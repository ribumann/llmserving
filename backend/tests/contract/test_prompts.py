from __future__ import annotations

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.persistence.db import get_db_session
from tests.support.demo_backend import FakeProvider, MemorySession, NoopPersistenceSession


def _build_client() -> tuple[TestClient, MemorySession]:
    app = create_app()
    session = MemorySession()
    session.seed_defaults()
    app.state.provider_adapter = FakeProvider(session)
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    return TestClient(app), session


def test_prompt_requires_ready_deployment() -> None:
    client, _session = _build_client()
    response = client.post(
        "/environments/env-demo/prompts",
        headers={"X-Demo-User": "presenter@example.com"},
        json={"prompt": "hello", "parameters": {}},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_ready_deployment"


def test_prompt_rejects_busy_environment() -> None:
    client, session = _build_client()
    environment = session.environments["env-demo"]
    environment.activeOperationId = "op-busy"
    response = client.post(
        "/environments/env-demo/prompts",
        headers={"X-Demo-User": "presenter@example.com"},
        json={"prompt": "hello", "parameters": {}},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "environment_busy"


def test_prompt_returns_ephemeral_response_payload() -> None:
    client, session = _build_client()
    headers = {"X-Demo-User": "presenter@example.com"}
    model = client.post(
        "/environments/env-demo/model-configurations",
        headers=headers,
        json={
            "catalogEntryId": "qwen3-4b",
            "resolvedCheckpointRef": "Qwen/Qwen3-4B@main",
            "modelSettings": {},
        },
    )
    inference = client.post(
        "/environments/env-demo/inference-configurations",
        headers=headers,
        json={"engineId": "vllm", "servingSettings": {}, "generationSettings": {}},
    )
    client.post(
        "/environments/env-demo/deployments",
        headers=headers,
        json={
            "modelConfigId": model.json()["modelConfigId"],
            "inferenceConfigId": inference.json()["inferenceConfigId"],
        },
    )

    response = client.post(
        "/environments/env-demo/prompts",
        headers=headers,
        json={"prompt": "Tell me a joke", "parameters": {"temperature": 0.1}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["responseText"] == "echo:Tell me a joke"
    assert body["timing"]["ttftMs"] == 10.0
    assert not hasattr(session, "prompt_records")
