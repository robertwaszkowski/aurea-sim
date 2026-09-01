"""Apply a reviewed parameter candidate to an executable Prosimos baseline."""

from __future__ import annotations

import copy
from typing import Any, Mapping

from aureasim.parameter_candidates import (
    ApplicationStatus,
    CandidateSet,
    ParameterCandidate,
    ReviewStatus,
)


def _prosimos_distribution(candidate: ParameterCandidate):
    spec = candidate.distribution
    if spec is None:
        raise ValueError("This candidate does not contain an executable distribution")

    incompatible = next(
        (
            item
            for item in candidate.export_compatibility
            if "prosimos" in item.target.lower() and not item.supported
        ),
        None,
    )
    used_fallback = False
    if incompatible is not None:
        if incompatible.fallback_distribution is None:
            raise ValueError(incompatible.reason or "Candidate is not executable by Prosimos")
        spec = incompatible.fallback_distribution
        used_fallback = True

    if spec.discrete_mass_points:
        raise ValueError(
            "Discrete empirical candidates require an explicitly recorded Prosimos fallback"
        )
    if not spec.distribution_params:
        raise ValueError("Executable distribution has no numeric parameters")
    return spec, used_fallback


def apply_candidate_to_baseline(
    baseline: Mapping[str, Any], candidate: ParameterCandidate
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return edited baseline, previous value, and the representation actually used."""
    if candidate.validity != "valid":
        raise ValueError("Invalid candidates cannot be used in the baseline")
    if candidate.review_status == ReviewStatus.REJECTED:
        raise ValueError("Rejected candidates cannot be used in the baseline")
    if candidate.parameter_family not in {
        "execution_duration_seconds",
        "interarrival_time_seconds",
        "resource_cost_per_hour",
        "resource_capacity",
        "gateway_probability",
    }:
        raise ValueError(
            f"{candidate.parameter_family} is diagnostic evidence, not an executable baseline parameter"
        )

    updated = copy.deepcopy(dict(baseline))

    if candidate.parameter_family == "gateway_probability":
        if candidate.scalar_value is None or not 0 <= candidate.scalar_value <= 1:
            raise ValueError("Gateway probability must be between zero and one")
        target = next(
            (
                path
                for gateway in updated.get("gateway_branching_probabilities", [])
                for path in gateway.get("probabilities", [])
                if path.get("path_id") == candidate.entity_id
            ),
            None,
        )
        if target is None:
            raise ValueError(f"Baseline has no gateway path matching {candidate.entity_id}")
        previous = copy.deepcopy(target)
        target.update({
            "value": float(candidate.scalar_value),
            "candidate_id": candidate.candidate_id,
            "candidate_method": candidate.method.value,
        })
        return updated, previous, {"scalar_value": float(candidate.scalar_value), "field": "value"}

    if candidate.parameter_family in {"resource_cost_per_hour", "resource_capacity"}:
        if candidate.scalar_value is None:
            raise ValueError("This candidate does not contain a scalar value")
        resource = next(
            (
                item
                for profile in updated.get("resource_profiles", [])
                for item in profile.get("resource_list", [])
                if item.get("id") == candidate.entity_id
            ),
            None,
        )
        if resource is None:
            raise ValueError(f"Baseline has no resource matching {candidate.entity_id}")
        previous = copy.deepcopy(resource)
        field = "cost_per_hour" if candidate.parameter_family == "resource_cost_per_hour" else "amount"
        value: float | int = float(candidate.scalar_value)
        if field == "amount":
            if value < 1 or not value.is_integer():
                raise ValueError("Baseline resource capacity must be a positive integer")
            value = int(value)
        resource.update({
            field: value,
            f"{field}_candidate_id": candidate.candidate_id,
            f"{field}_candidate_method": candidate.method.value,
        })
        return updated, previous, {"scalar_value": value, "field": field}

    spec, used_fallback = _prosimos_distribution(candidate)
    params = [{"value": float(value)} for value in spec.distribution_params]
    representation = {
        "distribution_name": spec.distribution_name,
        "distribution_params": params,
        "fit_method": spec.fit_method,
        "used_fallback": used_fallback,
    }

    if candidate.parameter_family == "interarrival_time_seconds":
        if candidate.entity_id != "__process__":
            raise ValueError("Interarrival candidates must target the process")
        target = updated.get("arrival_time_distribution")
        if not isinstance(target, dict):
            raise ValueError("Baseline has no arrival-time distribution")
        previous = copy.deepcopy(target)
        target.update({
            "distribution_name": spec.distribution_name,
            "distribution_params": params,
            "candidate_id": candidate.candidate_id,
            "candidate_method": candidate.method.value,
            "evidence_status": candidate.method.value,
            "evidence_rationale": candidate.confidence_basis,
        })
        target.pop("frequency", None)
        target.pop("histogram_data", None)
        return updated, previous, representation

    assignment = next(
        (
            item
            for item in updated.get("task_resource_distribution", [])
            if item.get("task_id") == candidate.entity_id
        ),
        None,
    )
    if assignment is None:
        raise ValueError(f"Baseline has no task matching {candidate.entity_id}")
    resources = assignment.get("resources", [])
    if not resources:
        raise ValueError(f"Task {candidate.entity_id} has no executable resource assignment")
    previous = copy.deepcopy(assignment)
    for resource in resources:
        resource.update({
            "distribution_name": spec.distribution_name,
            "distribution_params": copy.deepcopy(params),
            "candidate_id": candidate.candidate_id,
            "candidate_method": candidate.method.value,
            "evidence_status": candidate.method.value,
            "evidence_rationale": candidate.confidence_basis,
        })
    return updated, previous, representation


def active_candidate_ids(baseline: Mapping[str, Any]) -> list[str]:
    identifiers: set[str] = set()
    arrival = baseline.get("arrival_time_distribution", {})
    if isinstance(arrival, dict) and arrival.get("candidate_id"):
        identifiers.add(str(arrival["candidate_id"]))
    for assignment in baseline.get("task_resource_distribution", []):
        for resource in assignment.get("resources", []):
            if resource.get("candidate_id"):
                identifiers.add(str(resource["candidate_id"]))
    for profile in baseline.get("resource_profiles", []):
        for resource in profile.get("resource_list", []):
            for field in ("cost_per_hour_candidate_id", "amount_candidate_id"):
                if resource.get(field):
                    identifiers.add(str(resource[field]))
    for gateway in baseline.get("gateway_branching_probabilities", []):
        for path in gateway.get("probabilities", []):
            if path.get("candidate_id"):
                identifiers.add(str(path["candidate_id"]))
    return sorted(identifiers)


def selected_candidate_ids(
    baseline: Mapping[str, Any], candidate_set: CandidateSet
) -> list[str]:
    """Resolve explicit selections plus untouched candidates representing the baseline."""
    explicit = active_candidate_ids(baseline)
    by_id = {item.candidate_id: item for item in candidate_set.candidates}
    explicit_groups = {
        (by_id[identifier].parameter_family, by_id[identifier].entity_id)
        for identifier in explicit
        if identifier in by_id
    }
    selected = set(explicit)
    for candidate in candidate_set.candidates:
        group = (candidate.parameter_family, candidate.entity_id)
        if (
            candidate.application_status == ApplicationStatus.APPLIED
            and group not in explicit_groups
        ):
            selected.add(candidate.candidate_id)
    return sorted(selected)
