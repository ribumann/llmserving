from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.persistence.db import get_db_session
from tests.support.demo_backend import FakeProvider, MemorySession, NoopPersistenceSession


def test_configuration_and_deployment_routes_follow_contract() -> None:
    app = create_app()
    session = MemorySession()
    session.seed_defaults()
    app.state.provider_adapter = FakeProvider(session)
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    client = TestClient(app)
    headers = {"X-Demo-User": "presenter@example.com"}

    model_response = client.post(
        "/environments/env-demo/model-configurations",
        headers=headers,
        json={
            "catalogEntryId": "qwen3-4b",
            "resolvedCheckpointRef": "Qwen/Qwen3-4B@main",
            "modelSettings": {"maxContextWindow": 8192},
        },
    )
    assert model_response.status_code == 201
    model_id = model_response.json()["modelConfigId"]
    assert str(UUID(model_id)) == model_id

    inference_response = client.post(
        "/environments/env-demo/inference-configurations",
        headers=headers,
        json={
            "engineId": "vllm",
            "servingSettings": {"gpu_memory_utilization": 0.9},
            "generationSettings": {"temperature": 0.2},
        },
    )
    assert inference_response.status_code == 201
    inference_id = inference_response.json()["inferenceConfigId"]
    assert str(UUID(inference_id)) == inference_id

    deploy_response = client.post(
        "/environments/env-demo/deployments",
        headers=headers,
        json={
            "modelConfigId": model_id,
            "inferenceConfigId": inference_id,
        },
    )
    assert deploy_response.status_code == 202
    assert deploy_response.json()["phase"] == "accepted"
    assert deploy_response.json()["lifecycleState"] == "deploying"

    get_response = client.get(
        "/environments/env-demo/deployments/env-demo-deployment-1",
        headers=headers,
    )
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["deploymentRevisionId"] == "env-demo-deployment-1"
    assert body["health"]["status"] == "healthy"

    history_response = client.get(
        "/environments/env-demo/model-configurations",
        headers=headers,
    )
    assert history_response.status_code == 200
    assert history_response.json()["items"][0]["modelConfigId"] == model_id


def test_deployment_requires_hf_token_for_gated_catalog_entry() -> None:
    app = create_app()
    session = MemorySession()
    session.seed_defaults()
    app.state.provider_adapter = FakeProvider(session)
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    client = TestClient(app)
    headers = {"X-Demo-User": "presenter@example.com"}

    model = client.post(
        "/environments/env-demo/model-configurations",
        headers=headers,
        json={
            "catalogEntryId": "llama-3.2-3b-instruct",
            "resolvedCheckpointRef": "meta-llama/Llama-3.2-3B-Instruct@main",
            "modelSettings": {},
        },
    )
    inference = client.post(
        "/environments/env-demo/inference-configurations",
        headers=headers,
        json={"engineId": "vllm", "servingSettings": {}, "generationSettings": {}},
    )

    response = client.post(
        "/environments/env-demo/deployments",
        headers=headers,
        json={
            "modelConfigId": model.json()["modelConfigId"],
            "inferenceConfigId": inference.json()["inferenceConfigId"],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "hf_token_required"
