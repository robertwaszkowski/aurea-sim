"""Validation and one-case Prosimos smoke execution for active baselines."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aureasim.configuration_validation import validate_parameter_references


SUPPORTED_DISTRIBUTIONS = {
    "fix", "default", "expon", "norm", "uniform", "gamma", "triang", "lognorm",
    "histogram_sampling",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _distribution_errors(distribution: dict[str, Any], label: str) -> list[str]:
    name = distribution.get("distribution_name")
    params = distribution.get("distribution_params")
    errors: list[str] = []
    if name not in SUPPORTED_DISTRIBUTIONS:
        errors.append(f"{label}: unsupported distribution '{name}'")
        return errors
    if name == "histogram_sampling":
        histogram = distribution.get("histogram_data") or params
        if not isinstance(histogram, dict) or not histogram.get("cdf") or not histogram.get("bin_midpoints"):
            errors.append(f"{label}: histogram distribution is incomplete")
        return errors
    if not isinstance(params, list):
        return [f"{label}: distribution_params must be a list"]
    values = []
    for item in params:
        value = item.get("value") if isinstance(item, dict) else item
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            errors.append(f"{label}: distribution parameters must be finite numbers")
            return errors
        values.append(float(value))
    minimum = 1 if name == "fix" else 2 if name == "default" else 4
    if len(values) < minimum:
        errors.append(f"{label}: {name} requires at least {minimum} numeric parameters")
    if name not in {"fix", "default"} and len(values) >= 4 and values[-3] <= 0:
        errors.append(f"{label}: distribution scale must be greater than zero")
    if len(values) >= 2 and name == "norm" and values[1] < 0:
        errors.append(f"{label}: normal standard deviation cannot be negative")
    return errors


def validate_baseline_structure(bpmn_path: Path, params: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors = validate_parameter_references(bpmn_path, params)
    warnings: list[str] = []
    errors.extend(_distribution_errors(params.get("arrival_time_distribution", {}), "arrival time"))

    calendars = {str(item.get("id")) for item in params.get("resource_calendars", []) if item.get("id")}
    resource_ids: set[str] = set()
    profile_ids: set[str] = set()
    for profile in params.get("resource_profiles", []):
        profile_id = str(profile.get("id") or "")
        if not profile_id or profile_id in profile_ids:
            errors.append(f"duplicate or missing resource profile id: {profile_id or '<empty>'}")
        profile_ids.add(profile_id)
        resources = profile.get("resource_list", [])
        if not resources:
            errors.append(f"resource profile {profile_id} has no resources")
        for resource in resources:
            identifier = str(resource.get("id") or "")
            if not identifier or identifier in resource_ids:
                errors.append(f"duplicate or missing resource id: {identifier or '<empty>'}")
            resource_ids.add(identifier)
            amount = resource.get("amount", 1)
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 1:
                errors.append(f"resource {identifier} must have amount >= 1")
            calendar = str(resource.get("calendar") or "")
            if calendars and calendar not in calendars:
                errors.append(f"resource {identifier} references unknown calendar {calendar}")

    assignments = params.get("task_resource_distribution", [])
    if not assignments:
        errors.append("no task-resource distributions are defined")
    for assignment in assignments:
        task_id = str(assignment.get("task_id") or "")
        resources = assignment.get("resources", [])
        if not resources:
            errors.append(f"task {task_id} has no resource assignment")
        for resource in resources:
            resource_id = str(resource.get("resource_id") or "")
            if resource_id not in resource_ids:
                errors.append(f"task {task_id} references unknown resource {resource_id}")
            errors.extend(_distribution_errors(resource, f"task {task_id} / resource {resource_id}"))

    for gateway in params.get("gateway_branching_probabilities", []):
        values = [float(item.get("value", 0)) for item in gateway.get("probabilities", [])]
        if values and not math.isclose(sum(values), 1.0, abs_tol=1e-6):
            errors.append(f"gateway {gateway.get('gateway_id')} probabilities must sum to 1")
    if not params.get("gateway_branching_probabilities"):
        warnings.append("No gateway probabilities are defined; this is valid only when the model has no branching gateway requiring them")
    return sorted(set(errors)), warnings


def run_smoke_validation(
    *,
    bpmn_path: Path,
    params: dict[str, Any],
    run_dir: Path,
    runner: Callable[[Path, dict[str, Any], Path], None] | None = None,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "smoke_log.csv"
    try:
        if runner is not None:
            runner(bpmn_path, params, log_path)
        else:
            from prosimos.simulation_engine import run_simulation
            from aureasim.executor import _ensure_event_distributions
            from aureasim.sanitizer import auto_sanitize_bpmn

            effective = copy.deepcopy(params)
            _ensure_event_distributions(effective, str(bpmn_path))
            config_path = run_dir / "effective_parameters.json"
            config_path.write_text(json.dumps(effective, indent=2) + "\n", encoding="utf-8")
            sanitized = Path(auto_sanitize_bpmn(str(bpmn_path), str(run_dir), params=effective))
            run_simulation(
                str(sanitized), str(config_path), 1,
                log_out_path=str(log_path),
                starting_at="2026-01-05T09:00:00+00:00",
            )
        if not log_path.exists() or log_path.stat().st_size == 0:
            raise ValueError("Prosimos completed without producing an event log")
        return {"status": "passed", "cases": 1, "log_path": str(log_path), "log_sha256": sha256(log_path)}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__, "error_message": str(exc)}


def validate_and_smoke(
    *, project_path: Path, runner: Callable[[Path, dict[str, Any], Path], None] | None = None
) -> dict[str, Any]:
    base_path = project_path / "AutoGenerated_Base_params.json"
    bpmn_path = next((path for path in project_path.glob("*.bpmn") if not path.name.startswith("SANITIZED")), None)
    if not base_path.exists() or bpmn_path is None:
        raise ValueError("Baseline parameters and a source BPMN model are required")
    params = json.loads(base_path.read_text(encoding="utf-8"))
    configuration_hash = sha256(base_path)
    errors, warnings = validate_baseline_structure(bpmn_path, params)
    smoke = {"status": "not_run"}
    if not errors:
        smoke = run_smoke_validation(
            bpmn_path=bpmn_path,
            params=params,
            run_dir=project_path / ".validation" / configuration_hash[:16],
            runner=runner,
        )
        if smoke["status"] != "passed":
            errors.append(f"Prosimos smoke simulation failed: {smoke.get('error_message', 'unknown error')}")
    report = {
        "format_version": 1,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "configuration_sha256": configuration_hash,
        "bpmn_sha256": sha256(bpmn_path),
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "smoke_simulation": smoke,
    }
    report_path = project_path / "baseline_validation.json"
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    return report


def validation_state(project_path: Path) -> dict[str, Any]:
    base_path = project_path / "AutoGenerated_Base_params.json"
    report_path = project_path / "baseline_validation.json"
    if not base_path.exists() or not report_path.exists():
        return {"status": "not_validated", "current": False, "report": None}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unreadable", "current": False, "report": None}
    current = report.get("configuration_sha256") == sha256(base_path)
    return {
        "status": report.get("status") if current else "stale",
        "current": current,
        "report": report,
    }
