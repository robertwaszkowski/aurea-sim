import json
from pathlib import Path

import server

from aureasim.historical_repository import (
    candidate_from_search,
    public_search_result,
    search_repository,
)


def repository(path, *, strategy="cross_process_semantic"):
    def record(alias, process_id, task_id, observations=40, *, version="1", start="", end=""):
        return {
            "profile": {
                "process_alias": alias,
                "process_id": process_id,
                "process_version": version,
                "task_id": task_id,
                "task_name": "Verify application",
                "task_kind": "PROCESSSTEP",
                "parameter_family": "execution_duration_seconds",
                "unit": "seconds",
                "predecessor_labels": ["Register application"],
                "successor_labels": ["Approve application"],
                "role_label": "Clerk",
                "process_name": "Application handling",
                "domain_fields": ["application", "amount"],
                "form_access_signature": ["application\u001fm", "amount\u001fq"],
                "observation_count": observations,
                "observed_from": start,
                "observed_to": end,
            },
            "calibration_samples_seconds": [60, 90, 120, 180],
        }
    payload = {
        "format_version": 1,
        "minimum_score": 0.70,
        "weights": {"semantic": 0.55, "bpmn_context": 0.20, "role": 0.15, "domain": 0.10},
        "minimum_donor_observations": 30,
        "minimum_analogue_tasks": 3,
        "minimum_process_families": 2,
        "minimum_combined_executions": 100,
        "maximum_results": 5,
        "retrieval_strategy": strategy,
        "profiles": [
            record("TARGET", "target-process", "target-task"),
            record("P01", "donor-1", "task-1"),
            record("P02", "donor-2", "task-2"),
            record("P02", "donor-3", "task-3"),
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_search_excludes_target_process_and_builds_candidate(tmp_path):
    path = tmp_path / "historical_task_repository.json"
    repository(path)
    result = search_repository(
        repository_path=path,
        project_path=tmp_path,
        task_id="target-task",
        process_alias="TARGET",
        process_id="target-process",
        process_version="1",
    )
    public = public_search_result(result)
    assert public["sufficient"] is True
    assert len(public["matches"]) == 3
    assert all(item["process_alias"] != "TARGET" for item in public["matches"])
    candidate = candidate_from_search(result, path)
    assert candidate.method.value == "historical_analogue"
    assert candidate.distribution.distribution_name == "lognorm"
    assert candidate.evidence[0].split == "calibration"


def test_hsar_search_uses_prior_version_and_cross_process_donors(tmp_path):
    path = tmp_path / "historical_task_repository.json"
    repository(path, strategy="historical_semantic_analogue")
    payload = json.loads(path.read_text(encoding="utf-8"))
    target, prior, first_cross, second_cross = payload["profiles"]
    target["profile"].update({"process_version": "2", "observed_from": "2026-06-01T00:00:00Z"})
    prior["profile"].update({"process_id": "target-process", "observed_to": "2026-05-01T00:00:00Z"})
    first_cross["profile"]["observed_to"] = "2026-05-01T00:00:00Z"
    second_cross["profile"]["observed_to"] = "2026-05-01T00:00:00Z"
    for item in (prior, first_cross, second_cross):
        item["profile"]["observation_count"] = 100
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = search_repository(
        repository_path=path, project_path=tmp_path, task_id="target-task",
        process_alias="TARGET", process_id="target-process", process_version="2",
    )
    public = public_search_result(result)
    assert public["retrieval_strategy"] == "historical_semantic_analogue"
    assert {item["donor_scope"] for item in public["matches"]} == {"prior_version", "cross_process"}
    candidate = candidate_from_search(result, path)
    assert "HSAR: all donor evidence predates" in candidate.evidence[0].notes


def test_hsar_v2_reports_selected_and_excluded_donor_clusters(tmp_path):
    path = tmp_path / "historical_task_repository.json"
    repository(path, strategy="historical_semantic_analogue_v2")
    payload = json.loads(path.read_text(encoding="utf-8"))
    target, prior, first_cross, second_cross = payload["profiles"]
    target["profile"].update({"process_version": "2", "observed_from": "2026-06-01T00:00:00Z"})
    prior["profile"].update({"process_id": "target-process", "observed_to": "2026-05-01T00:00:00Z"})
    first_cross["profile"]["observed_to"] = "2026-05-01T00:00:00Z"
    second_cross["profile"]["observed_to"] = "2026-05-01T00:00:00Z"
    for item in (prior, first_cross, second_cross):
        item["profile"]["observation_count"] = 100
    prior["calibration_samples_seconds"] = [90, 100, 110]
    first_cross["calibration_samples_seconds"] = [100, 110, 120]
    second_cross["calibration_samples_seconds"] = [500, 600, 700]
    payload.update({"minimum_form_access_similarity": 0.35, "maximum_median_ratio_within_cluster": 2.0, "minimum_cluster_donors": 2, "minimum_prior_version_observations": 100})
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = search_repository(
        repository_path=path, project_path=tmp_path, task_id="target-task",
        process_alias="TARGET", process_id="target-process", process_version="2",
    )
    public = public_search_result(result)
    assert public["sufficient"] is True
    assert len(public["matches"]) == 2
    assert len(public["excluded_matches"]) == 1
    assert public["excluded_matches"][0]["task_id"] == "task-3"
    candidate = candidate_from_search(result, path)
    assert "Selected donors:" in candidate.evidence[0].notes
    assert "Excluded inconsistent donors:" in candidate.evidence[0].notes


def test_product_historical_repository_path_is_configurable(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    monkeypatch.delenv("AUREASIM_HISTORICAL_REPOSITORY", raising=False)
    assert server._historical_repository_path() == (
        tmp_path
        / "local_evidence"
        / "historical_tasks"
        / "historical_task_repository.json"
    ).resolve()

    monkeypatch.setenv(
        "AUREASIM_HISTORICAL_REPOSITORY",
        "local-evidence/tasks.json",
    )
    assert server._historical_repository_path() == (
        tmp_path / "local-evidence" / "tasks.json"
    ).resolve()


def test_published_synthetic_repository_is_executable():
    path = (
        Path(__file__).resolve().parents[1]
        / "local_evidence"
        / "historical_tasks"
        / "example_historical_task_repository.json"
    )
    result = search_repository(
        repository_path=path,
        project_path=path.parent,
        task_id="demo-target-verify-application",
        process_alias="DEMO_TARGET",
        process_id="demo-target-process",
        process_version="1",
    )
    public = public_search_result(result)
    assert public["sufficient"] is True
    assert len(public["matches"]) == 3
    assert public["process_families"] == 2
    assert public["combined_executions"] == 120
    assert all(item["score"] >= 0.70 for item in public["matches"])

    candidate = candidate_from_search(result, path)
    assert candidate.method.value == "historical_analogue"
    assert candidate.evidence[0].sample_size == 120
    assert candidate.distribution.empirical_quantiles == {
        "p10": 285.0,
        "p50": 510.0,
        "p90": 810.0,
    }
