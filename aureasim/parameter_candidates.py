"""Typed parameter candidates with provenance, confidence, and review state."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CandidateMethod(str, Enum):
    GENERIC_HEURISTIC = "generic_label_heuristic"
    SEMANTIC_HEURISTIC = "semantic_label_heuristic"
    EVIDENCE_GROUNDED = "evidence_grounded"
    PROCESS_MINING = "process_mining_calibration"
    HISTORICAL_ANALOGUE = "historical_analogue"
    EXPERT = "expert_refined"
    HYBRID = "hybrid_selected"


class ConfidenceGrade(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"
    LOCKED = "locked"


class ApplicationStatus(str, Enum):
    APPLIED = "applied"
    ALTERNATIVE = "alternative"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    INVALID = "invalid"


class DiscreteMassPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    probability: float = Field(ge=0, le=1)


class DistributionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribution_name: str
    distribution_params: list[float] = Field(default_factory=list)
    discrete_mass_points: list[DiscreteMassPoint] = Field(default_factory=list)
    fit_method: str
    empirical_quantiles: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_representation(self) -> "DistributionSpec":
        if self.discrete_mass_points:
            total = sum(point.probability for point in self.discrete_mass_points)
            if abs(total - 1.0) > 1e-9:
                raise ValueError("discrete mass probabilities must sum to one")
            values = [point.value for point in self.discrete_mass_points]
            if len(values) != len(set(values)):
                raise ValueError("discrete mass values must be unique")
        if self.distribution_name in {"zero_inflated_discrete", "empirical_discrete"}:
            if not self.discrete_mass_points:
                raise ValueError("discrete distribution requires mass points")
            if self.distribution_params:
                raise ValueError("discrete distribution may not also use numeric parameters")
        return self


class ExportCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str
    supported: bool
    reason: str
    fallback_distribution: DistributionSpec | None = None


class ReliabilityProfileReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    primary_error_metric: str
    reference_context: str
    independent_units: int = Field(ge=1)
    expected_error_p10: float = Field(ge=0)
    expected_error_median: float = Field(ge=0)
    expected_error_p90: float = Field(ge=0)
    reliability_grade: ConfidenceGrade
    generalizable_expected_range: bool

    @model_validator(mode="after")
    def check_quantile_order(self) -> "ReliabilityProfileReference":
        if not (
            self.expected_error_p10
            <= self.expected_error_median
            <= self.expected_error_p90
        ):
            raise ValueError("expected error quantiles must be ordered p10 <= median <= p90")
        return self


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: str
    source: str
    source_sha256: str
    split: str | None = None
    sample_size: int | None = Field(default=None, ge=0)
    notes: str = ""


class ParameterCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    candidate_revision: int = Field(default=1, ge=1)
    derived_from_candidate_id: str | None = None
    process_alias: str
    process_id: str
    process_version: str
    parameter_family: str
    entity_id: str
    entity_name: str = ""
    method: CandidateMethod
    unit: str
    scalar_value: float | None = None
    distribution: DistributionSpec | None = None
    evidence: list[EvidenceReference] = Field(min_length=1)
    confidence_grade: ConfidenceGrade = ConfidenceGrade.UNKNOWN
    confidence_basis: str
    uncertainty: dict[str, float] | None = None
    expected_error: dict[str, float] | None = None
    # Numeric error measures plus the identity of the independent reference.
    # A reference type is essential: operational logs and an expert survey are
    # both useful checks, but they must not be presented as the same evidence.
    measured_fidelity: dict[str, float | str | bool] | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    application_status: ApplicationStatus = ApplicationStatus.ALTERNATIVE
    locked: bool = False
    validity: str = "valid"
    validation_messages: list[str] = Field(default_factory=list)
    export_compatibility: list[ExportCompatibility] = Field(default_factory=list)
    reliability_profile: ReliabilityProfileReference | None = None

    @model_validator(mode="after")
    def check_value_and_lock(self) -> "ParameterCandidate":
        if self.scalar_value is None and self.distribution is None:
            raise ValueError("candidate requires scalar_value or distribution")
        if self.review_status == ReviewStatus.LOCKED and not self.locked:
            raise ValueError("locked review status requires locked=true")
        if self.method == CandidateMethod.PROCESS_MINING:
            if any(item.split not in {"calibration", None} for item in self.evidence):
                raise ValueError("process-mining candidates may not use selection/holdout evidence")
        return self


class CandidateSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: int = 1
    candidate_set_id: str
    process_alias: str
    process_id: str
    process_version: str
    created_at: str
    assembly_policy: str
    base_configuration_sha256: str
    candidates: list[ParameterCandidate]

    @model_validator(mode="after")
    def check_candidate_identity(self) -> "CandidateSet":
        identifiers = [candidate.candidate_id for candidate in self.candidates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("candidate IDs must be unique within a candidate set")
        for candidate in self.candidates:
            if candidate.process_alias != self.process_alias:
                raise ValueError("candidate process alias must match its candidate set")
        return self


class CandidateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameter_family: str
    entity_id: str
    candidate_id: str
    selection_reason: str


class HybridConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: int = 1
    hybrid_configuration_id: str
    candidate_set_id: str
    process_alias: str
    selections: list[CandidateSelection]
    explicit_assumptions: dict[str, str | float | int]
    evaluation_status: str
    configuration_sha256: str | None = None


def deterministic_candidate_id(*parts: object) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    return "pc_" + hashlib.sha256(encoded).hexdigest()[:24]


def new_candidate_set_id(process_alias: str, candidate_ids: list[str]) -> str:
    return deterministic_candidate_id("set", process_alias, *sorted(candidate_ids)).replace(
        "pc_", "pcs_", 1
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
