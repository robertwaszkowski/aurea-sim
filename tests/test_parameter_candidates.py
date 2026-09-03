import pytest
from pydantic import ValidationError

from aureasim.parameter_candidates import (
    ApplicationStatus,
    CandidateMethod,
    ConfidenceGrade,
    DistributionSpec,
    EvidenceReference,
    ExportCompatibility,
    ParameterCandidate,
    ReliabilityProfileReference,
    deterministic_candidate_id,
)


def candidate(**overrides):
    values = {
        "candidate_id": deterministic_candidate_id("P01", "task", "duration"),
        "process_alias": "P01",
        "process_id": "p",
        "process_version": "1",
        "parameter_family": "execution_duration_seconds",
        "entity_id": "task",
        "method": CandidateMethod.PROCESS_MINING,
        "unit": "seconds",
        "distribution": DistributionSpec(
            distribution_name="lognorm",
            distribution_params=[1.0, 0.0, 10.0, 1.0, 100.0],
            fit_method="calibration_quantiles",
        ),
        "evidence": [EvidenceReference(
            evidence_type="operational_log",
            source="references.csv",
            source_sha256="a" * 64,
            split="calibration",
            sample_size=100,
        )],
        "confidence_grade": ConfidenceGrade.MEDIUM,
        "confidence_basis": "Direct local calibration; prospective error unknown.",
        "application_status": ApplicationStatus.APPLIED,
    }
    values.update(overrides)
    return ParameterCandidate(**values)


def test_candidate_requires_a_value_and_calibration_only_mining_evidence():
    assert candidate().distribution.distribution_name == "lognorm"
    with pytest.raises(ValidationError, match="selection/holdout"):
        candidate(evidence=[EvidenceReference(
            evidence_type="operational_log", source="x", source_sha256="b" * 64,
            split="holdout", sample_size=10,
        )])
    with pytest.raises(ValidationError, match="requires scalar_value or distribution"):
        candidate(distribution=None)


def test_locked_review_state_must_set_lock_flag():
    with pytest.raises(ValidationError, match="locked=true"):
        candidate(review_status="locked", locked=False)


def test_zero_inflated_distribution_preserves_explicit_export_gap():
    distribution = DistributionSpec(
        distribution_name="zero_inflated_discrete",
        discrete_mass_points=[
            {"value": 0.0, "probability": 0.98},
            {"value": 1.0, "probability": 0.02},
        ],
        fit_method="calibration_zero_mass_and_positive_median",
    )
    compatibility = ExportCompatibility(
        target="prosimos_task_duration_1.2.4",
        supported=False,
        reason="Task parser does not accept discrete mass points.",
        fallback_distribution=DistributionSpec(
            distribution_name="fix",
            distribution_params=[0.0],
            fit_method="explicit_executable_fallback",
        ),
    )
    item = candidate(distribution=distribution, export_compatibility=[compatibility])
    assert item.distribution.discrete_mass_points[0].probability == 0.98
    assert item.export_compatibility[0].supported is False


def test_discrete_distribution_probabilities_must_sum_to_one():
    with pytest.raises(ValidationError, match="sum to one"):
        DistributionSpec(
            distribution_name="empirical_discrete",
            discrete_mass_points=[{"value": 0.0, "probability": 0.8}],
            fit_method="invalid_test",
        )


def test_candidate_can_reference_expected_error_without_claiming_fidelity():
    profile = ReliabilityProfileReference(
        profile_id="mrp_123",
        primary_error_metric="p50_scaled_absolute_error",
        reference_context="chronological_operational_selection",
        independent_units=39,
        expected_error_p10=0.04,
        expected_error_median=0.21,
        expected_error_p90=0.79,
        reliability_grade="high",
        generalizable_expected_range=True,
    )
    item = candidate(reliability_profile=profile)
    assert item.reliability_profile.expected_error_median == 0.21
    assert item.measured_fidelity is None


def test_reliability_profile_rejects_unordered_error_quantiles():
    with pytest.raises(ValidationError, match="quantiles must be ordered"):
        ReliabilityProfileReference(
            profile_id="mrp_bad",
            primary_error_metric="relative_error",
            reference_context="benchmark",
            independent_units=10,
            expected_error_p10=0.5,
            expected_error_median=0.2,
            expected_error_p90=0.8,
            reliability_grade="medium",
            generalizable_expected_range=True,
        )
