"""Deterministic, leakage-aware retrieval of historical task analogues."""

from __future__ import annotations

import math
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from typing import Iterable, Mapping, Sequence


TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(TOKEN_RE.findall(ascii_text))


def token_jaccard(left: str, right: str) -> float:
    a = set(normalize_text(left).split())
    b = set(normalize_text(right).split())
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _ngrams(value: str, size: int = 3) -> Counter[str]:
    compact = f"  {normalize_text(value)}  "
    return Counter(compact[index : index + size] for index in range(len(compact) - size + 1))


def character_ngram_cosine(left: str, right: str) -> float:
    a = _ngrams(left)
    b = _ngrams(right)
    if not a or not b:
        return 0.0
    numerator = sum(value * b.get(key, 0) for key, value in a.items())
    denominator = math.sqrt(sum(value * value for value in a.values())) * math.sqrt(
        sum(value * value for value in b.values())
    )
    return numerator / denominator if denominator else 0.0


def semantic_similarity(left: str, right: str) -> float:
    return (token_jaccard(left, right) + character_ngram_cosine(left, right)) / 2.0


def set_jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a = {normalize_text(value) for value in left if normalize_text(value)}
    b = {normalize_text(value) for value in right if normalize_text(value)}
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _degree_similarity(left: int, right: int) -> float:
    return 1.0 - abs(left - right) / max(left, right, 1)


