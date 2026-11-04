from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.persistence.db import get_db_session
from tests.support.demo_backend import FakeProvider, MemorySession, NoopPersistenceSession


@pytest.mark.integration
def test_deploy_prompt_and_redeploy_flow() -> None:
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

    model_v1 = client.post(
        "/environments/env-demo/model-configurations",
        headers=headers,
        json={
            "catalogEntryId": "qwen3-4b",
            "resolvedCheckpointRef": "Qwen/Qwen3-4B@main",
            "modelSettings": {"revisionLabel": "v1"},
        },
    ).json()
    inference_v1 = client.post(
        "/environments/env-demo/inference-configurations",
        headers=headers,
        json={
            "engineId": "vllm",
            "servingSettings": {"gpu_memory_utilization": 0.9},
            "generationSettings": {"temperature": 0.2},
        },
    ).json()
    deploy_v1 = client.post(
        "/environments/env-demo/deployments",
        headers=headers,
        json={
            "modelConfigId": model_v1["modelConfigId"],
            "inferenceConfigId": inference_v1["inferenceConfigId"],
        },
    ).json()
    assert deploy_v1["deploymentRevisionId"] == "env-demo-deployment-1"

    prompt_v1 = client.post(
        "/environments/env-demo/prompts",
        headers=headers,
        json={"prompt": "hello", "parameters": {}},
    ).json()
    assert prompt_v1["activeRevision"]["modelConfigId"] == model_v1["modelConfigId"]
    assert prompt_v1["activeRevision"]["inferenceConfigId"] == inference_v1["inferenceConfigId"]

    model_v2 = client.post(
        "/environments/env-demo/model-configurations",
        headers=headers,
        json={
            "catalogEntryId": "qwen3-4b",
            "resolvedCheckpointRef": "Qwen/Qwen3-4B@revision-2",
            "modelSettings": {"revisionLabel": "v2"},
        },
    ).json()
    prompt_still_old = client.post(
        "/environments/env-demo/prompts",
        headers=headers,
        json={"prompt": "still old?", "parameters": {}},
    ).json()
    assert prompt_still_old["activeRevision"]["modelConfigId"] == model_v1["modelConfigId"]

    deploy_v2 = client.post(
        "/environments/env-demo/deployments",
        headers=headers,
        json={
            "modelConfigId": model_v2["modelConfigId"],
            "inferenceConfigId": inference_v1["inferenceConfigId"],
        },
    ).json()
    assert deploy_v2["deploymentRevisionId"] == "env-demo-deployment-2"

    prompt_v2 = client.post(
        "/environments/env-demo/prompts",
        headers=headers,
        json={"prompt": "new model?", "parameters": {}},
    ).json()
    assert prompt_v2["activeRevision"]["modelConfigId"] == model_v2["modelConfigId"]
    assert (
        session.deployment_revisions["env-demo-deployment-1"].lifecycleState.value == "superseded"
    )
