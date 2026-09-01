"""Attach independent operational or expert-survey references to candidates.

The module deliberately treats references as evaluation evidence, never as an
instruction to overwrite an executable baseline.  A candidate can therefore be
compared with a completed expert survey without losing its generated provenance
or the possibility of an explicit expert edit.
"""

from __future__ import annotations

import csv
import re
from io import StringIO
from typing import Iterable

from aureasim.parameter_candidates import CandidateSet, ParameterCandidate


REQUIRED_COLUMNS = {
    "process_alias", "parameter_family", "entity_key", "reference_value",
    "reference_type", "source",
}
FAMILY_ALIASES = {
    "task_duration": "execution_duration_seconds",
    "execution_duration": "execution_duration_seconds",
    "resource_cost": "resource_cost_per_hour",
}
ALLOWED_REFERENCE_TYPES = {"expert_survey_reference", "operational_reference"}


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def parse_reference_csv(text: str) -> list[dict[str, str]]:
    rows = list(csv.DictReader(StringIO(text)))
    if not rows or not rows[0]:
        raise ValueError("The reference CSV is empty or has no header row")
    missing = REQUIRED_COLUMNS - set(rows[0])
    if missing:
        raise ValueError("Reference CSV is missing columns: " + ", ".join(sorted(missing)))
    result: list[dict[str, str]] = []
    for number, row in enumerate(rows, start=2):
        try:
            value = float(str(row["reference_value"]).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Row {number} has an invalid reference_value") from exc
        if value < 0:
            raise ValueError(f"Row {number} has a negative reference_value")
        reference_type = str(row["reference_type"] or "").strip()
        if reference_type not in ALLOWED_REFERENCE_TYPES:
            raise ValueError(
                f"Row {number} reference_type must be one of: "
                + ", ".join(sorted(ALLOWED_REFERENCE_TYPES))
            )
        result.append({**{key: str(value or "").strip() for key, value in row.items()},
                       "reference_value": str(value)})
    return result


def _candidate_value(candidate: ParameterCandidate) -> float | None:
    if candidate.scalar_value is not None:
        return float(candidate.scalar_value)
    if candidate.distribution and candidate.distribution.distribution_params:
        # Prosimos normal/lognormal generated distributions put the location/
        # mean parameter first; this is the existing baseline display value.
        return float(candidate.distribution.distribution_params[0])
    return None


def _matches(candidate: ParameterCandidate, row: dict[str, str]) -> bool:
    family = FAMILY_ALIASES.get(row["parameter_family"].strip(), row["parameter_family"].strip())
    if _key(candidate.process_alias) != _key(row["process_alias"]):
        return False
    if candidate.parameter_family != family:
        return False
    target = _key(row["entity_key"])
    return target in {_key(candidate.entity_id), _key(candidate.entity_name)}


def attach_independent_references(
    candidate_set: CandidateSet, rows: Iterable[dict[str, str]]
) -> tuple[CandidateSet, int]:
    """Return a copy with matched independent-reference fidelity attached."""
    references = list(rows)
    updated: list[ParameterCandidate] = []
    matched = 0
    for candidate in candidate_set.candidates:
        row = next((item for item in references if _matches(candidate, item)), None)
        value = _candidate_value(candidate)
        if row is None or value is None:
            updated.append(candidate)
            continue
        reference = float(row["reference_value"])
        error = abs(value - reference) / max(abs(reference), 1e-12)
        fidelity: dict[str, float | str | bool] = {
            "reference_type": row["reference_type"],
            "reference_value": reference,
            "candidate_value": value,
            "relative_error": error,
            "source": row["source"],
        }
        if row.get("reference_min") and row.get("reference_max"):
            lower, upper = float(row["reference_min"]), float(row["reference_max"])
            fidelity.update({"reference_min": lower, "reference_max": upper,
                             "inside_reference_range": lower <= value <= upper})
        updated.append(candidate.model_copy(update={"measured_fidelity": fidelity}))
        matched += 1
    return candidate_set.model_copy(update={"candidates": updated}), matched
