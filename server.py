"""
AureaSim API Server
Lightweight FastAPI backend serving project data for the Vue frontend.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(errors='replace')

import os
import csv
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field
import asyncio
import json
import uuid
import hashlib
import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional
from aureasim.ai_generator import generate_project_branding
from aureasim.expert_review import (
    CandidateReviewLedger,
    ReviewRequest,
    apply_review_action,
    build_review_queue,
    load_review_files,
    save_review_files,
    verify_review_ledger,
)
from aureasim.parameter_candidates import CandidateSet, new_candidate_set_id, utc_now
from aureasim.baseline_editor import apply_baseline_update
from aureasim.baseline_candidates import candidate_set_from_baseline
from aureasim.reference_evaluation import attach_independent_references, parse_reference_csv
from aureasim.candidate_application import (
    apply_candidate_to_baseline,
    selected_candidate_ids,
)
from aureasim.candidate_catalog import discover_candidate_packages
from aureasim.hybrid_configuration import freeze_hybrid_configuration
from aureasim.historical_repository import (
    candidate_from_search,
    public_search_result,
    search_repository,
)
from aureasim.baseline_validation import validate_and_smoke, validation_state
from aureasim.configuration_validation import validate_parameter_references
from aureasim.reference_data import (
    apply_eligible_historical_analogues,
    configured_repository_path,
    repository_status,
    set_source_enabled,
    source_catalog,
    import_reference_package,
)

# ---------------------
# Configuration
# ---------------------
BASE_DIR = Path(__file__).parent.resolve()
PROJECTS_DIR = BASE_DIR / "projects"
DIAGRAMS_DIR = BASE_DIR / "diagrams"
ENV_PATH = BASE_DIR / ".env"

# Local evaluation models retain their original BPMN identifiers internally,
# while the diagram picker presents concise, human-readable titles.
CURATED_DIAGRAM_TITLES = {
    "Aid_Application_Settlement.bpmn": "Aid Application Settlement",
    "Business_Travel_Delegation_Request.bpmn": "Business Travel Delegation Request",
    "Cost_Document_Workflow.bpmn": "Cost Document Workflow",
    "Cost_Invoice_Workflow.bpmn": "Cost Invoice Workflow",
    "Embargo_IV.bpmn": "Embargo IV",
    "Milk_Support_Application.bpmn": "Milk Support Application",
    "Registry_Entry_Application.bpmn": "Registry Entry Application",
}

app = FastAPI(title="AureaSim API", version="1.2.0")


def _configured_local_path(environment_name: str, default: Path) -> Path:
    """Resolve optional product data without coupling the app to research folders."""
    configured = os.getenv(environment_name, "").strip()
    path = Path(configured).expanduser() if configured else default
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def _candidate_package_root() -> Path:
    return _configured_local_path(
        "AUREASIM_CANDIDATE_PACKAGES_DIR",
        BASE_DIR / "local_evidence" / "candidate_packages",
    )


def _historical_repository_path() -> Path:
    return configured_repository_path(BASE_DIR)


@app.get("/api/reference-data")
def get_reference_data_status():
    """Return the shared evidence repository status used by all interfaces."""
    return repository_status(BASE_DIR)


@app.get("/api/reference-data/sources")
def get_reference_sources():
    path = _historical_repository_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Reference repository is not configured")
    try:
        return {"sources": source_catalog(path)}
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.put("/api/reference-data/sources/{source_id}")
def update_reference_source(source_id: str, enabled: bool):
    path = _historical_repository_path()
    try:
        return {"sources": set_source_enabled(path, source_id, enabled)}
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/reference-data/import")
async def import_reference_data_package(reference_file: UploadFile = File(...)):
    if not (reference_file.filename or "").lower().endswith(".json"):
        raise HTTPException(status_code=415, detail="Reference packages must be JSON")
    try:
        package = json.loads((await reference_file.read()).decode("utf-8"))
        return {"sources": import_reference_package(_historical_repository_path(), package)}
    except (UnicodeDecodeError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/projects/{name}/reference-data/apply")
def apply_project_reference_data(name: str):
    """Apply the shared eligible-analogue policy to a project baseline."""
    project_path = _project_path_or_404(name)
    path = _historical_repository_path()
    status = repository_status(BASE_DIR)
    if not status["valid"]:
        raise HTTPException(status_code=409, detail="No valid reference repository is configured")
    base_path = project_path / "AutoGenerated_Base_params.json"
    if not base_path.exists():
        raise HTTPException(status_code=404, detail="Baseline parameters are not available")
    try:
        baseline = json.loads(base_path.read_text(encoding="utf-8"))
        metadata = baseline.get("metadata", {})
        updated, applied = apply_eligible_historical_analogues(
            baseline, repository_path=path, project_path=project_path,
            process_alias=str(metadata.get("process_alias") or name),
            process_id=str(metadata.get("process_id") or name),
            process_version=str(metadata.get("process_version") or "unknown"),
        )
        base_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"applied": applied, "repository": status}

# Task management for SSE streaming
tasks_progress: Dict[str, List[str]] = {}
tasks_status: Dict[str, str] = {}

# Allow the Vite dev server on port 3000 to call this API,
# and allow all Code Ocean workstation proxy origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000", "https://live.codeocean.com"],
    allow_origin_regex=r"https://.*\.codeocean\.com",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------
# Helpers
# ---------------------
def _parse_kpi_csv(csv_path: Path) -> list[dict]:
    """Read Simulation_KPIs.csv and return rows as dicts."""
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = {}
            for key, val in row.items():
                try:
                    parsed[key] = float(val)
                except (ValueError, TypeError):
                    parsed[key] = val
            rows.append(parsed)
    return rows


def _results_are_stale(project_path: Path) -> bool:
    """Return true only for an explicitly recorded baseline revision.

    File modification time alone is not evidence of a model change: project
    imports, copies, and archive restoration can legitimately create a newer
    baseline file beside older historical results.
    """
    kpi_file = project_path / "results" / "Simulation_KPIs.csv"
    base_params_file = project_path / "AutoGenerated_Base_params.json"
    if not kpi_file.exists() or not base_params_file.exists():
        return False
    try:
        metadata = json.loads(base_params_file.read_text(encoding="utf-8")).get("metadata", {})
        changed_at = metadata.get("manually_modified_at") or metadata.get("candidate_selected_at")
        if not changed_at:
            return False
        from datetime import datetime
        revision_time = datetime.fromisoformat(str(changed_at).replace("Z", "+00:00")).timestamp()
        return revision_time > kpi_file.stat().st_mtime
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        # Do not invalidate historical results merely because optional metadata
        # cannot be interpreted.
        return False


def _scan_project(project_path: Path) -> dict:
    """Build a summary dict for a single project directory."""
    results_dir = project_path / "results"
    name = project_path.name

    # Find KPI file
    kpi_file = results_dir / "Simulation_KPIs.csv"
    has_kpis = kpi_file.exists()

    # Find chart image
    chart_file = results_dir / "Scenario_Comparison.png"
    has_chart = chart_file.exists()

    base_params_file = project_path / "AutoGenerated_Base_params.json"
    results_stale = _results_are_stale(project_path)

    # Find report files
    report_extensions = {".docx", ".pdf", ".tex"}
    reports = []
    if results_dir.exists():
        for f in results_dir.iterdir():
            if f.suffix in report_extensions and not f.name.startswith("~$") and not f.name.startswith("."):
                reports.append(f.name)

    # Count scenario log files
    scenario_count = 0
    if results_dir.exists():
        scenario_count = sum(1 for f in results_dir.iterdir() if f.name.startswith("log_") and f.suffix == ".csv")

    # Get creation time based on wizard-generated files (KPIs or Params)
    try:
        # Priority 1: When the KPIs were generated
        kpi_file = project_path / "results" / "Simulation_KPIs.csv"
        # Priority 2: When the project was first initialized
        base_params = project_path / "AutoGenerated_Base_params.json"
        
        if kpi_file.exists():
            created_at = kpi_file.stat().st_mtime
        elif base_params.exists():
            created_at = base_params.stat().st_mtime
        else:
            # Fallback to directory birthtime (macOS specific)
            stat = project_path.stat()
            created_at = getattr(stat, 'st_birthtime', stat.st_mtime)
    except Exception:
        created_at = os.path.getmtime(project_path)

    # Branding logic (Icon, Color, and Name)
    config_file = project_path / "project_config.json"
    branding = {}
    if config_file.exists():
        try:
            branding = json.loads(config_file.read_text())
        except Exception:
            pass

    from aureasim.ai_generator import humanize_name
    display_name = branding.get("display_name") or humanize_name(name)

    return {
        "name": name,
        "display_name": display_name,
        "created_at": created_at,
        "icon": branding.get("icon"),
        "color": branding.get("color"),
        "has_kpis": has_kpis,
        "has_chart": has_chart,
        "reports": sorted(reports),
        "scenario_count": scenario_count,
        "results_stale": results_stale,
    }


def _candidate_paths(project_path: Path) -> tuple[Path, Path]:
    return (
        project_path / "parameter_candidates.json",
        project_path / "candidate_review_ledger.json",
    )


def _project_path_or_404(name: str) -> Path:
    project_path = PROJECTS_DIR / name
    if not project_path.exists() or not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    return project_path


# ---------------------
# API Endpoints
# ---------------------

@app.get("/api/projects")
def list_projects():
    """List all project directories under projects/."""
    if not PROJECTS_DIR.exists():
        return []

    projects = []
    for d in sorted(PROJECTS_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            projects.append(_scan_project(d))
    return projects


@app.get("/api/projects/{name}")
def get_project(name: str):
    """Get detailed data for a single project."""
    project_path = PROJECTS_DIR / name
    if not project_path.exists() or not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    info = _scan_project(project_path)

    # Parse KPIs if available
    kpi_file = project_path / "results" / "Simulation_KPIs.csv"
    if kpi_file.exists():
        info["kpis"] = _parse_kpi_csv(kpi_file)
    else:
        info["kpis"] = []

    # Include Params
    base_params_file = project_path / "AutoGenerated_Base_params.json"
    exp_params_file = project_path / "AutoGenerated_Experiment_Scenarios.json"
    
    info["base_params"] = None
    if base_params_file.exists():
        try:
            info["base_params"] = json.loads(base_params_file.read_text())
        except: pass
        
    info["exp_params"] = None
    if exp_params_file.exists():
        try:
            info["exp_params"] = json.loads(exp_params_file.read_text())
        except: pass

    # Aggregate, task-level process-mining references are optional local
    # evidence.  They are intentionally separate from the executable baseline.
    reference_file = project_path / "operational_references.json"
    info["operational_references"] = None
    if reference_file.exists():
        try:
            info["operational_references"] = json.loads(reference_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    # Include AI Summary text if exists (generated by the reporter, lives in results/)
    summary_file = project_path / "results" / "AI_Executive_Summary.md"
    info["ai_summary"] = summary_file.read_text() if summary_file.exists() else None

    return info


class BaselineParameterUpdate(BaseModel):
    parameter_type: str
    entity_id: str = ""
    values: Dict[str, object]
    justification: str = Field(min_length=3, max_length=2000)
    reviewer_id: str = Field(default="local-user", min_length=1, max_length=160)
    evidence_type: str = Field(default="expert_judgment", pattern="^(local_measurement|expert_judgment|policy_requirement|other)$")


class CandidateApplicationRequest(BaseModel):
    reviewer_id: str = Field(default="local-user", min_length=1, max_length=160)
    justification: str = Field(min_length=8, max_length=4000)


class HybridConfigurationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    reviewer_id: str = Field(default="local-user", min_length=1, max_length=160)
    justification: str = Field(min_length=8, max_length=4000)
    explicit_assumptions: Dict[str, str | float | int] = Field(default_factory=dict)


@app.patch("/api/projects/{name}/baseline-parameters")
def update_baseline_parameter(name: str, request: BaselineParameterUpdate):
    """Apply one validated manual edit and retain an auditable prior value."""
    project_path = _project_path_or_404(name)
    base_path = project_path / "AutoGenerated_Base_params.json"
    if not base_path.exists():
        raise HTTPException(status_code=404, detail="Baseline parameters are not available")
    try:
        baseline = json.loads(base_path.read_text(encoding="utf-8"))
        updated, previous = apply_baseline_update(
            baseline,
            request.parameter_type,
            request.entity_id,
        {**request.values, "evidence_type": request.evidence_type},
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    bpmn_files = [
        path for path in project_path.glob("*.bpmn")
        if not path.name.startswith("SANITIZED")
    ]
    if bpmn_files:
        reference_errors = validate_parameter_references(bpmn_files[0], updated)
        if reference_errors:
            raise HTTPException(
                status_code=422,
                detail="; ".join(reference_errors),
            )

    from datetime import datetime, timezone
    changed_at = datetime.now(timezone.utc).isoformat()
    metadata = updated.setdefault("metadata", {})
    metadata["manually_modified_at"] = changed_at
    metadata["manual_revision"] = int(metadata.get("manual_revision", 0)) + 1

    history_path = project_path / "baseline_parameter_history.json"
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise HTTPException(status_code=409, detail="Baseline edit history is unreadable")
    history.append({
        "revision": metadata["manual_revision"],
        "changed_at": changed_at,
        "reviewer_id": request.reviewer_id,
        "evidence_type": request.evidence_type,
        "justification": request.justification,
        "parameter_type": request.parameter_type,
        "entity_id": request.entity_id,
        "previous_value": previous,
        "new_value": request.values,
    })

    base_temp = base_path.with_suffix(".json.tmp")
    history_temp = history_path.with_suffix(".json.tmp")
    try:
        base_temp.write_text(
            json.dumps(updated, indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        history_temp.write_text(
            json.dumps(history, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(base_temp, base_path)
        os.replace(history_temp, history_path)
    except OSError as exc:
        for temporary in (base_temp, history_temp):
            if temporary.exists():
                temporary.unlink()
        raise HTTPException(status_code=500, detail=f"Could not save baseline edit: {exc}")

    return {
        "base_params": updated,
        "results_stale": (project_path / "results" / "Simulation_KPIs.csv").exists(),
        "revision": metadata["manual_revision"],
    }


@app.get("/api/projects/{name}/parameter-candidates")
def get_parameter_candidates(name: str):
    """Return alternatives, their review queue, and audit-chain status."""
    project_path = _project_path_or_404(name)
    candidate_path, ledger_path = _candidate_paths(project_path)
    if not candidate_path.exists():
        return {
            "available": False,
            "candidate_set": None,
            "review_queue": [],
            "audit_event_count": 0,
            "audit_chain_valid": True,
        }
    try:
        candidate_set, ledger = load_review_files(candidate_path, ledger_path)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=f"Candidate review data failed validation: {exc}")
    base_path = project_path / "AutoGenerated_Base_params.json"
    active_ids: list[str] = []
    if base_path.exists():
        try:
            active_ids = selected_candidate_ids(
                json.loads(base_path.read_text(encoding="utf-8")), candidate_set
            )
        except (OSError, json.JSONDecodeError):
            raise HTTPException(status_code=409, detail="Baseline parameters are unreadable")
    return {
        "available": True,
        "candidate_set": candidate_set.model_dump(mode="json"),
        "review_queue": [item.model_dump(mode="json") for item in build_review_queue(candidate_set)],
        "audit_event_count": len(ledger.events),
        "audit_chain_valid": True,
        "active_candidate_ids": active_ids,
    }


@app.post("/api/projects/{name}/parameter-candidates", status_code=201)
def import_parameter_candidates(name: str, candidate_set: CandidateSet):
    """Attach a validated candidate package to a project without overwriting one."""
    project_path = _project_path_or_404(name)
    candidate_path, ledger_path = _candidate_paths(project_path)
    if candidate_path.exists() or ledger_path.exists():
        raise HTTPException(status_code=409, detail="A parameter-candidate package already exists")
    base_path = project_path / "AutoGenerated_Base_params.json"
    if base_path.exists():
        actual_hash = hashlib.sha256(base_path.read_bytes()).hexdigest()
        if actual_hash != candidate_set.base_configuration_sha256:
            raise HTTPException(
                status_code=409,
                detail="Candidate package was built for a different base configuration",
            )
    ledger = CandidateReviewLedger(candidate_set_id=candidate_set.candidate_set_id)
    try:
        save_review_files(candidate_path, ledger_path, candidate_set, ledger)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=f"Candidate package could not be imported: {exc}")
    return {
        "available": True,
        "candidate_set_id": candidate_set.candidate_set_id,
        "candidates": len(candidate_set.candidates),
        "review_queue": [item.model_dump(mode="json") for item in build_review_queue(candidate_set)],
        "audit_chain_valid": True,
    }


@app.post("/api/projects/{name}/parameter-candidates/initialize", status_code=201)
def initialize_project_parameter_candidates(name: str):
    """Create a provenance-aware candidate set from the current executable baseline."""
    project_path = _project_path_or_404(name)
    candidate_path, ledger_path = _candidate_paths(project_path)
    if candidate_path.exists() or ledger_path.exists():
        raise HTTPException(status_code=409, detail="Parameter candidates are already initialized")
    base_path = project_path / "AutoGenerated_Base_params.json"
    if not base_path.exists():
        raise HTTPException(status_code=404, detail="Baseline parameters are not available")
    try:
        candidate_set = candidate_set_from_baseline(project_path)
        if not candidate_set.candidates:
            raise ValueError("The baseline contains no supported numeric parameters")
        ledger = CandidateReviewLedger(candidate_set_id=candidate_set.candidate_set_id)
        save_review_files(candidate_path, ledger_path, candidate_set, ledger)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=f"Candidates could not be initialized: {exc}")
    return {
        "available": True,
        "candidate_set_id": candidate_set.candidate_set_id,
        "candidates": len(candidate_set.candidates),
        "active_candidate_ids": selected_candidate_ids(
            json.loads(base_path.read_text(encoding="utf-8")), candidate_set
        ),
        "assembly_policy": candidate_set.assembly_policy,
    }


@app.post("/api/projects/{name}/parameter-candidates/expert-survey-reference")
async def import_expert_survey_references(name: str, reference_file: UploadFile = File(...)):
    """Attach matched expert-survey references without changing baseline values.

    The upload is intentionally CSV rather than a private workbook: it is a
    small, inspectable interchange format that can be exported from the survey
    template and archived with a research package.
    """
    project_path = _project_path_or_404(name)
    candidate_path, ledger_path = _candidate_paths(project_path)
    if not candidate_path.exists():
        raise HTTPException(status_code=404, detail="Parameter candidates are not available")
    if not (reference_file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Expert-survey references must be supplied as a CSV file")
    try:
        text = (await reference_file.read()).decode("utf-8-sig")
        rows = parse_reference_csv(text)
        if any(row["reference_type"] != "expert_survey_reference" for row in rows):
            raise ValueError("This endpoint accepts only expert_survey_reference rows")
        candidate_set, ledger = load_review_files(candidate_path, ledger_path)
        updated_set, matched = attach_independent_references(candidate_set, rows)
        if not matched:
            raise ValueError("No expert-survey reference matches this project's parameters")
        save_review_files(candidate_path, ledger_path, updated_set, ledger)
    except (UnicodeDecodeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=f"Could not attach expert-survey references: {exc}")
    return {
        "matched_candidates": matched,
        "reference_type": "expert_survey_reference",
        "candidate_set": updated_set.model_dump(mode="json"),
    }


@app.get("/api/projects/{name}/parameter-candidates/discover")
def discover_project_parameter_candidates(name: str):
    project_path = _project_path_or_404(name)
    candidate_path, _ = _candidate_paths(project_path)
    base_path = project_path / "AutoGenerated_Base_params.json"
    if not base_path.exists():
        raise HTTPException(status_code=404, detail="Baseline parameters are not available")
    packages = discover_candidate_packages(
        BASE_DIR,
        base_path,
        roots=[_candidate_package_root()],
    )
    return {
        "already_attached": candidate_path.exists(),
        "packages": [{key: value for key, value in item.items() if key != "path"} for item in packages],
        "compatible_count": sum(bool(item["compatible"]) for item in packages),
    }


@app.post("/api/projects/{name}/parameter-candidates/auto-attach", status_code=201)
def auto_attach_project_parameter_candidates(name: str):
    project_path = _project_path_or_404(name)
    candidate_path, ledger_path = _candidate_paths(project_path)
    if candidate_path.exists() or ledger_path.exists():
        raise HTTPException(status_code=409, detail="A parameter-candidate package already exists")
    base_path = project_path / "AutoGenerated_Base_params.json"
    if not base_path.exists():
        raise HTTPException(status_code=404, detail="Baseline parameters are not available")
    compatible = [
        item
        for item in discover_candidate_packages(
            BASE_DIR,
            base_path,
            roots=[_candidate_package_root()],
        )
        if item["compatible"]
    ]
    if not compatible:
        raise HTTPException(status_code=404, detail="No candidate package exactly matches this baseline")
    if len(compatible) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple compatible packages were found; import the intended package explicitly",
        )
    try:
        candidate_set = CandidateSet.model_validate_json(
            compatible[0]["path"].read_text(encoding="utf-8")
        )
        ledger = CandidateReviewLedger(candidate_set_id=candidate_set.candidate_set_id)
        save_review_files(candidate_path, ledger_path, candidate_set, ledger)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"Compatible package could not be attached: {exc}")
    return {
        "available": True,
        "candidate_set_id": candidate_set.candidate_set_id,
        "candidates": len(candidate_set.candidates),
        "process_alias": candidate_set.process_alias,
    }


@app.get("/api/projects/{name}/parameter-candidates/audit")
def get_parameter_candidate_audit(name: str):
    project_path = _project_path_or_404(name)
    candidate_path, ledger_path = _candidate_paths(project_path)
    if not candidate_path.exists():
        raise HTTPException(status_code=404, detail="Parameter candidates are not available")
    try:
        _, ledger = load_review_files(candidate_path, ledger_path)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=f"Candidate review data failed validation: {exc}")
    return ledger.model_dump(mode="json")


@app.post("/api/projects/{name}/parameter-candidates/{candidate_id}/review")
def review_parameter_candidate(name: str, candidate_id: str, request: ReviewRequest):
    """Apply one justified expert decision and append its hash-chained event."""
    project_path = _project_path_or_404(name)
    candidate_path, ledger_path = _candidate_paths(project_path)
    if not candidate_path.exists():
        raise HTTPException(status_code=404, detail="Parameter candidates are not available")
    try:
        candidate_set, ledger = load_review_files(candidate_path, ledger_path)
        updated_set, updated_ledger, event = apply_review_action(
            candidate_set, ledger, candidate_id, request
        )
        verify_review_ledger(updated_ledger)
        save_review_files(candidate_path, ledger_path, updated_set, updated_ledger)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "candidate": next(
            item.model_dump(mode="json")
            for item in updated_set.candidates
            if item.candidate_id == event.after_candidate_id
        ),
        "event": event.model_dump(mode="json"),
        "review_queue": [item.model_dump(mode="json") for item in build_review_queue(updated_set)],
        "audit_chain_valid": True,
    }


@app.post("/api/projects/{name}/parameter-candidates/{candidate_id}/apply")
def apply_parameter_candidate(name: str, candidate_id: str, request: CandidateApplicationRequest):
    """Select one executable candidate and write it into the active baseline."""
    from datetime import datetime, timezone

    project_path = _project_path_or_404(name)
    candidate_path, ledger_path = _candidate_paths(project_path)
    base_path = project_path / "AutoGenerated_Base_params.json"
    if not candidate_path.exists():
        raise HTTPException(status_code=404, detail="Parameter candidates are not available")
    if not base_path.exists():
        raise HTTPException(status_code=404, detail="Baseline parameters are not available")
    try:
        candidate_set, _ = load_review_files(candidate_path, ledger_path)
        candidate = next(item for item in candidate_set.candidates if item.candidate_id == candidate_id)
        baseline = json.loads(base_path.read_text(encoding="utf-8"))
        updated, previous, representation = apply_candidate_to_baseline(baseline, candidate)
    except StopIteration:
        raise HTTPException(status_code=404, detail=f"Candidate not found: {candidate_id}")
    except (ValueError, TypeError, json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    bpmn_files = [path for path in project_path.glob("*.bpmn") if not path.name.startswith("SANITIZED")]
    if bpmn_files:
        reference_errors = validate_parameter_references(bpmn_files[0], updated)
        if reference_errors:
            raise HTTPException(status_code=422, detail="; ".join(reference_errors))

    changed_at = datetime.now(timezone.utc).isoformat()
    metadata = updated.setdefault("metadata", {})
    metadata["candidate_selected_at"] = changed_at
    metadata["candidate_selection_revision"] = int(metadata.get("candidate_selection_revision", 0)) + 1

    history_path = project_path / "parameter_selection_history.json"
    try:
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=409, detail="Parameter selection history is unreadable")
    event = {
        "revision": metadata["candidate_selection_revision"],
        "changed_at": changed_at,
        "reviewer_id": request.reviewer_id,
        "justification": request.justification,
        "candidate_set_id": candidate_set.candidate_set_id,
        "candidate_id": candidate.candidate_id,
        "parameter_family": candidate.parameter_family,
        "entity_id": candidate.entity_id,
        "method": candidate.method.value,
        "previous_value": previous,
        "applied_representation": representation,
    }
    history.append(event)

    base_temp = base_path.with_suffix(".json.tmp")
    history_temp = history_path.with_suffix(".json.tmp")
    try:
        base_temp.write_text(json.dumps(updated, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        history_temp.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(base_temp, base_path)
        os.replace(history_temp, history_path)
    except OSError as exc:
        for temporary in (base_temp, history_temp):
            if temporary.exists():
                temporary.unlink()
        raise HTTPException(status_code=500, detail=f"Could not apply parameter candidate: {exc}")

    return {
        "candidate": candidate.model_dump(mode="json"),
        "application_event": event,
        "base_params": updated,
        "active_candidate_ids": selected_candidate_ids(updated, candidate_set),
        "results_stale": (project_path / "results" / "Simulation_KPIs.csv").exists(),
    }


@app.post("/api/projects/{name}/hybrid-configurations", status_code=201)
def create_hybrid_configuration(name: str, request: HybridConfigurationRequest):
    project_path = _project_path_or_404(name)
    state = validation_state(project_path)
    if state["status"] != "valid" or not state["current"]:
        raise HTTPException(
            status_code=409,
            detail="Validate the current baseline successfully before freezing a hybrid configuration",
        )
    candidate_path, ledger_path = _candidate_paths(project_path)
    if not candidate_path.exists():
        raise HTTPException(status_code=404, detail="Parameter candidates are not available")
    try:
        candidate_set, _ = load_review_files(candidate_path, ledger_path)
        hybrid, export_dir = freeze_hybrid_configuration(
            project_path=project_path,
            candidate_set=candidate_set,
            name=request.name,
            reviewer_id=request.reviewer_id,
            justification=request.justification,
            explicit_assumptions=request.explicit_assumptions,
        )
    except FileExistsError:
        raise HTTPException(status_code=409, detail="This exact hybrid configuration is already frozen")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "hybrid_configuration": hybrid.model_dump(mode="json"),
        "download_url": (
            f"/api/projects/{name}/hybrid-configurations/"
            f"{export_dir.name}/download"
        ),
    }


@app.get("/api/projects/{name}/baseline-validation")
def get_baseline_validation(name: str):
    return validation_state(_project_path_or_404(name))


@app.post("/api/projects/{name}/baseline-validation")
def run_baseline_validation(name: str):
    project_path = _project_path_or_404(name)
    try:
        report = validate_and_smoke(project_path=project_path)
    except (OSError, ValueError, json.JSONDecodeError, ET.ParseError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "status": report["status"],
        "current": True,
        "report": report,
    }


@app.get("/api/projects/{name}/hybrid-configurations/{export_id}/download")
def download_hybrid_configuration(name: str, export_id: str):
    project_path = _project_path_or_404(name)
    root = (project_path / "hybrid_configurations").resolve()
    export_dir = (root / export_id).resolve()
    if export_dir.parent != root or not export_dir.is_dir():
        raise HTTPException(status_code=404, detail="Hybrid configuration was not found")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in ("hybrid_selection.json", "AutoGenerated_Base_params.json"):
            source = export_dir / filename
            if not source.exists():
                raise HTTPException(status_code=409, detail="Hybrid export is incomplete")
            archive.write(source, arcname=filename)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{export_id}.zip"'},
    )


def _historical_search(name: str, task_id: str):
    project_path = _project_path_or_404(name)
    repository_path = _historical_repository_path()
    if not repository_path.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Historical-task evidence is not configured. Set "
                "AUREASIM_HISTORICAL_REPOSITORY or place a repository at "
                "local_evidence/historical_tasks/historical_task_repository.json."
            ),
        )
    candidate_path, ledger_path = _candidate_paths(project_path)
    candidate_set = None
    if candidate_path.exists():
        try:
            candidate_set, _ = load_review_files(candidate_path, ledger_path)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=f"Candidate data failed validation: {exc}")
    try:
        result = search_repository(
            repository_path=repository_path,
            project_path=project_path,
            task_id=task_id,
            process_alias=candidate_set.process_alias if candidate_set else name,
            process_id=candidate_set.process_id if candidate_set else "",
            process_version=candidate_set.process_version if candidate_set else "unknown",
        )
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return project_path, repository_path, candidate_set, result


@app.get("/api/projects/{name}/historical-analogues/{task_id}")
def find_project_historical_analogues(name: str, task_id: str):
    """Search calibration-only tasks while excluding the target process."""
    _, _, _, result = _historical_search(name, task_id)
    return public_search_result(result)


@app.post("/api/projects/{name}/historical-analogues/{task_id}/candidate", status_code=201)
def add_historical_analogue_candidate(name: str, task_id: str):
    """Create a candidate only when the frozen analogue evidence rules pass."""
    project_path, repository_path, candidate_set, result = _historical_search(name, task_id)
    try:
        candidate = candidate_from_search(result, repository_path)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    candidate_path, ledger_path = _candidate_paths(project_path)
    if candidate_set is None:
        base_path = project_path / "AutoGenerated_Base_params.json"
        if not base_path.exists():
            raise HTTPException(status_code=404, detail="Baseline parameters are not available")
        candidate_set = CandidateSet(
            candidate_set_id=new_candidate_set_id(candidate.process_alias, [candidate.candidate_id]),
            process_alias=candidate.process_alias,
            process_id=candidate.process_id,
            process_version=candidate.process_version,
            created_at=utc_now(),
            assembly_policy="product_historical_analogue_search",
            base_configuration_sha256=hashlib.sha256(base_path.read_bytes()).hexdigest(),
            candidates=[candidate],
        )
        ledger = CandidateReviewLedger(candidate_set_id=candidate_set.candidate_set_id)
    else:
        if any(item.candidate_id == candidate.candidate_id for item in candidate_set.candidates):
            raise HTTPException(status_code=409, detail="This historical-analogue candidate already exists")
        if candidate.process_alias != candidate_set.process_alias:
            raise HTTPException(status_code=409, detail="Historical candidate belongs to another process")
        _, ledger = load_review_files(candidate_path, ledger_path)
        candidate_set = CandidateSet.model_validate({
            **candidate_set.model_dump(mode="json"),
            "candidates": [
                *[item.model_dump(mode="json") for item in candidate_set.candidates],
                candidate.model_dump(mode="json"),
            ],
        })
    try:
        save_review_files(candidate_path, ledger_path, candidate_set, ledger)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"Historical candidate could not be saved: {exc}")
    return {
        "candidate": candidate.model_dump(mode="json"),
        "candidate_set_id": candidate_set.candidate_set_id,
        "search": public_search_result(result),
    }

@app.delete("/api/projects/{name}")
def delete_project(name: str):
    """Delete a project and its directory."""
    import shutil
    project_path = PROJECTS_DIR / name
    if not project_path.exists() or not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
        
    try:
        shutil.rmtree(project_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {str(e)}")
        
    return {"success": True, "deleted": name}

@app.get("/api/projects/{name}/analytics")
def get_project_analytics(name: str):
    """
    Compute rich analytics from per-scenario event logs (log_*.csv).
    Returns per-activity and per-resource statistics for each scenario.
    """
    import csv as _csv
    from datetime import datetime

    results_dir = PROJECTS_DIR / name / "results"
    if not results_dir.exists():
        raise HTTPException(status_code=404, detail="Project results not found")

    log_files = sorted(results_dir.glob("log_*.csv"))
    if not log_files:
        raise HTTPException(status_code=404, detail="No scenario log files found")

    def parse_dt(s: str) -> datetime:
        # Handle timezone-aware ISO strings produced by Prosimos
        s = s.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z",
                    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        raise ValueError(f"Cannot parse datetime: {s!r}")

    def seconds(a: datetime, b: datetime) -> float:
        return (b - a).total_seconds()

    scenarios = []
    for log_path in log_files:
        scenario_name = log_path.stem[len("log_"):]  # strip "log_" prefix

        rows = []
        with open(log_path, encoding="utf-8-sig", newline="") as f:
            for row in _csv.DictReader(f):
                try:
                    rows.append({
                        "case_id":     row["case_id"],
                        "activity":    row["activity"],
                        "enable_time": parse_dt(row["enable_time"]),
                        "start_time":  parse_dt(row["start_time"]),
                        "end_time":    parse_dt(row["end_time"]),
                        "resource":    row["resource"],
                    })
                except Exception:
                    continue  # skip malformed rows

        if not rows:
            continue

        # ── Activity statistics ──────────────────────────────────────────────
        from collections import defaultdict
        act_process: dict = defaultdict(list)  # activity → [processing_seconds]
        act_wait:    dict = defaultdict(list)  # activity → [waiting_seconds]

        for r in rows:
            proc = seconds(r["start_time"], r["end_time"])
            wait = seconds(r["enable_time"], r["start_time"])
            act_process[r["activity"]].append(max(proc, 0))
            act_wait[r["activity"]].append(max(wait, 0))

        activities = []
        for act in sorted(act_process.keys()):
            ps = act_process[act]
            ws = act_wait[act]
            activities.append({
                "activity":        act,
                "count":           len(ps),
                "avg_processing_s": round(sum(ps) / len(ps), 1),
                "min_processing_s": round(min(ps), 1),
                "max_processing_s": round(max(ps), 1),
                "avg_wait_s":      round(sum(ws) / len(ws), 1),
                "max_wait_s":      round(max(ws), 1),
            })

        # ── Case cycle times ─────────────────────────────────────────────────
        case_times: dict = defaultdict(lambda: {"start": None, "end": None})
        for r in rows:
            ct = case_times[r["case_id"]]
            if ct["start"] is None or r["enable_time"] < ct["start"]:
                ct["start"] = r["enable_time"]
            if ct["end"] is None or r["end_time"] > ct["end"]:
                ct["end"] = r["end_time"]

        cycle_seconds = [
            seconds(v["start"], v["end"])
            for v in case_times.values()
            if v["start"] and v["end"]
        ]

        # Histogram: 10 equal-width buckets
        cycle_hist = []
        if cycle_seconds:
            lo, hi = min(cycle_seconds), max(cycle_seconds)
            n_bins = 10
            width = (hi - lo) / n_bins if hi > lo else 1
            bins = [0] * n_bins
            for cs in cycle_seconds:
                idx = min(int((cs - lo) / width), n_bins - 1)
                bins[idx] += 1
            cycle_hist = [
                {
                    "label": f"{round((lo + i * width) / 3600, 1)}h",
                    "count": bins[i],
                }
                for i in range(n_bins)
            ]

        # ── Resource utilisation ─────────────────────────────────────────────
        # Simulation span = earliest enable → latest end across all events
        sim_start = min(r["enable_time"] for r in rows)
        sim_end   = max(r["end_time"]    for r in rows)
        sim_span  = seconds(sim_start, sim_end)

        res_busy: dict = defaultdict(float)
        for r in rows:
            res_busy[r["resource"]] += max(seconds(r["start_time"], r["end_time"]), 0)

        resources = []
        for res in sorted(res_busy.keys()):
            utilisation = min(round(res_busy[res] / sim_span * 100, 1), 100) if sim_span > 0 else 0
            resources.append({
                "resource":       res,
                "busy_hours":     round(res_busy[res] / 3600, 2),
                "utilisation_pct": utilisation,
            })

        # ── Summary ──────────────────────────────────────────────────────────
        avg_cycle_h = round(sum(cycle_seconds) / len(cycle_seconds) / 3600, 2) if cycle_seconds else 0
        scenarios.append({
            "scenario":    scenario_name,
            "activities":  activities,
            "resources":   resources,
            "cycle_times": {
                "avg_hours": avg_cycle_h,
                "min_hours": round(min(cycle_seconds) / 3600, 2) if cycle_seconds else 0,
                "max_hours": round(max(cycle_seconds) / 3600, 2) if cycle_seconds else 0,
                "histogram": cycle_hist,
            },
        })

    return {"scenarios": scenarios}


@app.get("/api/projects/{name}/chart")
def get_project_chart(name: str):
    """Serve the Scenario_Comparison.png chart for a project."""
    chart_path = PROJECTS_DIR / name / "results" / "Scenario_Comparison.png"
    if not chart_path.exists():
        raise HTTPException(status_code=404, detail="Chart not found")
    return FileResponse(chart_path, media_type="image/png")


@app.get("/api/projects/{name}/download/{filename}")
def download_report(name: str, filename: str):
    """Download a report file from a project's results directory."""
    file_path = PROJECTS_DIR / name / "results" / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found")

    # Security: prevent path traversal
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    return FileResponse(file_path, filename=filename)


