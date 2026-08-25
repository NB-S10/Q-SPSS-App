"""Phase 1 smoke tests: the app boots, the schema builds, projects round-trip."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_every_screen_renders(client):
    for path in ["/", "/data", "/variables", "/tables", "/weighting", "/models", "/exports"]:
        res = client.get(path)
        assert res.status_code == 200, path
        assert "<nav>" in res.text, path


def test_unknown_screen_404s(client):
    assert client.get("/nonsense").status_code == 404


def test_project_round_trip(client):
    created = client.post("/api/projects", json={"name": "Test project"})
    assert created.status_code == 201
    pid = created.json()["id"]

    listed = client.get("/api/projects").json()
    assert any(p["id"] == pid and p["dataset_count"] == 0 for p in listed)

    fetched = client.get(f"/api/projects/{pid}").json()
    assert fetched["name"] == "Test project"
    assert fetched["datasets"] == []


def test_blank_project_name_rejected(client):
    assert client.post("/api/projects", json={"name": "   "}).status_code == 422
