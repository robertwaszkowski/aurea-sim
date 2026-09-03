"""Product-facing historical-task repository and candidate construction."""

from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from aureasim.historical_analogues import (
    HistoricalTaskProfile,
    find_similar_tasks,
    find_temporal_semantic_analogues,
    find_temporal_semantic_analogues_v2,
    select_consistent_donor_cluster,
)
from aureasim.parameter_candidates import (
    ApplicationStatus,
    CandidateMethod,
    ConfidenceGrade,
    DistributionSpec,
    EvidenceReference,
    ParameterCandidate,
    deterministic_candidate_id,
)


BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
Z90 = 1.2815515655446004


def _profile(data: dict[str, Any]) -> HistoricalTaskProfile:
    return HistoricalTaskProfile(
        **{
            **data,
            "predecessor_labels": tuple(data.get("predecessor_labels", ())),
            "successor_labels": tuple(data.get("successor_labels", ())),
            "domain_fields": frozenset(data.get("domain_fields", ())),
            "form_access_signature": frozenset(data.get("form_access_signature", ())),
        }
    )


def load_repository(path: Path) -> tuple[dict[str, Any], list[tuple[HistoricalTaskProfile, list[float]]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format_version") != 1:
        raise ValueError("Unsupported historical-task repository format")
    records = [
        (_profile(item["profile"]), [float(value) for value in item["calibration_samples_seconds"]])
        for item in payload.get("profiles", [])
    ]
    return payload, records


def enabled_source_ids(payload: dict[str, Any]) -> set[str] | None:
    """Return selected source IDs; legacy repositories keep all sources active."""
    catalog = payload.get("source_catalog")
    if catalog is None:
        return None
    return {str(item["source_id"]) for item in catalog if item.get("enabled")}


def _parse_project_task(project_path: Path, task_id: str, process_id: str, process_version: str, alias: str):
    bpmn = (
        project_path
        if project_path.is_file() and project_path.suffix.casefold() == ".bpmn"
        else next(
            (path for path in project_path.glob("*.bpmn") if not path.name.startswith("SANITIZED")),
            None,
        )
    )
    if bpmn is None:
        raise ValueError("Project has no source BPMN model")
    root = ET.parse(bpmn).getroot()
    process = root.find(f"{{{BPMN_NS}}}process")
    if process is None:
        raise ValueError("BPMN model has no process")
    names = {
        item.get("id", ""): item.get("name", "") or item.tag.rsplit("}", 1)[-1]
        for item in process.iter()
        if item.get("id") and item.tag.rsplit("}", 1)[-1] != "sequenceFlow"
    }
    if task_id not in names:
        raise ValueError(f"Task {task_id} is not present in the BPMN model")
    predecessors, successors = [], []
    for flow in process.findall(f"{{{BPMN_NS}}}sequenceFlow"):
        if flow.get("targetRef") == task_id:
            predecessors.append(names.get(flow.get("sourceRef", ""), flow.get("sourceRef", "")))
        if flow.get("sourceRef") == task_id:
            successors.append(names.get(flow.get("targetRef", ""), flow.get("targetRef", "")))
    return HistoricalTaskProfile(
        process_alias=alias,
        process_id=process_id or process.get("id", ""),
        process_version=process_version,
        task_id=task_id,
        task_name=names[task_id],
        predecessor_labels=tuple(sorted(predecessors)),
        successor_labels=tuple(sorted(successors)),
        process_name=process.get("name", "") or process.get("id", ""),
    )


def search_repository(
    *,
    repository_path: Path,
    project_path: Path,
    task_id: str,
    process_alias: str,
    process_id: str,
    process_version: str,
) -> dict[str, Any]:
    settings, records = load_repository(repository_path)
    enabled = enabled_source_ids(settings)
    records = [item for item in records if enabled is None or item[0].process_alias in enabled]
    profiles = [profile for profile, _ in records]
    target = next(
        (
            profile for profile in profiles
            if profile.process_id == process_id and profile.task_id == task_id
        ),
        None,
    ) or _parse_project_task(project_path, task_id, process_id, process_version, process_alias)
    retrieval_strategy = settings.get("retrieval_strategy", "cross_process_semantic")
    retrieval = {
        "cross_process_semantic": find_similar_tasks,
        "historical_semantic_analogue": find_temporal_semantic_analogues,
        # Compatibility name used before the method was renamed HSAR.
        "temporal_semantic_analogue": find_temporal_semantic_analogues,
        "historical_semantic_analogue_v2": find_temporal_semantic_analogues_v2,
    }.get(retrieval_strategy)
    if retrieval is None:
        raise ValueError(f"Unsupported historical retrieval strategy: {retrieval_strategy!r}")
    retrieval_kwargs = {
        "weights": settings["weights"],
        "minimum_score": float(settings["minimum_score"]),
        "maximum_results": int(settings["maximum_results"]),
        "minimum_observations": int(settings["minimum_donor_observations"]),
    }
    if retrieval_strategy == "historical_semantic_analogue_v2":
        retrieval_kwargs["minimum_form_access_similarity"] = float(
            settings.get("minimum_form_access_similarity", 0.35)
        )
    matches = retrieval(target, profiles, **retrieval_kwargs)
    excluded_matches = []
    donor_medians = {}
    if retrieval_strategy == "historical_semantic_analogue_v2":
        samples_by_profile = {profile: values for profile, values in records}
        matches, excluded_matches, donor_medians = select_consistent_donor_cluster(
            matches,
            samples_by_profile,
            maximum_median_ratio=float(settings.get("maximum_median_ratio_within_cluster", 2.0)),
            minimum_donors=int(settings.get("minimum_cluster_donors", 2)),
        )
    families = {match.profile.process_alias for match in matches}
    combined = sum(match.profile.observation_count for match in matches)
    if retrieval_strategy == "historical_semantic_analogue_v2":
        has_prior_version = any(match.donor_scope == "prior_version" for match in matches)
        enough_prior = has_prior_version and combined >= int(settings.get("minimum_prior_version_observations", 100))
        enough_cross_process = (
            len(matches) >= int(settings.get("minimum_analogue_tasks", 2))
            and len(families) >= int(settings.get("minimum_process_families", 2))
            and combined >= int(settings["minimum_combined_executions"])
        )
        sufficient = enough_prior or enough_cross_process
    else:
        sufficient = (
            len(matches) >= int(settings["minimum_analogue_tasks"])
            and len(families) >= int(settings["minimum_process_families"])
            and combined >= int(settings["minimum_combined_executions"])
        )
    return {
        "target": target,
        "matches": matches,
        "excluded_matches": excluded_matches,
        "donor_medians": donor_medians,
        "sufficient": sufficient,
        "process_families": len(families),
        "combined_executions": combined,
        "requirements": {
            key: settings[key] for key in (
                "minimum_score", "minimum_analogue_tasks", "minimum_process_families",
                "minimum_combined_executions", "minimum_donor_observations",
            )
        },
        "retrieval_strategy": retrieval_strategy,
        "records": records,
    }


def _weighted_percentile(values: list[tuple[float, float]], probability: float) -> float:
    ordered = sorted(values)
    threshold = probability * sum(weight for _, weight in ordered)
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def candidate_from_search(search: dict[str, Any], repository_path: Path) -> ParameterCandidate:
    if not search["sufficient"]:
        raise ValueError("Analogue evidence does not satisfy the frozen evidence thresholds")
    samples = {
        (profile.process_alias, profile.process_id, profile.process_version, profile.task_id): values
        for profile, values in search["records"]
    }
    weighted: list[tuple[float, float]] = []
    for match in search["matches"]:
        weighted.extend(
            (value, match.score)
            for value in samples[(
                match.profile.process_alias,
                match.profile.process_id,
                match.profile.process_version,
                match.profile.task_id,
            )]
        )
    p10 = max(_weighted_percentile(weighted, 0.10), 1e-9)
    median = max(_weighted_percentile(weighted, 0.50), 1e-9)
    p90 = max(_weighted_percentile(weighted, 0.90), p10)
    sigma = min(max((math.log(p90) - math.log(p10)) / (2 * Z90), 0.05), 4.0)
    target: HistoricalTaskProfile = search["target"]
    donor_ids = [
        f"{item.profile.process_alias}:{item.profile.process_version}:{item.profile.task_id}"
        for item in search["matches"]
    ]
    excluded_donors = [
        f"{item.profile.process_alias}:{item.profile.process_version}:{item.profile.task_id}"
        for item in search.get("excluded_matches", [])
    ]
    digest = hashlib.sha256(repository_path.read_bytes()).hexdigest()
    return ParameterCandidate(
        candidate_id=deterministic_candidate_id(
            target.process_alias, target.task_id, "historical_analogue", digest, *donor_ids
        ),
        process_alias=target.process_alias,
        process_id=target.process_id,
        process_version=target.process_version,
        parameter_family="execution_duration_seconds",
        entity_id=target.task_id,
        entity_name=target.task_name,
        method=CandidateMethod.HISTORICAL_ANALOGUE,
        unit="seconds",
        distribution=DistributionSpec(
            distribution_name="lognorm",
            distribution_params=[sigma, 0.0, median, 0.0, max(value for value, _ in weighted)],
            fit_method="similarity_weighted_calibration_donor_mixture",
            empirical_quantiles={"p10": p10, "p50": median, "p90": p90},
        ),
        evidence=[EvidenceReference(
            evidence_type="historical_task_repository",
            source=str(repository_path).replace("\\", "/"),
            source_sha256=digest,
            split="calibration",
            sample_size=search["combined_executions"],
            notes=(
                "HSAR: all donor evidence predates the target evidence window. "
                if search["retrieval_strategy"] in {
                    "historical_semantic_analogue", "temporal_semantic_analogue", "historical_semantic_analogue_v2"
                }
                else "Target process excluded. "
            ) + "Selected donors: " + ", ".join(donor_ids)
            + (". Excluded inconsistent donors: " + ", ".join(excluded_donors) if excluded_donors else ""),
        )],
        confidence_grade=ConfidenceGrade.MEDIUM,
        confidence_basis=(
            f"{len(search['matches'])} selected analogue tasks from {search['process_families']} "
            f"process families and {search['combined_executions']} calibration observations."
        ),
        application_status=ApplicationStatus.ALTERNATIVE,
    )


def public_search_result(search: dict[str, Any]) -> dict[str, Any]:
    target: HistoricalTaskProfile = search["target"]
    return {
        "target": {
            "process_alias": target.process_alias,
            "task_id": target.task_id,
            "task_name": target.task_name,
        },
        "sufficient": search["sufficient"],
        "process_families": search["process_families"],
        "combined_executions": search["combined_executions"],
        "requirements": search["requirements"],
        "retrieval_strategy": search["retrieval_strategy"],
        "matches": [{
            "process_alias": item.profile.process_alias,
            "task_id": item.profile.task_id,
            "task_name": item.profile.task_name,
            "process_name": item.profile.process_name,
            "role_label": item.profile.role_label,
            "observation_count": item.profile.observation_count,
            "semantic": item.semantic,
            "bpmn_context": item.bpmn_context,
            "role": item.role,
            "domain": item.domain,
            "score": item.score,
            "donor_scope": item.donor_scope,
            "form_access": item.form_access,
            "donor_median_seconds": search.get("donor_medians", {}).get(item.profile),
        } for item in search["matches"]],
        "excluded_matches": [{
            "process_alias": item.profile.process_alias,
            "task_id": item.profile.task_id,
            "task_name": item.profile.task_name,
            "donor_median_seconds": search.get("donor_medians", {}).get(item.profile),
        } for item in search.get("excluded_matches", [])],
    }
