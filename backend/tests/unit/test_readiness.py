from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from src.api.app import create_app
from src.config import Settings
from src.persistence.db import DatabaseReadiness


def test_liveness_does_not_depend_on_database() -> None:
    app = create_app()
    app.state.database_readiness.check = MagicMock(return_value=False)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "database_not_ready"
    app.state.database_readiness.check.assert_called_once_with()


def test_ready_requires_database_response() -> None:
    app = create_app()
    app.state.database_readiness.check = MagicMock(return_value=True)
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["database"] == "ready"
    assert response.headers["X-Request-ID"] == response.json()["requestId"]


def test_readiness_response_deadline_does_not_wait_for_slow_driver() -> None:
    app = create_app(Settings(database_readiness_timeout_seconds=0.05))
    release = threading.Event()
    started = threading.Event()

    def blocked_query():
        started.set()
        release.wait(timeout=2)
        return True

    app.state.database_readiness.check = blocked_query
    try:
        with TestClient(app) as client:
            start = time.monotonic()
            response = client.get("/readyz")
            elapsed = time.monotonic() - start
            assert started.is_set()
            assert response.status_code == 503
            assert elapsed < 0.5
            release.set()
    finally:
        release.set()


def test_probe_surfaces_driver_failure_without_leaking_credentials(caplog) -> None:
    probe = DatabaseReadiness(Settings())
    engine = MagicMock()
    engine.connect.side_effect = OperationalError(
        "SELECT 1", {}, Exception("password=do-not-log-this")
    )
    probe.close()
    probe._engine = engine
    assert probe.check() is False
    assert "OperationalError" in caplog.text
    assert "do-not-log-this" not in caplog.text


def test_probe_does_not_queue_a_second_database_call() -> None:
    probe = DatabaseReadiness(Settings())
    engine = MagicMock()
    probe.close()
    probe._engine = engine
    assert probe._lock.acquire(blocking=False)
    try:
        assert probe.check() is False
        engine.connect.assert_not_called()
    finally:
        probe._lock.release()
