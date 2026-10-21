from fastapi.testclient import TestClient

from atlas.app import app
from atlas.domain import analyze
from atlas.store import Store


def test_workflow_and_session_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DB_PATH", str(tmp_path / "atlas.db"))
    with TestClient(app) as first:
        landing = first.get("/")
        assert "HttpOnly" in landing.headers["set-cookie"]
        response = first.get("/api/workspace")
        assert response.status_code == 200
        incident_id = response.json()["incidents"][0]["id"]
        saved = first.post(f"/api/incidents/{incident_id}/review", json={"state": "investigating", "note": "Checked pool metrics; still need query traces."})
        assert saved.status_code == 200
        assert saved.json()["state"] == "investigating"
        assert len(saved.json()["events"]) == 2
        assert first.get("/api/workspace").json()["incidents"][0]["state"] == "investigating"
        with TestClient(app) as second:
            assert second.get(f"/api/incidents/{incident_id}").status_code == 404
            assert second.post(f"/api/incidents/{incident_id}/review", json={"state": "resolved"}).status_code == 404
        healthy = first.post("/api/exercises", json={"scenario": "healthy", "seed": 42})
        assert healthy.status_code == 201 and healthy.json()["incidents"] == []


def test_invalid_inputs_and_cross_origin_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DB_PATH", str(tmp_path / "atlas.db"))
    with TestClient(app) as client:
        assert client.post("/api/exercises", json={"scenario": "arbitrary-shell-command"}).status_code == 422
        assert client.post("/api/exercises", json={"scenario": "healthy", "seed": -1}).status_code == 422
        assert client.post("/api/exercises", json={"scenario": "healthy"}, headers={"Origin": "https://other.example"}).status_code == 403
        assert client.post("/api/exercises", content="a" * 20_000).status_code == 413
        assert client.get("/api/incidents/unknown").status_code == 404


def test_persistence_and_retention(tmp_path):
    path = str(tmp_path / "atlas.db")
    store = Store(path)
    result = store.create_run("session-a", analyze("database-pressure"))
    incident_id = result["incidents"][0]["id"]
    store.review("session-a", incident_id, "resolved", "Synthetic investigation complete")
    reopened = Store(path)
    assert reopened.incident("session-a", incident_id)["state"] == "resolved"
    assert reopened.incident("session-b", incident_id) is None
    for _ in range(13):
        reopened.create_run("session-a", analyze("healthy"))
    assert reopened.incident("session-a", incident_id) is None


def test_local_links_and_security_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DB_PATH", str(tmp_path / "atlas.db"))
    with TestClient(app) as client:
        for path in ("/", "/docs", "/static/docs.js", "/static/style.css", "/static/app.js", "/healthz", "/api/scenarios", "/openapi.json"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert len(client.get("/api/scenarios").json()) == 4
        assert "cdnjs" not in client.get("/docs").text
