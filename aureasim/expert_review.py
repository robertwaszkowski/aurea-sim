"""Auditable expert-review operations for parameter candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aureasim.parameter_candidates import (
    ApplicationStatus,
    CandidateMethod,
    CandidateSet,
    DistributionSpec,
    EvidenceReference,
    ParameterCandidate,
    ReviewStatus,
    deterministic_candidate_id,
)


def canonical_sha256(value: BaseModel | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class ReviewAction(str, Enum):
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"
    LOCK = "lock"


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    reviewer_id: str = Field(min_length=1, max_length=160)
    justification: str = Field(min_length=8, max_length=4000)
    scalar_value: float | None = None
    distribution: DistributionSpec | None = None

    @model_validator(mode="after")
    def check_edit_payload(self) -> "ReviewRequest":
        supplied = int(self.scalar_value is not None) + int(self.distribution is not None)
        if self.action == ReviewAction.EDIT and supplied != 1:
            raise ValueError("edit requires exactly one scalar value or distribution")
        if self.action != ReviewAction.EDIT and supplied:
            raise ValueError("only an edit action may supply a replacement value")
        return self


class ExpertReviewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    event_id: str
    candidate_set_id: str
    root_candidate_id: str
    before_candidate_id: str
    after_candidate_id: str
    action: ReviewAction
    reviewer_id: str
    justification: str
    occurred_at: str
    changed_fields: list[str]
    before_candidate_sha256: str
    after_candidate_sha256: str
    previous_event_sha256: str | None = None
    event_sha256: str


class CandidateReviewLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: int = 1
    candidate_set_id: str
    events: list[ExpertReviewEvent] = Field(default_factory=list)


class ReviewQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    parameter_family: str
    entity_id: str
    entity_name: str
    priority_score: float
    reasons: list[str]
    review_status: ReviewStatus
    confidence_grade: str


def _root_candidate_id(candidate: ParameterCandidate, ledger: CandidateReviewLedger) -> str:
    for event in reversed(ledger.events):
        if event.after_candidate_id == candidate.candidate_id:
            return event.root_candidate_id
    return candidate.derived_from_candidate_id or candidate.candidate_id


def _changed_fields(before: ParameterCandidate, after: ParameterCandidate) -> list[str]:
    left, right = before.model_dump(mode="json"), after.model_dump(mode="json")
    return sorted(key for key in left.keys() | right.keys() if left.get(key) != right.get(key))


def _event_hash_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "event_sha256"}


def verify_review_ledger(ledger: CandidateReviewLedger) -> None:
    previous: str | None = None
    for expected_sequence, event in enumerate(ledger.events, 1):
        if event.sequence != expected_sequence:
            raise ValueError("review ledger sequence is not contiguous")
        if event.previous_event_sha256 != previous:
            raise ValueError("review ledger hash chain is broken")
        calculated = canonical_sha256(_event_hash_payload(event.model_dump(mode="json")))
        if calculated != event.event_sha256:
            raise ValueError("review event hash does not match its content")
        previous = event.event_sha256


def verify_review_state(candidate_set: CandidateSet, ledger: CandidateReviewLedger) -> None:
    """Verify that every reviewed lineage still has its last audited snapshot."""
    verify_review_ledger(ledger)
    latest_by_root: dict[str, ExpertReviewEvent] = {}
    for event in ledger.events:
        latest_by_root[event.root_candidate_id] = event
    candidates = {candidate.candidate_id: candidate for candidate in candidate_set.candidates}
    for event in latest_by_root.values():
        current = candidates.get(event.after_candidate_id)
        if current is None:
            raise ValueError("reviewed candidate snapshot is missing from the candidate set")
        if canonical_sha256(current) != event.after_candidate_sha256:
            raise ValueError("reviewed candidate no longer matches its audited snapshot")


def apply_review_action(
    candidate_set: CandidateSet,
    ledger: CandidateReviewLedger,
    candidate_id: str,
    request: ReviewRequest,
    *,
    occurred_at: str | None = None,
) -> tuple[CandidateSet, CandidateReviewLedger, ExpertReviewEvent]:
    """Return updated immutable models and one hash-chained audit event."""
    if ledger.candidate_set_id != candidate_set.candidate_set_id:
        raise ValueError("review ledger belongs to a different candidate set")
    verify_review_state(candidate_set, ledger)
    index = next(
        (position for position, item in enumerate(candidate_set.candidates) if item.candidate_id == candidate_id),
        None,
    )
    if index is None:
        raise KeyError(f"candidate not found: {candidate_id}")
    before = candidate_set.candidates[index]
    if before.locked or before.review_status == ReviewStatus.LOCKED:
        raise ValueError("locked candidates cannot be changed")

    update: dict[str, Any]
    if request.action == ReviewAction.ACCEPT:
        update = {"review_status": ReviewStatus.ACCEPTED}
    elif request.action == ReviewAction.REJECT:
        update = {
            "review_status": ReviewStatus.REJECTED,
            "application_status": ApplicationStatus.ALTERNATIVE,
        }
    elif request.action == ReviewAction.LOCK:
        if before.review_status not in {ReviewStatus.ACCEPTED, ReviewStatus.EDITED}:
            raise ValueError("candidate must be accepted or edited before it can be locked")
        update = {"review_status": ReviewStatus.LOCKED, "locked": True}
    else:
        parent_hash = canonical_sha256(before)
        value_fingerprint = (
            request.distribution.model_dump(mode="json")
            if request.distribution is not None
            else request.scalar_value
        )
        edited_id = deterministic_candidate_id(
            "expert", before.candidate_id, before.candidate_revision + 1, value_fingerprint
        )
        expert_evidence = EvidenceReference(
            evidence_type="expert_review",
            source=f"reviewer:{request.reviewer_id}",
            source_sha256=parent_hash,
            notes=request.justification,
        )
        update = {
            "candidate_id": edited_id,
            "candidate_revision": before.candidate_revision + 1,
            "derived_from_candidate_id": before.candidate_id,
            "method": CandidateMethod.EXPERT,
            "scalar_value": request.scalar_value,
            "distribution": request.distribution,
            "evidence": [*before.evidence, expert_evidence],
            "confidence_basis": (
                before.confidence_basis
                + " Expert-refined; empirical reliability remains unchanged until independently evaluated."
            ),
            "review_status": ReviewStatus.EDITED,
            "application_status": ApplicationStatus.ALTERNATIVE,
            "locked": False,
            "measured_fidelity": None,
        }
    after = before.model_copy(update=update)
    # Revalidate the copied instance because model_copy intentionally skips validation.
    after = ParameterCandidate.model_validate(after.model_dump(mode="json"))
    candidates = list(candidate_set.candidates)
    if request.action == ReviewAction.EDIT:
        # An expert value is an alternative, not a destructive correction of
        # the evidence-derived value. Keeping both allows explicit comparison.
        candidates.append(after)
    else:
        candidates[index] = after
    updated_set = CandidateSet.model_validate(
        {**candidate_set.model_dump(mode="json"), "candidates": [item.model_dump(mode="json") for item in candidates]}
    )

    sequence = len(ledger.events) + 1
    timestamp = occurred_at or datetime.now(timezone.utc).isoformat()
    previous_hash = ledger.events[-1].event_sha256 if ledger.events else None
    event_data = {
        "sequence": sequence,
        "event_id": "",
        "candidate_set_id": candidate_set.candidate_set_id,
        "root_candidate_id": _root_candidate_id(before, ledger),
        "before_candidate_id": before.candidate_id,
        "after_candidate_id": after.candidate_id,
        "action": request.action.value,
        "reviewer_id": request.reviewer_id,
        "justification": request.justification,
        "occurred_at": timestamp,
        "changed_fields": _changed_fields(before, after),
        "before_candidate_sha256": canonical_sha256(before),
        "after_candidate_sha256": canonical_sha256(after),
        "previous_event_sha256": previous_hash,
        "event_sha256": "",
    }
    event_data["event_id"] = "ere_" + canonical_sha256({**event_data, "event_id": ""})[:24]
    event_data["event_sha256"] = canonical_sha256(_event_hash_payload(event_data))
    event = ExpertReviewEvent.model_validate(event_data)
    updated_ledger = CandidateReviewLedger(
        candidate_set_id=ledger.candidate_set_id,
        events=[*ledger.events, event],
    )
    verify_review_ledger(updated_ledger)
    return updated_set, updated_ledger, event


def build_review_queue(candidate_set: CandidateSet) -> list[ReviewQueueItem]:
    queue: list[ReviewQueueItem] = []
    for candidate in candidate_set.candidates:
        if candidate.review_status in {ReviewStatus.REJECTED, ReviewStatus.LOCKED}:
            continue
        score = 0.0
        reasons: list[str] = []
        if candidate.validity != "valid":
            score += 100
            reasons.append("invalid candidate")
        if candidate.confidence_grade.value == "unknown":
            score += 60
            reasons.append("unknown confidence")
        elif candidate.confidence_grade.value == "low":
            score += 50
            reasons.append("low confidence")
        if candidate.reliability_profile and not candidate.reliability_profile.generalizable_expected_range:
            score += 40
            reasons.append("expected-error evidence is not generalizable")
        expected_median = None
        if candidate.reliability_profile:
            expected_median = candidate.reliability_profile.expected_error_median
        elif candidate.expected_error:
            expected_median = candidate.expected_error.get("median")
        if expected_median is not None and expected_median > 0.35:
            score += min(40.0, expected_median * 40.0)
            reasons.append(f"expected median error {expected_median:.1%}")
        if any(not compatibility.supported for compatibility in candidate.export_compatibility):
            score += 30
            reasons.append("not directly exportable")
        if candidate.review_status == ReviewStatus.PENDING:
            score += 20
            reasons.append("expert review pending")
        if reasons:
            queue.append(ReviewQueueItem(
                candidate_id=candidate.candidate_id,
                parameter_family=candidate.parameter_family,
                entity_id=candidate.entity_id,
                entity_name=candidate.entity_name,
                priority_score=score,
                reasons=reasons,
                review_status=candidate.review_status,
                confidence_grade=candidate.confidence_grade.value,
            ))
    return sorted(queue, key=lambda item: (-item.priority_score, item.parameter_family, item.entity_id))


def load_review_files(candidate_path: Path, ledger_path: Path) -> tuple[CandidateSet, CandidateReviewLedger]:
    candidate_set = CandidateSet.model_validate_json(candidate_path.read_text(encoding="utf-8"))
    if ledger_path.exists():
        ledger = CandidateReviewLedger.model_validate_json(ledger_path.read_text(encoding="utf-8"))
    else:
        ledger = CandidateReviewLedger(candidate_set_id=candidate_set.candidate_set_id)
    verify_review_ledger(ledger)
    verify_review_state(candidate_set, ledger)
    return candidate_set, ledger


def save_review_files(
    candidate_path: Path,
    ledger_path: Path,
    candidate_set: CandidateSet,
    ledger: CandidateReviewLedger,
) -> None:
    """Validate first, then atomically replace each project file."""
    verify_review_state(candidate_set, ledger)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_temp = candidate_path.with_suffix(candidate_path.suffix + ".tmp")
    ledger_temp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    candidate_temp.write_text(candidate_set.model_dump_json(indent=2), encoding="utf-8")
    ledger_temp.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
    candidate_temp.replace(candidate_path)
    ledger_temp.replace(ledger_path)
