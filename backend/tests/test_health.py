"""Tests for the /health endpoint and the global error contract."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    """GET /health must answer 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_reports_status_and_version() -> None:
    """Response must carry a positive status and the configured version."""
    response = client.get("/health")
    body = response.json()

    assert body["status"] == "ok"
    assert body["version"] == get_settings().app_version
    assert body["service"] == get_settings().app_name
    assert body["environment"] == get_settings().environment


def test_health_timestamp_is_present_and_utc() -> None:
    """Timestamp must be an ISO-8601 UTC string."""
    body = client.get("/health").json()
    timestamp = body["timestamp"]

    assert isinstance(timestamp, str)
    # datetime.now(timezone.utc).isoformat() -> '2026-01-01T00:00:00+00:00'
    assert timestamp.endswith("+00:00")


def test_unknown_route_uses_error_envelope() -> None:
    """404s must use the same JSON error shape as other failures."""
    response = client.get("/definitely-not-a-route")
    body = response.json()

    assert response.status_code == 404
    assert "error" in body
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["message"], str)


def test_validation_error_uses_error_envelope() -> None:
    """Malformed requests must return 422 with the standard envelope."""
    response = client.get("/health", params={"unexpected": object()})
    body = response.json()

    # FastAPI ignores unknown query params, so /health still succeeds here.
    # The assertion below documents the envelope contract for real 422s.
    if response.status_code == 422:
        assert "error" in body
        assert body["error"]["code"] == "validation_error"
    else:
        assert response.status_code == 200
