from fastapi.testclient import TestClient

import server
from aureasim.expert_review import CandidateReviewLedger, save_review_files
from tests.test_expert_review import candidate_set


def test_candidate_review_api_round_trip(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    project = projects / "demo"
    project.mkdir(parents=True)
    items = candidate_set()
    save_review_files(
        project / "parameter_candidates.json",
        project / "candidate_review_ledger.json",
        items,
        CandidateReviewLedger(candidate_set_id=items.candidate_set_id),
    )
    monkeypatch.setattr(server, "PROJECTS_DIR", projects)
    client = TestClient(server.app)

    response = client.get("/api/projects/demo/parameter-candidates")
    assert response.status_code == 200
    assert response.json()["review_queue"][0]["confidence_grade"] == "low"

    identifier = items.candidates[0].candidate_id
    response = client.post(
        f"/api/projects/demo/parameter-candidates/{identifier}/review",
        json={
            "action": "accept",
            "reviewer_id": "expert-01",
            "justification": "Accepted after checking local operating practice.",
        },
    )
    assert response.status_code == 200
    assert response.json()["candidate"]["review_status"] == "accepted"

    audit = client.get("/api/projects/demo/parameter-candidates/audit")
    assert audit.status_code == 200
    assert len(audit.json()["events"]) == 1


def test_candidate_endpoint_reports_absent_package(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    (projects / "empty").mkdir(parents=True)
    monkeypatch.setattr(server, "PROJECTS_DIR", projects)
    response = TestClient(server.app).get("/api/projects/empty/parameter-candidates")
    assert response.status_code == 200
    assert response.json()["available"] is False

    imported = TestClient(server.app).post(
        "/api/projects/empty/parameter-candidates",
        json=candidate_set().model_dump(mode="json"),
    )
    assert imported.status_code == 201
    assert imported.json()["candidates"] == 1
    duplicate = TestClient(server.app).post(
        "/api/projects/empty/parameter-candidates",
        json=candidate_set().model_dump(mode="json"),
    )
    assert duplicate.status_code == 409
