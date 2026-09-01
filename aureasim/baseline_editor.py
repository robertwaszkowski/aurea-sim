"""Validated manual edits for an executable Prosimos baseline configuration."""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping


_ARRIVAL_UNIT_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,
}


def _finite_number(value: Any, label: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not math.isfinite(number) or number < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return number


def _find(items: list[dict], key: str, value: str, label: str) -> dict:
    for item in items:
        if item.get(key) == value:
            return item
    raise ValueError(f"Unknown {label}: {value}")


def apply_baseline_update(
    baseline: Mapping[str, Any],
    parameter_type: str,
    entity_id: str,
    values: Mapping[str, Any],
) -> tuple[dict, dict]:
    """Return a validated edited copy and a compact record of the prior value."""
    updated = copy.deepcopy(dict(baseline))
    evidence_type = str(values.get("evidence_type") or "expert_judgment")
    if evidence_type not in {"local_measurement", "expert_judgment", "policy_requirement", "other"}:
        raise ValueError("Unsupported evidence type")

    if parameter_type == "arrival":
        distribution = updated.get("arrival_time_distribution")
        if not isinstance(distribution, dict):
            raise ValueError("Baseline has no arrival-time distribution")
        events = _finite_number(values.get("events"), "Arrival events", minimum=0.000001)
        per_count = _finite_number(values.get("per_count"), "Arrival period count", minimum=0.000001)
        per_unit = str(values.get("per_unit") or "")
        if per_unit not in _ARRIVAL_UNIT_SECONDS:
            raise ValueError(f"Unsupported arrival time unit: {per_unit}")
        previous = copy.deepcopy(distribution)
        mean_seconds = _ARRIVAL_UNIT_SECONDS[per_unit] * per_count / events
        distribution["distribution_name"] = "expon"
        distribution["distribution_params"] = [
            {"value": 0},
            {"value": round(mean_seconds, 6)},
            {"value": 0},
            {"value": 9999999},
        ]
        distribution["frequency"] = {
            "events": events,
            "per_count": per_count,
            "per_unit": per_unit,
            "rationale": str(values.get("rationale") or "Manually revised baseline arrival frequency."),
        }
        return updated, previous

    if parameter_type == "resource":
        profile = _find(
            updated.get("resource_profiles", []), "id", entity_id, "resource profile"
        )
        headcount_value = values.get("headcount")
        if isinstance(headcount_value, bool):
            raise ValueError("Resource headcount must be a positive integer")
        try:
            headcount = int(headcount_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Resource headcount must be a positive integer") from exc
        if headcount < 1 or float(headcount_value) != headcount:
            raise ValueError("Resource headcount must be a positive integer")
        cost = _finite_number(values.get("cost_per_hour"), "Hourly cost")
        calendar = str(values.get("calendar") or "")
        known_calendars = {
            item.get("id") for item in updated.get("resource_calendars", [])
        }
        if calendar not in known_calendars:
            raise ValueError(f"Unknown resource calendar: {calendar}")

        previous = copy.deepcopy(profile)
        old_resources = profile.get("resource_list", [])
        if not old_resources:
            raise ValueError(f"Resource profile '{entity_id}' has no resource template")
        old_ids = {item.get("id") for item in old_resources if item.get("id")}
        template = copy.deepcopy(old_resources[0])
        new_resources = []
        for index in range(1, headcount + 1):
            resource = copy.deepcopy(template)
            resource["id"] = f"{entity_id}_{index}"
            resource["name"] = f"{profile.get('name') or entity_id} {index}"
            resource["amount"] = 1
            resource["cost_per_hour"] = cost
            resource["calendar"] = calendar
            resource["evidence_status"] = evidence_type
            resource["evidence_rationale"] = "Manually revised baseline resource configuration."
            new_resources.append(resource)
        profile["resource_list"] = new_resources

        new_ids = [item["id"] for item in new_resources]
        for assignment in updated.get("task_resource_distribution", []):
            resources = assignment.get("resources", [])
            matching = [item for item in resources if item.get("resource_id") in old_ids]
            if not matching:
                continue
            task_template = copy.deepcopy(matching[0])
            assignment["resources"] = [
                item for item in resources if item.get("resource_id") not in old_ids
            ]
            for resource_id in new_ids:
                entry = copy.deepcopy(task_template)
                entry["resource_id"] = resource_id
                assignment["resources"].append(entry)
        return updated, previous

    if parameter_type == "task_duration":
        assignment = _find(
            updated.get("task_resource_distribution", []),
            "task_id",
            entity_id,
            "task duration",
        )
        mean_minutes = _finite_number(values.get("mean_minutes"), "Mean duration", minimum=0.000001)
        stddev_minutes = _finite_number(values.get("stddev_minutes", 0), "Duration standard deviation")
        previous = copy.deepcopy(assignment)
        for resource in assignment.get("resources", []):
            params = resource.setdefault("distribution_params", [])
            while len(params) < 4:
                params.append({"value": 0})
            params[0]["value"] = mean_minutes * 60
            params[1]["value"] = stddev_minutes * 60
            resource["evidence_status"] = evidence_type
            resource["evidence_rationale"] = "Manually revised baseline task duration."
        return updated, previous

    if parameter_type == "gateway":
        gateway = _find(
            updated.get("gateway_branching_probabilities", []),
            "gateway_id",
            entity_id,
            "gateway",
        )
        supplied = values.get("probabilities")
        if not isinstance(supplied, dict):
            raise ValueError("Gateway probabilities must be a path-to-probability object")
        expected_paths = {item.get("path_id") for item in gateway.get("probabilities", [])}
        if set(supplied) != expected_paths:
            raise ValueError("Gateway probability paths do not match the baseline gateway")
        probabilities = {
            path_id: _finite_number(value, f"Probability for {path_id}")
            for path_id, value in supplied.items()
        }
        if any(value > 1 for value in probabilities.values()):
            raise ValueError("Gateway probabilities cannot exceed 1")
        if abs(sum(probabilities.values()) - 1) > 1e-6:
            raise ValueError("Gateway probabilities must sum to 1")
        previous = copy.deepcopy(gateway)
        for item in gateway.get("probabilities", []):
            item["value"] = probabilities[item["path_id"]]
        return updated, previous

    raise ValueError(f"Unsupported baseline parameter type: {parameter_type}")
