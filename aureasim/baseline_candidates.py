"""Create reviewable parameter candidates from an executable AureaSim baseline."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from aureasim.parameter_candidates import (
    ApplicationStatus,
    CandidateMethod,
    CandidateSet,
    ConfidenceGrade,
    DistributionSpec,
    EvidenceReference,
    ParameterCandidate,
    ReliabilityProfileReference,
    deterministic_candidate_id,
    new_candidate_set_id,
    utc_now,
)


# Frozen profiles produced by the SoftwareX evaluation.  Human execution
# durations are profiled only against independently classified human tasks;
# PROCESSSTEP model type alone is not evidence of human work. Percentages are
# stored as fractions because candidate errors use 1.0 == 100%.
_RELIABILITY_PROFILES: dict[tuple[CandidateMethod, str], dict[str, Any]] = {
    (CandidateMethod.SEMANTIC_HEURISTIC, "execution_duration_seconds"): {
        "profile_id": "softwarex_semantic_duration_human_tasks_v2",
        "primary_error_metric": "absolute_relative_error",
        "reference_context": "chronological_operational_holdout_human_tasks",
        "independent_units": 32,
        "expected_error_p10": 0.5313870771677361,
        "expected_error_median": 0.9431890985720269,
        "expected_error_p90": 11.181668427137163,
        "reliability_grade": ConfidenceGrade.LOW,
        "generalizable_expected_range": True,
    },
    (CandidateMethod.GENERIC_HEURISTIC, "execution_duration_seconds"): {
        "profile_id": "softwarex_generic_duration_human_tasks_v2",
        "primary_error_metric": "absolute_relative_error",
        "reference_context": "chronological_operational_holdout_human_tasks",
        "independent_units": 32,
        "expected_error_p10": 0.7375456929136104,
        "expected_error_median": 0.9770053085555059,
        "expected_error_p90": 25.426324818634477,
        "reliability_grade": ConfidenceGrade.LOW,
        "generalizable_expected_range": True,
    },
    (CandidateMethod.EVIDENCE_GROUNDED, "execution_duration_seconds"): {
        "profile_id": "softwarex_grounded_duration_human_tasks_v2",
        "primary_error_metric": "absolute_relative_error",
        "reference_context": "chronological_operational_holdout_human_tasks",
        "independent_units": 32,
        "expected_error_p10": 0.609872612841276,
        "expected_error_median": 0.9827338421572682,
        "expected_error_p90": 7.880313986957179,
        "reliability_grade": ConfidenceGrade.LOW,
        "generalizable_expected_range": True,
    },
    (CandidateMethod.EVIDENCE_GROUNDED, "resource_cost_per_hour"): {
        "profile_id": "softwarex_grounded_cost_reference_v1",
        "primary_error_metric": "absolute_relative_error",
        "reference_context": "expert_or_documented_benchmark",
        "independent_units": 20,
        "expected_error_p10": 0.002,
        "expected_error_median": 0.013,
        "expected_error_p90": 0.059,
        "reliability_grade": ConfidenceGrade.MEDIUM,
        "generalizable_expected_range": True,
    },
}


def _numeric_params(value: Any) -> list[float]:
    result: list[float] = []
    for item in value or []:
        raw = item.get("value") if isinstance(item, dict) else item
        result.append(float(raw))
    return result


def _process_identity(project_path: Path, baseline: dict[str, Any]) -> tuple[str, str]:
    metadata = baseline.get("metadata", {})
    process_id = str(metadata.get("process_id") or "")
    process_version = str(metadata.get("process_version") or "unknown")
    if not process_id:
        bpmn_files = [path for path in project_path.glob("*.bpmn") if not path.name.startswith("SANITIZED")]
        if bpmn_files:
            try:
                root = ET.parse(bpmn_files[0]).getroot()
                process = next((node for node in root.iter() if node.tag.split("}")[-1] == "process"), None)
                process_id = str(process.get("id") if process is not None else "")
            except (OSError, ET.ParseError):
                pass
    return process_id or project_path.name, process_version


def _method_for(status: str, family: str, entity_name: str, entity_id: str) -> CandidateMethod:
    if status.startswith("grounded"):
        return CandidateMethod.EVIDENCE_GROUNDED
    if family == "execution_duration_seconds" and entity_name and entity_name != entity_id:
        return CandidateMethod.SEMANTIC_HEURISTIC
    return CandidateMethod.GENERIC_HEURISTIC


def _profile(method: CandidateMethod, family: str) -> ReliabilityProfileReference | None:
    payload = _RELIABILITY_PROFILES.get((method, family))
    return ReliabilityProfileReference(**payload) if payload else None


def _candidate(
    *,
    process_alias: str,
    process_id: str,
    process_version: str,
    base_hash: str,
    family: str,
    entity_id: str,
    entity_name: str,
    unit: str,
    method: CandidateMethod,
    source_pointer: str,
    rationale: str,
    distribution: DistributionSpec | None = None,
    scalar_value: float | None = None,
) -> ParameterCandidate:
    reliability = _profile(method, family)
    expected_error = None
    grade = ConfidenceGrade.UNKNOWN
    if reliability:
        expected_error = {
            "p10": reliability.expected_error_p10,
            "median": reliability.expected_error_median,
            "p90": reliability.expected_error_p90,
        }
        grade = reliability.reliability_grade
        confidence_basis = (
            f"SoftwareX empirical method profile over {reliability.independent_units} independent "
            f"units in the {reliability.reference_context} context."
        )
    else:
        confidence_basis = "No matching empirical reliability profile is available for this method and parameter family."
    fingerprint = distribution.model_dump(mode="json") if distribution else scalar_value
    identifier = deterministic_candidate_id(
        process_alias, family, entity_id, method.value, fingerprint, base_hash
    )
    return ParameterCandidate(
        candidate_id=identifier,
        process_alias=process_alias,
        process_id=process_id,
        process_version=process_version,
        parameter_family=family,
        entity_id=entity_id,
        entity_name=entity_name,
        method=method,
        unit=unit,
        scalar_value=scalar_value,
        distribution=distribution,
        evidence=[EvidenceReference(
            evidence_type="generated_baseline_provenance",
            source=source_pointer,
            source_sha256=base_hash,
            notes=rationale,
        )],
        confidence_grade=grade,
        confidence_basis=confidence_basis,
        expected_error=expected_error,
        reliability_profile=reliability,
        application_status=ApplicationStatus.APPLIED,
    )


def candidate_set_from_baseline(project_path: Path) -> CandidateSet:
    """Represent every supported numeric baseline parameter as a reviewed candidate."""
    base_path = project_path / "AutoGenerated_Base_params.json"
    baseline_bytes = base_path.read_bytes()
    baseline = json.loads(baseline_bytes)
    base_hash = hashlib.sha256(baseline_bytes).hexdigest()
    process_alias = project_path.name
    process_id, process_version = _process_identity(project_path, baseline)
    metadata = baseline.get("metadata", {})
    task_names = metadata.get("task_name_map", {})
    candidates: list[ParameterCandidate] = []

    for entry in baseline.get("task_resource_distribution", []):
        task_id = str(entry.get("task_id") or "")
        resources = entry.get("resources") or []
        if not task_id or not resources:
            continue
        resource = resources[0]
        params = _numeric_params(resource.get("distribution_params"))
        if not params:
            continue
        name_info = task_names.get(task_id, {})
        task_name = str(name_info.get("clean_task_name") or name_info.get("task_name") or task_id)
        status = str(resource.get("evidence_status") or metadata.get("grounding_mode") or "heuristic")
        method = _method_for(status, "execution_duration_seconds", task_name, task_id)
        candidates.append(_candidate(
            process_alias=process_alias, process_id=process_id, process_version=process_version,
            base_hash=base_hash, family="execution_duration_seconds", entity_id=task_id,
            entity_name=task_name, unit="seconds", method=method,
            source_pointer=f"AutoGenerated_Base_params.json#/task_resource_distribution/{task_id}",
            rationale=str(resource.get("evidence_rationale") or metadata.get("methodology") or "Generated baseline value."),
            distribution=DistributionSpec(
                distribution_name=str(resource.get("distribution_name") or "fix"),
                distribution_params=params,
                fit_method=f"generated_{method.value}",
            ),
        ))

    arrival = baseline.get("arrival_time_distribution")
    if isinstance(arrival, dict):
        params = _numeric_params(arrival.get("distribution_params"))
        if params:
            status = str(arrival.get("evidence_status") or metadata.get("grounding_mode") or "heuristic")
            method = _method_for(status, "interarrival_time_seconds", "Process arrivals", "__process__")
            candidates.append(_candidate(
                process_alias=process_alias, process_id=process_id, process_version=process_version,
                base_hash=base_hash, family="interarrival_time_seconds", entity_id="__process__",
                entity_name="Process arrivals", unit="seconds", method=method,
                source_pointer="AutoGenerated_Base_params.json#/arrival_time_distribution",
                rationale=str(arrival.get("evidence_rationale") or metadata.get("methodology") or "Generated baseline value."),
                distribution=DistributionSpec(
                    distribution_name=str(arrival.get("distribution_name") or "fix"),
                    distribution_params=params,
                    fit_method=f"generated_{method.value}",
                ),
            ))

    for profile in baseline.get("resource_profiles", []):
        profile_name = str(profile.get("name") or profile.get("id") or "Resource")
        for resource in profile.get("resource_list", []):
            resource_id = str(resource.get("id") or "")
            if not resource_id:
                continue
            status = str(resource.get("evidence_status") or metadata.get("grounding_mode") or "heuristic")
            cost_method = _method_for(status, "resource_cost_per_hour", profile_name, resource_id)
            if resource.get("cost_per_hour") is not None:
                candidates.append(_candidate(
                    process_alias=process_alias, process_id=process_id, process_version=process_version,
                    base_hash=base_hash, family="resource_cost_per_hour", entity_id=resource_id,
                    entity_name=f"{profile_name} hourly cost", unit="currency/hour", method=cost_method,
                    source_pointer=f"AutoGenerated_Base_params.json#/resource_profiles/{resource_id}/cost_per_hour",
                    rationale=str(resource.get("evidence_rationale") or metadata.get("methodology") or "Generated baseline value."),
                    scalar_value=float(resource["cost_per_hour"]),
                ))
            if resource.get("amount") is not None:
                candidates.append(_candidate(
                    process_alias=process_alias, process_id=process_id, process_version=process_version,
                    base_hash=base_hash, family="resource_capacity", entity_id=resource_id,
                    entity_name=f"{profile_name} capacity", unit="resources",
                    method=CandidateMethod.GENERIC_HEURISTIC,
                    source_pointer=f"AutoGenerated_Base_params.json#/resource_profiles/{resource_id}/amount",
                    rationale="Capacity retained from the generated executable baseline.",
                    scalar_value=float(resource["amount"]),
                ))

    for gateway in baseline.get("gateway_branching_probabilities", []):
        gateway_id = str(gateway.get("gateway_id") or "Gateway")
        for path in gateway.get("probabilities", []):
            path_id = str(path.get("path_id") or "")
            if path_id and path.get("value") is not None:
                candidates.append(_candidate(
                    process_alias=process_alias, process_id=process_id, process_version=process_version,
                    base_hash=base_hash, family="gateway_probability", entity_id=path_id,
                    entity_name=f"{gateway_id} / {path_id}", unit="probability",
                    method=CandidateMethod.GENERIC_HEURISTIC,
                    source_pointer=f"AutoGenerated_Base_params.json#/gateway_branching_probabilities/{gateway_id}/{path_id}",
                    rationale="Gateway probability retained from the generated executable baseline.",
                    scalar_value=float(path["value"]),
                ))

    identifiers = [item.candidate_id for item in candidates]
    return CandidateSet(
        candidate_set_id=new_candidate_set_id(process_alias, identifiers),
        process_alias=process_alias,
        process_id=process_id,
        process_version=process_version,
        created_at=utc_now(),
        assembly_policy="automatic_baseline_candidate_initialization_v1",
        base_configuration_sha256=base_hash,
        candidates=candidates,
    )