@app.get("/api/projects/{name}/report")
def get_project_report(name: str):
    """Return the markdown report for a project as plain text."""
    project_path = PROJECTS_DIR / name
    if not project_path.exists() or not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    summary_file = project_path / "results" / "AI_Executive_Summary.md"
    if not summary_file.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(summary_file.read_text(encoding="utf-8"))


@app.get("/api/projects/{name}/bpmn")
def get_project_bpmn(name: str):
    """Return the BPMN XML for a project (original file, not sanitized)."""
    from fastapi.responses import PlainTextResponse
    project_path = PROJECTS_DIR / name
    if not project_path.exists() or not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    bpmn_files = [f for f in project_path.iterdir()
                  if f.suffix == ".bpmn" and not f.name.startswith("SANITIZED")]
    if not bpmn_files:
        bpmn_files = [f for f in project_path.iterdir() if f.suffix == ".bpmn"]
    if not bpmn_files:
        raise HTTPException(status_code=404, detail="BPMN file not found")
    return PlainTextResponse(bpmn_files[0].read_text(encoding="utf-8"),
                             media_type="application/xml")


@app.get("/api/diagrams/{name}/xml")
def get_diagram_xml(name: str):
    """Return the raw BPMN XML for a library diagram file."""
    from fastapi.responses import PlainTextResponse
    if ".." in name or "/" in name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    diagram_path = DIAGRAMS_DIR / name
    if not diagram_path.exists():
        raise HTTPException(status_code=404, detail="Diagram not found")
    return PlainTextResponse(diagram_path.read_text(encoding="utf-8"),
                             media_type="application/xml")


