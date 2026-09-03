from aureasim.parameter_candidates import (
    CandidateMethod,
    CandidateSet,
    EvidenceReference,
    ParameterCandidate,
)
from aureasim.reference_evaluation import attach_independent_references, parse_reference_csv


def candidate() -> ParameterCandidate:
    return ParameterCandidate(
        candidate_id="candidate-1",
        process_alias="RES_Sales_Process", process_id="RES", process_version="1",
        parameter_family="execution_duration_seconds", entity_id="Task_Review",
        entity_name="Review", method=CandidateMethod.SEMANTIC_HEURISTIC, unit="seconds",
        scalar_value=120.0, evidence=[EvidenceReference(evidence_type="test", source="test", source_sha256="x")],
        confidence_basis="test",
    )


def candidate_set() -> CandidateSet:
    item = candidate()
    return CandidateSet(
        candidate_set_id="set-1", process_alias=item.process_alias, process_id=item.process_id,
        process_version="1", created_at="2026-01-01T00:00:00Z", assembly_policy="test",
        base_configuration_sha256="abc", candidates=[item],
    )


def test_expert_reference_is_attached_without_changing_candidate_value():
    rows = parse_reference_csv(
        "process_alias,parameter_family,entity_key,reference_value,reference_type,source\n"
        "RES_Sales_Process,execution_duration_seconds,Task_Review,100,expert_survey_reference,expert interview\n"
    )
    updated, matched = attach_independent_references(candidate_set(), rows)
    result = updated.candidates[0]
    assert matched == 1
    assert result.scalar_value == 120.0
    assert result.measured_fidelity["reference_type"] == "expert_survey_reference"
    assert result.measured_fidelity["relative_error"] == 0.2


def test_invalid_reference_type_is_rejected():
    try:
        parse_reference_csv(
            "process_alias,parameter_family,entity_key,reference_value,reference_type,source\n"
            "P01,execution_duration_seconds,Task_A,100,unlabelled,expert\n"
        )
    except ValueError as exc:
        assert "reference_type" in str(exc)
    else:
        raise AssertionError("invalid reference type should be rejected")
