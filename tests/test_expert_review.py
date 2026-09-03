import json

import pytest
from pydantic import ValidationError

from aureasim.expert_review import (
    CandidateReviewLedger,
    ReviewRequest,
    apply_review_action,
    build_review_queue,
    load_review_files,
    save_review_files,
    verify_review_ledger,
    verify_review_state,
)
from aureasim.parameter_candidates import (
    CandidateSet,
    DistributionSpec,
    EvidenceReference,
    ParameterCandidate,
    deterministic_candidate_id,
)


def candidate(confidence="low"):
    return ParameterCandidate(
        candidate_id=deterministic_candidate_id("P01", "task", "duration"),
        process_alias="P01", process_id="p", process_version="1",
        parameter_family="execution_duration_seconds", entity_id="task",
        entity_name="Review invoice", method="semantic_label_heuristic", unit="seconds",
        distribution=DistributionSpec(
            distribution_name="lognorm", distribution_params=[1, 0, 10, 1, 100],
            fit_method="semantic",
        ),
        evidence=[EvidenceReference(
            evidence_type="generation", source="run.json", source_sha256="a" * 64,
        )],
        confidence_grade=confidence,
        confidence_basis="Method reliability profile.",
        expected_error={"median": 0.8},
    )


def candidate_set():
    item = candidate()
    return CandidateSet(
        candidate_set_id="pcs_test", process_alias="P01", process_id="p",
        process_version="1", created_at="2026-08-15T00:00:00+00:00",
        assembly_policy="test", base_configuration_sha256="b" * 64,
        candidates=[item],
    )


def request(action, **values):
    return ReviewRequest(
        action=action, reviewer_id="expert-01",
        justification="Reviewed against operational knowledge.", **values,
    )


def test_justification_and_edit_value_are_required():
    with pytest.raises(ValidationError):
        ReviewRequest(action="accept", reviewer_id="x", justification="short")
    with pytest.raises(ValidationError, match="exactly one"):
        request("edit")


def test_edit_creates_derived_expert_candidate_and_hash_chained_event():
    items = candidate_set()
    ledger = CandidateReviewLedger(candidate_set_id=items.candidate_set_id)
    original = items.candidates[0]
    distribution = DistributionSpec(
        distribution_name="fix", distribution_params=[120.0], fit_method="expert_point",
    )
    updated, ledger, event = apply_review_action(
        items, ledger, original.candidate_id, request("edit", distribution=distribution),
        occurred_at="2026-08-15T10:00:00+00:00",
    )
    assert len(updated.candidates) == 2
    assert updated.candidates[0] == original
    edited = updated.candidates[1]
    assert edited.candidate_id != original.candidate_id
    assert edited.derived_from_candidate_id == original.candidate_id
    assert edited.method.value == "expert_refined"
    assert edited.measured_fidelity is None
    assert event.changed_fields
    verify_review_ledger(ledger)


def test_lock_requires_review_and_is_terminal():
    items = candidate_set()
    ledger = CandidateReviewLedger(candidate_set_id=items.candidate_set_id)
    identifier = items.candidates[0].candidate_id
    with pytest.raises(ValueError, match="accepted or edited"):
        apply_review_action(items, ledger, identifier, request("lock"))
    items, ledger, _ = apply_review_action(items, ledger, identifier, request("accept"))
    items, ledger, _ = apply_review_action(items, ledger, identifier, request("lock"))
    assert items.candidates[0].locked is True
    with pytest.raises(ValueError, match="locked"):
        apply_review_action(items, ledger, identifier, request("reject"))


def test_review_queue_prioritizes_weak_pending_candidates():
    queue = build_review_queue(candidate_set())
    assert queue[0].priority_score >= 70
    assert "low confidence" in queue[0].reasons
    assert any(reason.startswith("expected median error") for reason in queue[0].reasons)


def test_tampering_is_detected_and_files_round_trip(tmp_path):
    items = candidate_set()
    ledger = CandidateReviewLedger(candidate_set_id=items.candidate_set_id)
    identifier = items.candidates[0].candidate_id
    items, ledger, _ = apply_review_action(items, ledger, identifier, request("accept"))
    candidate_path, ledger_path = tmp_path / "candidates.json", tmp_path / "ledger.json"
    save_review_files(candidate_path, ledger_path, items, ledger)
    loaded_items, loaded_ledger = load_review_files(candidate_path, ledger_path)
    assert loaded_items == items
    assert loaded_ledger == ledger
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    data["events"][0]["justification"] = "tampered justification"
    ledger_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        load_review_files(candidate_path, ledger_path)


def test_candidate_snapshot_tampering_is_detected():
    items = candidate_set()
    ledger = CandidateReviewLedger(candidate_set_id=items.candidate_set_id)
    identifier = items.candidates[0].candidate_id
    items, ledger, _ = apply_review_action(items, ledger, identifier, request("accept"))
    tampered_candidate = items.candidates[0].model_copy(update={"confidence_basis": "tampered"})
    tampered_set = items.model_copy(update={"candidates": [tampered_candidate]})
    with pytest.raises(ValueError, match="audited snapshot"):
        verify_review_state(tampered_set, ledger)