@app.get("/api/diagrams")
def list_diagrams():
    """List BPMN files in the diagrams/ directory with rich metadata."""
    if not DIAGRAMS_DIR.exists():
        return []

    diagrams = []
    for f in sorted(DIAGRAMS_DIR.iterdir()):
        if f.suffix == ".bpmn":
            # Extract human-readable process name from the BPMN XML
            process_name = f.stem.replace('_', ' ').replace('-', ' ')  # humanized fallback
            try:
                tree = ET.parse(f)
                root = tree.getroot()
                ns = root.tag.split('}')[0].lstrip('{') if '}' in root.tag else ''
                prefix = f'{{{ns}}}' if ns else ''
                # 1. Try <process name="..."> (most BPMN modellers put the name here)
                for child in root:
                    local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if local.lower() == 'process':
                        pname = child.get('name', '').strip()
                        if pname:
                            process_name = pname
                            break
                else:
                    # 2. Try <definitions name="...">
                    dname = root.get('name', '').strip()
                    if dname:
                        process_name = dname
            except Exception:
                pass
            process_name = CURATED_DIAGRAM_TITLES.get(f.name, process_name)
            diagrams.append({
                "name": f.name,
                "process_name": process_name,
                "size_bytes": f.stat().st_size,
                "created_at": f.stat().st_mtime,
            })
    return diagrams