def _neighbour_similarity(left: Sequence[str], right: Sequence[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    forward = sum(max(semantic_similarity(item, other) for other in right) for item in left) / len(left)
    backward = sum(max(semantic_similarity(item, other) for other in left) for item in right) / len(right)
    return (forward + backward) / 2.0


@dataclass(frozen=True)
class HistoricalTaskProfile:
    process_alias: str
    process_id: str
    process_version: str
    task_id: str
    task_name: str
    task_kind: str = "PROCESSSTEP"
    parameter_family: str = "execution_duration_seconds"
    unit: str = "seconds"
    predecessor_labels: tuple[str, ...] = ()
    successor_labels: tuple[str, ...] = ()
    role_label: str = ""
    process_name: str = ""
    domain_fields: frozenset[str] = field(default_factory=frozenset)
    # Exact (field-path, access-class) tokens for the task's form contract.
    # It is deliberately task-specific: a process-wide field set cannot
    # distinguish reused task labels with different permitted interactions.
    form_access_signature: frozenset[str] = field(default_factory=frozenset)
    observation_count: int = 0
    # ISO-8601 bounds of the evidence used to derive this profile.  They are
    # deliberately profile metadata rather than a version-number heuristic:
    # version labels need not be chronologically sortable.
    observed_from: str = ""
    observed_to: str = ""


@dataclass(frozen=True)
class AnalogueMatch:
    profile: HistoricalTaskProfile
    semantic: float
    bpmn_context: float
    role: float
    domain: float
    score: float
    donor_scope: str = "cross_process"
    form_access: float = 0.0


def form_access_similarity(target: HistoricalTaskProfile, donor: HistoricalTaskProfile) -> float:
    """Exact Jaccard similarity of task form-path/access signatures.

    Missing signatures mean that compatibility is unverified, not perfect.
    This avoids treating two unavailable form descriptions as evidence of a
    common task contract.
    """
    left = {item.casefold() for item in target.form_access_signature if item}
    right = {item.casefold() for item in donor.form_access_signature if item}
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _has_required_context(profile: HistoricalTaskProfile) -> bool:
    return bool(profile.role_label and profile.predecessor_labels and profile.successor_labels)


def _same_normalized_role(left: HistoricalTaskProfile, right: HistoricalTaskProfile) -> bool:
    return bool(normalize_text(left.role_label)) and normalize_text(left.role_label) == normalize_text(right.role_label)


def similarity_components(
    target: HistoricalTaskProfile, donor: HistoricalTaskProfile
) -> dict[str, float]:
    context = (
        _degree_similarity(len(target.predecessor_labels), len(donor.predecessor_labels))
        + _degree_similarity(len(target.successor_labels), len(donor.successor_labels))
        + _neighbour_similarity(target.predecessor_labels, donor.predecessor_labels)
        + _neighbour_similarity(target.successor_labels, donor.successor_labels)
    ) / 4.0
    role = (
        semantic_similarity(target.role_label, donor.role_label)
        if target.role_label and donor.role_label
        else 0.0
    )
    domain = (
        semantic_similarity(target.process_name, donor.process_name)
        + set_jaccard(target.domain_fields, donor.domain_fields)
    ) / 2.0
    return {
        "semantic": semantic_similarity(target.task_name, donor.task_name),
        "bpmn_context": context,
        "role": role,
        "domain": domain,
    }


def find_similar_tasks(
    target: HistoricalTaskProfile,
    candidates: Iterable[HistoricalTaskProfile],
    *,
    weights: Mapping[str, float] | None = None,
    minimum_score: float = 0.70,
    maximum_results: int = 5,
    minimum_observations: int = 30,
) -> list[AnalogueMatch]:
    """Return ranked compatible donors while excluding the target process."""
    selected_weights = dict(
        weights
        or {"semantic": 0.55, "bpmn_context": 0.20, "role": 0.15, "domain": 0.10}
    )
    if not math.isclose(sum(selected_weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("similarity weights must sum to one")
    matches: list[AnalogueMatch] = []
    for donor in candidates:
        if donor.process_id == target.process_id:
            continue
        if donor.task_kind != target.task_kind:
            continue
        if donor.parameter_family != target.parameter_family or donor.unit != target.unit:
            continue
        if donor.observation_count < minimum_observations:
            continue
        components = similarity_components(target, donor)
        score = sum(selected_weights[name] * components[name] for name in selected_weights)
        if score >= minimum_score:
            matches.append(AnalogueMatch(donor, score=score, **components))
    matches.sort(key=lambda match: (-match.score, match.profile.process_alias, match.profile.task_id))
    return matches[:maximum_results]


def _parse_observation_time(value: str) -> datetime | None:
    """Parse a repository time bound, accepting the standard ``Z`` suffix."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Invalid ISO-8601 observation time: {value!r}") from error


def is_strictly_prior(donor: HistoricalTaskProfile, target: HistoricalTaskProfile) -> bool:
    """Whether all donor evidence predates the target evidence window.

    This is the leakage barrier for Historical Semantic Analogue Refinement
    (HSAR).  It intentionally uses recorded observation times, not process
    version labels, because labels such as ``1.10`` and ``1.9`` are not a
    reliable chronology.
    """
    donor_end = _parse_observation_time(donor.observed_to)
    target_start = _parse_observation_time(target.observed_from)
    return donor_end is not None and target_start is not None and donor_end < target_start


def find_temporal_semantic_analogues(
    target: HistoricalTaskProfile,
    candidates: Iterable[HistoricalTaskProfile],
    *,
    weights: Mapping[str, float] | None = None,
    minimum_score: float = 0.70,
    maximum_results: int = 5,
    minimum_observations: int = 30,
) -> list[AnalogueMatch]:
    """Return HSAR donors: prior versions and prior cross-process analogues.

    A donor is eligible only when its complete evidence window ends before the
    target window starts.  This admits two evidence sources in one ranked list:
    a prior version of the same logical process and an analogous task from a
    different process.  The target version itself and any concurrent/future
    evidence are always excluded.
    """
    selected_weights = dict(
        weights
        or {"semantic": 0.55, "bpmn_context": 0.20, "role": 0.15, "domain": 0.10}
    )
    if not math.isclose(sum(selected_weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("similarity weights must sum to one")
    matches: list[AnalogueMatch] = []
    for donor in candidates:
        if donor.process_id == target.process_id and donor.process_version == target.process_version:
            continue
        if not is_strictly_prior(donor, target):
            continue
        if donor.task_kind != target.task_kind:
            continue
        if donor.parameter_family != target.parameter_family or donor.unit != target.unit:
            continue
        if donor.observation_count < minimum_observations:
            continue
        components = similarity_components(target, donor)
        score = sum(selected_weights[name] * components[name] for name in selected_weights)
        if score >= minimum_score:
            scope = "prior_version" if donor.process_id == target.process_id else "cross_process"
            matches.append(AnalogueMatch(donor, score=score, donor_scope=scope, **components))
    matches.sort(key=lambda match: (-match.score, match.profile.process_alias, match.profile.task_id))
    return matches[:maximum_results]


def find_temporal_semantic_analogues_v2(
    target: HistoricalTaskProfile,
    candidates: Iterable[HistoricalTaskProfile],
    *,
    weights: Mapping[str, float] | None = None,
    minimum_score: float = 0.70,
    minimum_form_access_similarity: float = 0.35,
    maximum_results: int = 5,
    minimum_observations: int = 30,
) -> list[AnalogueMatch]:
    """Retrieve HSAR-v2 donors with contract-aware cross-process screening.

    Prior versions of the same logical process retain their own evidence route.
    Cross-process donors must additionally have equal normalized roles,
    populated predecessor/successor context, and an adequate exact form-access
    signature.  The function does *not* pool donors; pooling is a separate,
    auditable clustered step.
    """
    selected_weights = dict(
        weights
        or {"semantic": 0.55, "bpmn_context": 0.20, "role": 0.15, "domain": 0.10}
    )
    if not math.isclose(sum(selected_weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("similarity weights must sum to one")
    if not 0.0 <= minimum_form_access_similarity <= 1.0:
        raise ValueError("minimum_form_access_similarity must be between zero and one")
    if not _has_required_context(target):
        return []
    matches: list[AnalogueMatch] = []
    for donor in candidates:
        if donor.process_id == target.process_id and donor.process_version == target.process_version:
            continue
        if not is_strictly_prior(donor, target):
            continue
        if donor.task_kind != target.task_kind:
            continue
        if donor.parameter_family != target.parameter_family or donor.unit != target.unit:
            continue
        if donor.observation_count < minimum_observations or not _has_required_context(donor):
            continue
        if not _same_normalized_role(target, donor):
            continue
        scope = "prior_version" if donor.process_id == target.process_id else "cross_process"
        form_access = form_access_similarity(target, donor)
        if scope == "cross_process" and form_access < minimum_form_access_similarity:
            continue
        components = similarity_components(target, donor)
        score = sum(selected_weights[name] * components[name] for name in selected_weights)
        if score >= minimum_score:
            matches.append(AnalogueMatch(
                donor, score=score, donor_scope=scope, form_access=form_access, **components
            ))
    matches.sort(key=lambda match: (-match.score, match.profile.process_alias, match.profile.task_id))
    return matches[:maximum_results]


def select_consistent_donor_cluster(
    matches: Sequence[AnalogueMatch],
    samples_by_profile: Mapping[HistoricalTaskProfile, Sequence[float]],
    *,
    maximum_median_ratio: float = 2.0,
    minimum_donors: int = 2,
) -> tuple[list[AnalogueMatch], list[AnalogueMatch], dict[HistoricalTaskProfile, float]]:
    """Select the largest internally consistent set of donor task medians.

    The deterministic tie-breaker is total retrieval score then tighter median
    ratio.  Values outside the selected cluster are returned explicitly rather
    than silently blended into the candidate distribution.
    """
    if maximum_median_ratio < 1.0:
        raise ValueError("maximum_median_ratio must be at least one")
    medians: dict[HistoricalTaskProfile, float] = {}
    usable: list[AnalogueMatch] = []
    for match in matches:
        values = [float(value) for value in samples_by_profile.get(match.profile, ()) if float(value) > 0]
        if values:
            medians[match.profile] = statistics.median(values)
            usable.append(match)
    candidates: list[tuple[int, float, float, tuple[AnalogueMatch, ...]]] = []
    for size in range(minimum_donors, len(usable) + 1):
        for subset in combinations(usable, size):
            subset_medians = [medians[item.profile] for item in subset]
            ratio = max(subset_medians) / min(subset_medians)
            if ratio <= maximum_median_ratio:
                candidates.append((len(subset), sum(item.score for item in subset), -ratio, subset))
    if not candidates:
        return [], list(matches), medians
    chosen = list(max(candidates, key=lambda item: item[:3])[-1])
    chosen_profiles = {item.profile for item in chosen}
    return chosen, [item for item in matches if item.profile not in chosen_profiles], medians
