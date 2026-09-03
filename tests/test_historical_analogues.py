import pytest

from aureasim.historical_analogues import (
    HistoricalTaskProfile,
    find_temporal_semantic_analogues,
    find_temporal_semantic_analogues_v2,
    find_similar_tasks,
    select_consistent_donor_cluster,
    semantic_similarity,
)


def profile(alias: str, process_id: str, task_id: str, name: str, n: int = 100, *, version: str = "1", start: str = "", end: str = ""):
    return HistoricalTaskProfile(
        process_alias=alias,
        process_id=process_id,
        process_version=version,
        task_id=task_id,
        task_name=name,
        predecessor_labels=("start",),
        successor_labels=("archive invoice",),
        role_label="accounting specialist",
        process_name="invoice processing",
        domain_fields=frozenset({"invoice number", "amount"}),
        observation_count=n,
        observed_from=start,
        observed_to=end,
    )


def test_semantic_similarity_is_normalized_and_symmetric():
    assert semantic_similarity("Weryfikacja faktury", "weryfikacja FAKTURY") == pytest.approx(1.0)
    assert semantic_similarity("alpha", "beta") == semantic_similarity("beta", "alpha")


def test_retrieval_excludes_same_process_and_insufficient_samples():
    target = profile("P01", "invoice", "t", "verify invoice")
    donors = [
        profile("P01", "invoice", "same", "verify invoice"),
        profile("P02", "other", "small", "verify invoice", n=10),
        profile("P03", "third", "valid", "verify invoice"),
    ]
    matches = find_similar_tasks(target, donors)
    assert [match.profile.task_id for match in matches] == ["valid"]
    assert matches[0].score == pytest.approx(1.0)


def test_retrieval_does_not_lower_threshold():
    target = profile("P01", "invoice", "t", "approve invoice")
    donor = profile("P02", "other", "d", "unrelated warehouse task")
    assert find_similar_tasks(target, [donor], minimum_score=0.99) == []


def test_hsar_admits_prior_versions_and_prior_cross_process_analogues():
    target = profile("P01-v2", "invoice", "target", "verify invoice", version="2", start="2026-06-01T00:00:00Z")
    donors = [
        profile("P01-v1", "invoice", "previous", "verify invoice", version="1", end="2026-05-31T23:59:59Z"),
        profile("P02", "expense", "other", "verify invoice", end="2026-05-15T00:00:00Z"),
        profile("P01-v2", "invoice", "same-version", "verify invoice", version="2", end="2026-05-15T00:00:00Z"),
        profile("P03", "future", "future", "verify invoice", end="2026-06-02T00:00:00Z"),
    ]
    matches = find_temporal_semantic_analogues(target, donors)
    assert [(match.profile.task_id, match.donor_scope) for match in matches] == [
        ("previous", "prior_version"), ("other", "cross_process")
    ]


def test_hsar_requires_recorded_temporal_bounds():
    target = profile("P01-v2", "invoice", "target", "verify invoice", version="2")
    donor = profile("P01-v1", "invoice", "previous", "verify invoice", version="1")
    assert find_temporal_semantic_analogues(target, [donor]) == []


def test_hsar_v2_rejects_cross_process_donor_with_incompatible_form_contract():
    target = profile("P01-v2", "invoice", "target", "verify invoice", version="2", start="2026-06-01T00:00:00Z")
    target = HistoricalTaskProfile(**{**target.__dict__, "form_access_signature": frozenset({"amount\x1fm", "decision\x1fq"})})
    prior = HistoricalTaskProfile(**{**target.__dict__, "process_alias": "P01-v1", "process_version": "1", "task_id": "prior", "observed_from": "", "observed_to": "2026-05-01T00:00:00Z"})
    incompatible = HistoricalTaskProfile(**{**target.__dict__, "process_alias": "P02", "process_id": "other", "task_id": "cross", "form_access_signature": frozenset({"unrelated\x1fm"}), "observed_from": "", "observed_to": "2026-05-01T00:00:00Z"})
    matches = find_temporal_semantic_analogues_v2(target, [prior, incompatible])
    assert [(match.profile.task_id, match.donor_scope) for match in matches] == [("prior", "prior_version")]


def test_hsar_v2_selects_largest_consistent_donor_cluster():
    target = profile("T", "target", "target", "verify invoice")
    donors = [
        HistoricalTaskProfile(**{**target.__dict__, "process_alias": f"P{index}", "process_id": f"donor-{index}", "task_id": f"d{index}"})
        for index in range(3)
    ]
    from aureasim.historical_analogues import AnalogueMatch
    matches = [AnalogueMatch(donor, 1.0, 1.0, 1.0, 1.0, 0.8) for donor in donors]
    selected, excluded, medians = select_consistent_donor_cluster(
        matches, {donors[0]: [90, 100, 110], donors[1]: [100, 110, 120], donors[2]: [400, 500, 600]}
    )
    assert [match.profile.task_id for match in selected] == ["d0", "d1"]
    assert [match.profile.task_id for match in excluded] == ["d2"]
    assert medians[donors[0]] == 100