@app.get("/api/examples/{name}/xml")
def get_example_xml(name: str):
    """Return the raw BPMN XML for an example diagram file."""
    from fastapi.responses import PlainTextResponse
    if ".." in name or "/" in name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # We strip the .bpmn and append it, or we just trust `name`
    # The name is usually "ExampleName.bpmn"
    examples_dir = BASE_DIR / "examples"
    diagram_path = examples_dir / name
    if not diagram_path.exists():
        raise HTTPException(status_code=404, detail="Example diagram not found")
    return PlainTextResponse(diagram_path.read_text(encoding="utf-8"),
                             media_type="application/xml")


@app.get("/api/examples")
def list_examples():
    """List BPMN files in the examples/ directory with rich metadata."""
    examples_dir = BASE_DIR / "examples"
    if not examples_dir.exists():
        return []

    examples = []
    for f in sorted(examples_dir.iterdir()):
        if f.suffix == ".bpmn":
            process_name = f.stem.replace('_', ' ').replace('-', ' ')
            try:
                tree = ET.parse(f)
                root = tree.getroot()
                ns = root.tag.split('}')[0].lstrip('{') if '}' in root.tag else ''
                for child in root:
                    local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if local.lower() == 'process':
                        pname = child.get('name', '').strip()
                        if pname:
                            process_name = pname
                            break
                else:
                    dname = root.get('name', '').strip()
                    if dname:
                        process_name = dname
            except Exception:
                pass
            examples.append({
                "name": f.name,
                "process_name": process_name,
                "size_bytes": f.stat().st_size,
                "created_at": f.stat().st_mtime,
            })
    return examples



