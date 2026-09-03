from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import SPAStaticFiles


def test_frontend_route_serves_spa_index_but_missing_assets_stay_404(tmp_path):
    (tmp_path / "index.html").write_text("<html>SPA shell</html>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")

    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=str(tmp_path), html=True), name="frontend")
    client = TestClient(app)

    route = client.get(
        "/projects/RES_Installation_Process-10",
        headers={"Accept": "text/html"},
    )
    assert route.status_code == 200
    assert "SPA shell" in route.text

    assert client.get(
        "/assets/missing.js",
        headers={"Accept": "text/html"},
    ).status_code == 404

    assert client.get(
        "/api/missing",
        headers={"Accept": "text/html"},
    ).status_code == 404
