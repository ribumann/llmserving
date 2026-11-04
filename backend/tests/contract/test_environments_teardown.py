from __future__ import annotations

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.persistence.db import get_db_session
from src.providers.base import TeardownHandle, TeardownPreview


class NoopPersistenceSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def add(self, _obj) -> None:
        return None

    def commit(self) -> None:
        return None

    def get(self, _model, _identifier):
        return None


class FakeSession:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class FakeProvider:
    def __init__(self) -> None:
        self.teardown_calls: list[tuple[str, str]] = []
        self.raise_on_teardown: Exception | None = None

    def teardownPreview(self, environmentId: str) -> TeardownPreview:
        if environmentId == "missing-env":
            raise LookupError(f"Environment '{environmentId}' was not found.")
        return TeardownPreview(
            environmentId=environmentId,
            previewToken=f"teardown-{environmentId}",
            resources=[{"type": "resourceGroup", "name": f"rg-llm-demo-{environmentId}"}],
            consequences=["Terraform destroy will remove every resource."],
        )

    def teardownEnvironment(self, environmentId: str, previewToken: str) -> TeardownHandle:
        self.teardown_calls.append((environmentId, previewToken))
        if self.raise_on_teardown is not None:
            raise self.raise_on_teardown
        return TeardownHandle(
            operationId="teardown-op-123",
            phase="accepted",
            state="tearing_down",
            diagnostics=[],
        )


def _client(monkeypatch, provider: FakeProvider, *, lock_side_effect=None) -> TestClient:
    app = create_app()
    app.state.provider_adapter = provider
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None

    def override_db():
        yield FakeSession()

    app.dependency_overrides[get_db_session] = override_db

    if lock_side_effect is None:
        monkeypatch.setattr(
            "src.api.routes.environments.EnvironmentLockService.acquire",
            lambda self, session, environment_id, operation_id: None,
        )
    else:
        monkeypatch.setattr(
            "src.api.routes.environments.EnvironmentLockService.acquire",
            lock_side_effect,
        )
    return TestClient(app)


def test_preview_teardown_returns_resources_and_preview_token(monkeypatch) -> None:
    provider = FakeProvider()
    client = _client(monkeypatch, provider)

    response = client.post(
        "/environments/env-123/teardown/preview",
        headers={"X-Demo-User": "presenter@example.com"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["environmentId"] == "env-123"
    assert body["previewToken"] == "teardown-env-123"
    assert body["resources"] == [{"type": "resourceGroup", "name": "rg-llm-demo-env-123"}]


def test_preview_teardown_returns_404_for_missing_environment(monkeypatch) -> None:
    provider = FakeProvider()
    client = _client(monkeypatch, provider)

    response = client.post(
        "/environments/missing-env/teardown/preview",
        headers={"X-Demo-User": "presenter@example.com"},
    )

    assert response.status_code == 404


def test_teardown_environment_returns_accepted_and_dispatches(monkeypatch) -> None:
    provider = FakeProvider()
    client = _client(monkeypatch, provider)

    response = client.post(
        "/environments/env-123/teardown",
        headers={"X-Demo-User": "presenter@example.com"},
        json={"previewToken": "teardown-env-123"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["operationId"] == "teardown-op-123"
    assert body["state"] == "tearing_down"
    assert provider.teardown_calls == [("env-123", "teardown-env-123")]


def test_teardown_environment_returns_409_when_locked(monkeypatch) -> None:
    from src.domain.environment_lock import EnvironmentLockedError

    def _locked(self, session, environment_id, operation_id):
        raise EnvironmentLockedError(environment_id, "op-existing")

    provider = FakeProvider()
    client = _client(monkeypatch, provider, lock_side_effect=_locked)

    response = client.post(
        "/environments/env-123/teardown",
        headers={"X-Demo-User": "presenter@example.com"},
        json={"previewToken": "teardown-env-123"},
    )

    assert response.status_code == 409
    assert provider.teardown_calls == []
