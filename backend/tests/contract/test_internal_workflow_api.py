from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.api.internal_auth import InternalCaller, require_internal_identity
from src.domain.enums import DemoEnvironmentState, WorkflowStatus
from src.persistence.db import get_db_session
from tests.support.demo_backend import MemorySession, NoopPersistenceSession


def _client() -> tuple[TestClient, MemorySession]:
    app = create_app()
    session = MemorySession()
    session.seed_defaults()
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None

    def override_db():
        yield session

    def override_internal_identity() -> InternalCaller:
        return InternalCaller(
            subject="durable-functions-app", app_id="test-app-id", audience="test"
        )

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[require_internal_identity] = override_internal_identity
    return TestClient(app), session


def test_internal_workflow_lifecycle_follows_contract() -> None:
    client, _session = _client()

    create_response = client.post(
        "/internal/workflows",
        json={
            "environmentId": "env-demo",
            "operationId": "op-provision-1",
            "workflowType": "provision",
        },
    )
    assert create_response.status_code == 201
    body = create_response.json()
    workflow_id = body["workflowId"]
    assert body["status"] == "running"
    assert body["environmentId"] == "env-demo"
    assert body["operationId"] == "op-provision-1"

    progress_response = client.patch(
        f"/internal/workflows/{workflow_id}",
        json={"phase": "applying-terraform", "diagnostics": {"resourcesApplied": 3}},
    )
    assert progress_response.status_code == 200
    assert progress_response.json()["phase"] == "applying-terraform"
    assert progress_response.json()["diagnostics"]["resourcesApplied"] == 3

    complete_response = client.post(
        f"/internal/workflows/{workflow_id}/complete",
        json={"status": "completed", "phase": "ready"},
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "completed"
    assert complete_response.json()["endedAt"] is not None


def test_create_workflow_requires_lock_not_already_held() -> None:
    client, session = _client()
    session.environments["env-demo"].activeOperationId = "op-existing"

    response = client.post(
        "/internal/workflows",
        json={
            "environmentId": "env-demo",
            "operationId": "op-new",
            "workflowType": "deploy",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "environment_locked"


def test_create_workflow_rejects_unknown_environment() -> None:
    client, _session = _client()

    response = client.post(
        "/internal/workflows",
        json={
            "environmentId": "env-does-not-exist",
            "operationId": "op-1",
            "workflowType": "provision",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "environment_not_found"


def test_progress_callback_rejects_hf_credential_payload() -> None:
    client, _session = _client()
    workflow_id = client.post(
        "/internal/workflows",
        json={"environmentId": "env-demo", "operationId": "op-2", "workflowType": "deploy"},
    ).json()["workflowId"]

    response = client.patch(
        f"/internal/workflows/{workflow_id}",
        json={"phase": "deploying", "diagnostics": {"huggingFaceToken": "hf_secret"}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "callback_payload_rejected"


def test_progress_callback_rejects_interactive_prompt_payload() -> None:
    client, _session = _client()
    workflow_id = client.post(
        "/internal/workflows",
        json={"environmentId": "env-demo", "operationId": "op-3", "workflowType": "deploy"},
    ).json()["workflowId"]

    response = client.patch(
        f"/internal/workflows/{workflow_id}",
        json={"phase": "deploying", "diagnostics": {"responseText": "some model output"}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "callback_payload_rejected"


def test_progress_callback_rejects_unknown_workflow() -> None:
    client, _session = _client()

    response = client.patch("/internal/workflows/unknown-workflow", json={"phase": "x"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "workflow_not_found"


def test_progress_callback_rejects_already_terminal_workflow() -> None:
    client, _session = _client()
    workflow_id = client.post(
        "/internal/workflows",
        json={"environmentId": "env-demo", "operationId": "op-4", "workflowType": "teardown"},
    ).json()["workflowId"]
    client.post(f"/internal/workflows/{workflow_id}/complete", json={"status": "completed"})

    response = client.patch(f"/internal/workflows/{workflow_id}", json={"phase": "too-late"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "workflow_not_running"


def test_complete_releases_environment_lock() -> None:
    client, session = _client()
    workflow_id = client.post(
        "/internal/workflows",
        json={"environmentId": "env-demo", "operationId": "op-5", "workflowType": "teardown"},
    ).json()["workflowId"]
    assert session.environments["env-demo"].activeOperationId == "op-5"

    client.post(f"/internal/workflows/{workflow_id}/complete", json={"status": "failed"})
    assert session.environments["env-demo"].activeOperationId is None


def test_complete_rejects_non_terminal_status() -> None:
    client, _session = _client()
    workflow_id = client.post(
        "/internal/workflows",
        json={"environmentId": "env-demo", "operationId": "op-6", "workflowType": "export"},
    ).json()["workflowId"]

    response = client.post(
        f"/internal/workflows/{workflow_id}/complete", json={"status": "running"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_terminal_status"


@pytest.mark.parametrize("owner", ["new-operation", None])
@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_stale_completion_rejects_before_reconciliation(owner: str | None, status: str) -> None:
    client, session = _client()
    workflow_id = client.post(
        "/internal/workflows",
        json={
            "environmentId": "env-demo",
            "operationId": "old-operation",
            "workflowType": "teardown",
        },
    ).json()["workflowId"]
    environment = session.environments["env-demo"]
    environment.activeOperationId = owner
    environment.lifecycleState = DemoEnvironmentState.READY
    provider_state = dict(environment.providerState or {})

    response = client.post(
        f"/internal/workflows/{workflow_id}/complete",
        json={"status": status, "phase": "late-completion", "diagnostics": {"late": True}},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "environment_locked"
    assert environment.activeOperationId == owner
    assert environment.lifecycleState == DemoEnvironmentState.READY
    assert environment.providerState == provider_state
    workflow = session.orchestration_workflows[workflow_id]
    assert workflow.status == WorkflowStatus.RUNNING
    assert workflow.phase == "accepted"
    assert workflow.diagnostics == {}
    assert workflow.endedAt is None


def test_cancel_ack_is_idempotent() -> None:
    client, _session = _client()
    workflow_id = client.post(
        "/internal/workflows",
        json={"environmentId": "env-demo", "operationId": "op-7", "workflowType": "export"},
    ).json()["workflowId"]

    first = client.post(f"/internal/workflows/{workflow_id}/cancel-ack")
    second = client.post(f"/internal/workflows/{workflow_id}/cancel-ack")
    assert first.status_code == 200
    assert second.status_code == 200


def test_internal_endpoints_reject_missing_bearer_auth() -> None:
    app = create_app()
    session = MemorySession()
    session.seed_defaults()
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None
    app.state.internal_token_validator = None  # unconfigured -> fails closed

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    client = TestClient(app)

    response = client.post(
        "/internal/workflows",
        json={"environmentId": "env-demo", "operationId": "op-1", "workflowType": "provision"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "internal_auth_unconfigured"
