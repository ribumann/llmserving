"""Integration test for T144: exercises `AzureProvisioner.provisionEnvironment`'s
full asynchronous flow end-to-end - the environment is put into `PROVISIONING`
and exactly one `Orchestration Workflow` is created and dispatched via Durable
Functions, but the environment only ever resolves to `READY`/
`PROVISIONING_FAILED` when the real `/internal/workflows/{id}/complete` HTTP
route (internal_workflows.py) is called back, exercising the actual
`WorkflowReconciliationService` - never by this test (or anything else)
polling Terraform/the job directly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.api.internal_auth import InternalCaller, require_internal_identity
from src.config import Settings
from src.domain.enums import DemoEnvironmentState
from src.persistence.db import get_db_session
from src.providers.azure.provision import AzureProvisioner, ProvisioningContext
from tests.support.demo_backend import MemorySession, MemorySessionContext, NoopPersistenceSession


def _session_factory(session: MemorySession):
    return lambda: MemorySessionContext(session)


class RecordingFunctionsClient:
    """Stands in for the real Durable Functions HTTP starter - records the
    dispatch call instead of making a real network call, since the actual
    Terraform apply/callback round trip only happens against real Azure
    infrastructure."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __enter__(self) -> RecordingFunctionsClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None

    def start_orchestration(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "durable-instance-t144"


def _provision_context(operation_id: str) -> ProvisioningContext:
    return ProvisioningContext(
        environmentId="env-demo",
        operationId=operation_id,
        actorEmail="presenter@example.com",
        region="eastus2",
        profileId="azure-single-gpu-3b",
        profileSizeClass="small",
        vmSize="Standard_NC16as_T4_v3",
        bootstrapModelRepo="Qwen/Qwen3-4B",
        terraformVariables={"subscription_id": "sub-123", "environment_id": "env-demo"},
        fallbackRegions=["eastus2", "westus3"],
    )


def _internal_client(session: MemorySession) -> TestClient:
    app = create_app()
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
    return TestClient(app)


@pytest.mark.integration
def test_provision_environment_resolves_ready_only_via_completion_callback() -> None:
    session = MemorySession()
    session.seed_defaults()
    session.environments["env-demo"].activeOperationId = None

    functions_client = RecordingFunctionsClient()
    provisioner = AzureProvisioner(
        session_factory=_session_factory(session),
        settings=Settings(),
        functions_client_factory=lambda: functions_client,
    )

    provisioner._run(_provision_context("op-t144-provision-ok"))

    # provisionEnvironment's dispatch put the environment into PROVISIONING and
    # created exactly one Orchestration Workflow - it did not (and cannot)
    # resolve the environment synchronously, since the real apply runs
    # out-of-process in jobs/terraform_runner.
    assert len(functions_client.calls) == 1
    assert functions_client.calls[0]["workflow_type"] == "provision"
    [workflow] = session.orchestration_workflows.values()
    environment = session.environments["env-demo"]
    assert environment.lifecycleState == DemoEnvironmentState.PROVISIONING

    client = _internal_client(session)
    complete_response = client.post(
        f"/internal/workflows/{workflow.workflowId}/complete",
        json={
            "status": "completed",
            "phase": "ready",
            "diagnostics": {
                "outputs": {
                    "resource_group_name": {"value": "rg-llmserving-env-demo"},
                    "vm_name": {"value": "llmserving-env-demo-vm"},
                    "private_ip_address": {"value": "10.0.0.5"},
                    "vllm_endpoint": {"value": "http://10.0.0.5:8000"},
                }
            },
        },
    )

    assert complete_response.status_code == 200
    environment = session.environments["env-demo"]
    assert environment.lifecycleState == DemoEnvironmentState.READY
    assert environment.providerState["resourceGroupName"] == "rg-llmserving-env-demo"
    assert environment.providerState["vllmEndpoint"] == "http://10.0.0.5:8000"
    assert environment.providerState["inferenceApiUrl"] == "http://10.0.0.5:8000"
    assert environment.activeOperationId is None


@pytest.mark.integration
def test_provision_environment_resolves_failed_only_via_completion_callback() -> None:
    session = MemorySession()
    session.seed_defaults()
    session.environments["env-demo"].activeOperationId = None

    functions_client = RecordingFunctionsClient()
    provisioner = AzureProvisioner(
        session_factory=_session_factory(session),
        settings=Settings(),
        functions_client_factory=lambda: functions_client,
    )

    provisioner._run(_provision_context("op-t144-provision-failed"))
    [workflow] = session.orchestration_workflows.values()
    assert session.environments["env-demo"].lifecycleState == DemoEnvironmentState.PROVISIONING

    client = _internal_client(session)
    complete_response = client.post(
        f"/internal/workflows/{workflow.workflowId}/complete",
        json={
            "status": "failed",
            "phase": "failed",
            "diagnostics": {
                "error": "AllocationFailed: no capacity in this region",
                "region": "eastus2",
                "fallbackRegions": ["eastus2", "westus3"],
            },
        },
    )

    assert complete_response.status_code == 200
    environment = session.environments["env-demo"]
    assert environment.lifecycleState == DemoEnvironmentState.PROVISIONING_FAILED
    assert environment.activeOperationId is None
    diagnostics = environment.providerState["currentOperation"]["diagnostics"]
    assert any("fallback regions: westus3" in message.lower() for message in diagnostics)