@app.post("/api/diagrams/upload")
async def upload_diagram(
    file: UploadFile = File(...),
    resolution: str = Form(default=""),  # "replace" | "rename:<new_name>" | ""
):
    """
    Upload a BPMN file to the diagrams/ directory.
    - If the file already exists and no resolution is provided → 409 Conflict.
    - resolution="replace"        → overwrite existing file.
    - resolution="rename:NewName" → save under the new name.
    """
    DIAGRAMS_DIR.mkdir(exist_ok=True)

    if not file.filename or not file.filename.endswith(".bpmn"):
        raise HTTPException(status_code=400, detail="Only .bpmn files are accepted.")

    content = await file.read()

    # Validate: must be well-formed XML with a BPMN <definitions> root
    try:
        root = ET.fromstring(content)
        local = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        if local.lower() not in ("definitions", "semantic:definitions"):
            raise ValueError(f"Root element is <{local}>, expected <definitions>")
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"File is not valid XML: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Determine target filename
    target_name = file.filename
    if resolution.startswith("rename:"):
        proposed = resolution[len("rename:"):].strip()
        if not proposed.endswith(".bpmn"):
            proposed += ".bpmn"
        target_name = proposed

    target_path = DIAGRAMS_DIR / target_name

    # Duplicate check (only when not replacing)
    if target_path.exists() and resolution != "replace":
        # Suggest a suffixed name e.g. MyModel_2.bpmn
        stem = Path(target_name).stem
        i = 2
        while (DIAGRAMS_DIR / f"{stem}_{i}.bpmn").exists():
            i += 1
        suggested = f"{stem}_{i}.bpmn"
        return {
            "conflict": True,
            "existing_name": target_name,
            "suggested_rename": suggested,
            "options": ["replace", "rename", "cancel"],
        }

    target_path.write_bytes(content)
    return {"success": True, "saved_as": target_name}


