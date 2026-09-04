import json

from fastapi.testclient import TestClient

import server


def test_project_detail_reads_legacy_offline_scenario_config(monkeypatch, tmp_path):
    """Projects written by older offline demos still show their scenarios."""
    project_path = tmp_path / "demo"
    project_path.mkdir()
    (project_path / "project_config.json").write_text(
        json.dumps({"scenarios": [{"name": "A_Baseline"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "PROJECTS_DIR", tmp_path)

    response = TestClient(server.app).get("/api/projects/demo")

    assert response.status_code == 200
    assert response.json()["exp_params"]["scenarios"] == [{"name": "A_Baseline"}]
