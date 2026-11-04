from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.enums import DemoEnvironmentState, ProviderType
from src.domain.environment import DemoEnvironment
from src.persistence.db import get_db_session


class FakeScalars:
    def __init__(self, rows: list[DemoEnvironment]) -> None:
        self._rows = rows

    def all(self) -> list[DemoEnvironment]:
        return self._rows


class FakeResult:
    def __init__(self, rows: list[DemoEnvironment]) -> None:
        self._rows = rows

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._rows)


class FakeSession:
    def __init__(self, rows: list[DemoEnvironment]) -> None:
        self._rows = rows

    def execute(self, _stmt) -> FakeResult:
        return FakeResult(self._rows)


def _environment(
    environment_id: str,
    *,
    state: DemoEnvironmentState = DemoEnvironmentState.READY,
) -> DemoEnvironment:
    now = datetime(2026, 8, 19, tzinfo=UTC)
    return DemoEnvironment(
        environmentId=environment_id,
        profileId="azure-single-gpu-3b",
        provider=ProviderType.AZURE,
        region="eastus2",
        lifecycleState=state,
        providerState={},
        createdBy="presenter@example.com",
        lastModifiedBy="presenter@example.com",
        createdAt=now,
        updatedAt=now,
    )


def _client(rows: list[DemoEnvironment]) -> TestClient:
    app = create_app()
    app.state.provider_adapter = None
    app.state.session_factory = None
    app.state.telemetry = None

    def override_db():
        yield FakeSession(rows)

    app.dependency_overrides[get_db_session] = override_db
    return TestClient(app)


def test_list_environments_returns_summaries() -> None:
    rows = [
        _environment("env-123", state=DemoEnvironmentState.READY),
        _environment("env-456", state=DemoEnvironmentState.PROVISIONING),
    ]
    client = _client(rows)

    response = client.get(
        "/environments",
        headers={"X-Demo-User": "presenter@example.com"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [entry["environmentId"] for entry in body["environments"]] == [
        "env-123",
        "env-456",
    ]
    assert body["environments"][0]["lifecycleState"] == "ready"
    assert body["environments"][0]["profileId"] == "azure-single-gpu-3b"
    assert body["environments"][1]["lifecycleState"] == "provisioning"


def test_list_environments_returns_empty_list_when_none_exist() -> None:
    client = _client([])

    response = client.get(
        "/environments",
        headers={"X-Demo-User": "presenter@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["environments"] == []