@app.delete("/api/diagrams/{name}")
def delete_diagram(name: str):
    """
    Delete a BPMN file from diagrams/.
    Blocked if any project folder contains a .bpmn with the same stem.
    """
    if "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    diagram_path = DIAGRAMS_DIR / name
    if not diagram_path.exists():
        raise HTTPException(status_code=404, detail="Diagram not found.")

    # Guard: check if any project references this model
    stem = Path(name).stem
    blocking = []
    if PROJECTS_DIR.exists():
        for proj in PROJECTS_DIR.iterdir():
            if proj.is_dir():
                for bf in proj.glob("*.bpmn"):
                    if bf.stem == stem:
                        blocking.append(proj.name)
                        break

    if blocking:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Model is referenced by existing projects and cannot be deleted.",
                "blocking_projects": blocking,
            },
        )

    diagram_path.unlink()
    return {"success": True, "deleted": name}


class SettingsUpdate(BaseModel):
    api_key: Optional[str] = None


@app.get("/api/version")
def get_version():
    """Return the application version."""
    try:
        from aureasim import __version__
    except ImportError:
        __version__ = "unknown"
    return {"version": __version__}


@app.get("/api/settings")
def get_settings():
    """Return current settings (API key masked)."""
    api_key = ""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")

    if api_key:
        masked = api_key[:4] + "•" * (len(api_key) - 8) + api_key[-4:]
    else:
        masked = ""

    return {
        "api_key_set": bool(api_key),
        "api_key_masked": masked,
    }


