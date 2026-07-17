from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ingest.project_a.api import configure_service, router
from ingest.project_a.config import ProjectAConfig
from ingest.project_a.service import ProjectAIngestService

from .test_session_2_project_a_runtime import ready, wire


ROOT = Path(__file__).resolve().parents[1]


def build_client(tmp_path, *, max_body=262_144, v1_enabled=False,
                 at=datetime(2026, 7, 16, 0, 0, 5, tzinfo=timezone.utc)):
    config = ProjectAConfig(
        database_path=tmp_path / "api.db",
        max_body_bytes=max_body,
        v1_ingest_enabled=v1_enabled,
    )
    service = ProjectAIngestService(
        config, clock=lambda: at)
    configure_service(service)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), service


def test_strict_endpoint_accepts_json_and_health_is_separate(tmp_path):
    client, _ = build_client(tmp_path)
    response = client.post("/project-a/v0.2/events", content=wire(ready()),
                           headers={"content-type": "application/json"})
    assert response.status_code == 202 and response.json()["result_code"] == "ACCEPTED"
    assert client.get("/project-a/v0.2/health/live").status_code == 200
    ready_response = client.get("/project-a/v0.2/health/ready")
    assert ready_response.status_code == 200 and ready_response.json()["schema_ready"] is True


def test_method_content_type_and_oversize_are_deterministic(tmp_path):
    client, service = build_client(tmp_path, max_body=32)
    assert client.get("/project-a/v0.2/events").status_code == 405
    media = client.post("/project-a/v0.2/events", content=b"{}",
                        headers={"content-type": "text/plain"})
    assert media.status_code == 415 and media.json()["result_code"] == "CONTENT_TYPE_UNSUPPORTED"
    large = client.post("/project-a/v0.2/events", content=b"{" + b"x" * 100,
                        headers={"content-type": "application/json"})
    assert large.status_code == 413 and large.json()["result_code"] == "BODY_TOO_LARGE"
    with service.db.connect() as conn:
        row = conn.execute(
            "SELECT raw_complete,body_bytes FROM project_a_raw_receipts ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    assert row["raw_complete"] == 0 and row["body_bytes"] == 33


def test_legacy_and_project_a_routes_coexist_without_fallback():
    from ingest.webhook_server import app
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/project-a/v0.2/health/live").status_code == 200
    assert client.get("/project-a/v0.2/events").status_code == 405


def test_v1_endpoint_is_disabled_by_default_and_can_be_explicitly_test_enabled(tmp_path):
    vector = json.loads(
        (ROOT / "fixtures/project_a/event_v1_known_vectors.json").read_text(
            encoding="utf-8"
        )
    )["documents"]["rejection_ready"]
    body = json.dumps(vector, separators=(",", ":")).encode()
    disabled, _ = build_client(
        tmp_path / "disabled",
        at=datetime(2026, 7, 16, 1, 1, 2, tzinfo=timezone.utc),
    )
    response = disabled.post(
        "/project-a/v1/events",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 503
    assert response.json()["result_code"] == "V1_INGEST_DISABLED"

    enabled, _ = build_client(
        tmp_path / "enabled",
        v1_enabled=True,
        at=datetime(2026, 7, 16, 1, 1, 2, tzinfo=timezone.utc),
    )
    accepted = enabled.post(
        "/project-a/v1/events",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert accepted.status_code == 202
    assert accepted.json()["result_code"] == "ACCEPTED"