@app.put("/api/settings")
def update_settings(settings: SettingsUpdate):
    """Update .env settings."""
    if settings.api_key is not None:
        # Read existing .env content
        lines = []
        found = False
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    lines.append(f'GEMINI_API_KEY="{settings.api_key}"')
                    found = True
                else:
                    lines.append(line)

        if not found:
            lines.append(f'GEMINI_API_KEY="{settings.api_key}"')

        ENV_PATH.write_text("\n".join(lines) + "\n")

    return {"status": "ok"}


# ---------------------
# Simulation Trigger (Phase 2)
# ---------------------
class SimulateRequest(BaseModel):
    diagram_name: str
    industry_context: str = ""
    num_scenarios: int = 3
    demo_mode: bool = False
    grounding_mode: str = "heuristic"
    inflation_factor: float = 1.0
    skip_ai_report: bool = False
    report_formats: list[str] = ["docx", "pdf", "latex"]

@app.post("/api/simulate")
def start_simulation(req: SimulateRequest):
    task_id = str(uuid.uuid4())
    tasks_progress[task_id] = []
    tasks_status[task_id] = "running"
    
    # Validate diagram if not in demo mode
    if not req.demo_mode:
        diagram_path = DIAGRAMS_DIR / req.diagram_name
        if not diagram_path.exists():
            raise HTTPException(status_code=404, detail="Diagram not found.")

    api_key = ""
    if not req.demo_mode:
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    
        if not api_key:
            api_key = os.getenv("GEMINI_API_KEY", "")
            
        if not api_key:
            req.demo_mode = True
            print(f"[INFO] GEMINI_API_KEY is missing. Automatically falling back to offline demo simulation mode for: {req.diagram_name}")

    def progress_cb(msg):
        tasks_progress[task_id].append(msg)
        print(f"[Task {task_id}] {msg}")

    def bg_task():
        try:
            if req.demo_mode:
                from aureasim.headless import run_demo_simulation
                # Pass the diagram_name (which should be "ExampleName.bpmn") so run_demo_simulation knows which example to load
                stem = Path(req.diagram_name).stem if req.diagram_name else "RES_Sales_Process"
                run_demo_simulation(progress_cb, project_name_override=stem)
            else:
                from aureasim.headless import run_automated_simulation
                run_automated_simulation(
                    original_bpmn_path=str(DIAGRAMS_DIR / req.diagram_name), 
                    industry_context=req.industry_context, 
                    num_scenarios=req.num_scenarios, 
                    api_key=api_key, 
                    progress_callback=progress_cb,
                    generation_mode=req.grounding_mode,
                    inflation_factor=req.inflation_factor,
                    skip_ai_report=req.skip_ai_report,
                    report_formats=req.report_formats
                )
            tasks_status[task_id] = "done"
            progress_cb("[DONE] Simulation completed.")
        except Exception as e:
            progress_cb(f"[FATAL ERROR] {str(e)}")
            tasks_status[task_id] = "error"

    import threading
    t = threading.Thread(target=bg_task, daemon=True)
    t.start()
    return {"task_id": task_id}

@app.get("/api/simulate/{task_id}/stream")
async def stream_simulation(task_id: str):
    if task_id not in tasks_status:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        last_idx = 0
        while True:
            current_len = len(tasks_progress[task_id])
            if current_len > last_idx:
                for msg in tasks_progress[task_id][last_idx:current_len]:
                    yield f"data: {json.dumps({'msg': msg, 'status': tasks_status[task_id]})}\n\n"
                last_idx = current_len
            
            if tasks_status[task_id] in ["done", "error"] and last_idx == current_len:
                # Send final status and break
                yield f"data: {json.dumps({'msg': '[EOF]', 'status': tasks_status[task_id]})}\n\n"
                break
                
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ---------------------
# Static Frontend (production build)
# ---------------------
class SPAStaticFiles(StaticFiles):
    """Serve index.html for browser navigation to client-side Vue routes."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            normalized = path.replace("\\", "/").lstrip("/")
            accept = dict(scope.get("headers", [])).get(b"accept", b"").decode(
                "latin-1", errors="ignore"
            )
            is_frontend_navigation = (
                exc.status_code == 404
                and scope.get("method") in {"GET", "HEAD"}
                and "text/html" in accept
                and not normalized.startswith(("api/", "assets/"))
            )
            if is_frontend_navigation:
                return await super().get_response("index.html", scope)
            raise


DIST_DIR = BASE_DIR / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount("/", SPAStaticFiles(directory=str(DIST_DIR), html=True), name="frontend")

# ---------------------
# Entry point
# ---------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
