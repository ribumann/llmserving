"""Unit tests for T140's dispatch-based `AzureProvisioner`/`AzureDeployer`
(backend/src/providers/azure/provision.py, deploy.py). Terraform apply/destroy
and the vLLM engine no longer run in-process here - both are dispatched
elsewhere (jobs/terraform_runner, jobs/model_deployment) and monitored via the
Durable Functions orchestration app, so these tests assert on dispatch calls
and on-failure domain-state transitions rather than on subprocess output.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from src.api.routes.environments import _generate_admin_ssh_keypair
from src.config import Settings
from src.domain.enums import DemoEnvironmentState, ProviderType, WorkflowStatus, WorkflowType
from src.domain.environment import DemoEnvironment
from src.providers.azure.container_jobs import JobDispatchResult
from src.providers.azure.deploy import AzureDeployer, DeploymentContext
from src.providers.azure.provision import AzureProvisioner, ProvisioningContext
from src.providers.azure.state import AzureEnvironmentStateService
from tests.support.demo_backend import MemorySession, MemorySessionContext


def _session_factory(session: MemorySession):
    return lambda: MemorySessionContext(session)


@pytest.fixture
def session() -> MemorySession:
    memory_session = MemorySession()
    memory_session.seed_defaults()
    return memory_session


class FakeFunctionsClient:
    """Records every start_orchestration() call; optionally raises to exercise
    the dispatch-failure path."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._raises = raises

    def __enter__(self) -> FakeFunctionsClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None

    def start_orchestration(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return "durable-instance-1"


def test_provisioner_dispatches_orchestration_and_persists_terraform_variables(
    session: MemorySession,
) -> None:
    functions_client = FakeFunctionsClient()
    provisioner = AzureProvisioner(
        session_factory=_session_factory(session),
        settings=Settings(),
        functions_client_factory=lambda: functions_client,
    )
    context = ProvisioningContext(
        environmentId="env-demo",
        operationId="op-provision-1",
        actorEmail="presenter@example.com",
        region="eastus2",
        profileId="azure-single-gpu-3b",
        profileSizeClass="small",
        vmSize="Standard_NC16as_T4_v3",
        bootstrapModelRepo="Qwen/Qwen3-4B",
        terraformVariables={"subscription_id": "sub-123", "environment_id": "env-demo"},
        fallbackRegions=["eastus2", "westus3"],
    )
    session.environments["env-demo"].activeOperationId = None

    provisioner._run(context)

    assert len(functions_client.calls) == 1
    call = functions_client.calls[0]
    assert call["workflow_type"] == "provision"
    assert call["job_input"]["action"] == "apply"
    assert call["job_input"]["terraformVariables"] == context.terraformVariables

    environment = session.environments["env-demo"]
    assert environment.lifecycleState == DemoEnvironmentState.PROVISIONING
    assert environment.providerState["terraform"]["variables"] == context.terraformVariables

    [workflow] = session.orchestration_workflows.values()
    assert workflow.workflowType == WorkflowType.PROVISION
    assert workflow.diagnostics["region"] == "eastus2"
    assert workflow.diagnostics["fallbackRegions"] == ["eastus2", "westus3"]


def test_provisioner_marks_environment_failed_when_dispatch_raises(
    session: MemorySession,
) -> None:
    functions_client = FakeFunctionsClient(raises=RuntimeError("orchestration unreachable"))
    provisioner = AzureProvisioner(
        session_factory=_session_factory(session),
        settings=Settings(),
        functions_client_factory=lambda: functions_client,
    )
    context = ProvisioningContext(
        environmentId="env-demo",
        operationId="op-provision-2",
        actorEmail="presenter@example.com",
        region="eastus2",
        profileId="azure-single-gpu-3b",
        profileSizeClass="small",
        vmSize="Standard_NC16as_T4_v3",
        bootstrapModelRepo="Qwen/Qwen3-4B",
        terraformVariables={"subscription_id": "sub-123"},
        fallbackRegions=["eastus2"],
    )
    session.environments["env-demo"].activeOperationId = None

    provisioner._run(context)

    environment = session.environments["env-demo"]
    assert environment.lifecycleState == DemoEnvironmentState.PROVISIONING_FAILED
    assert environment.activeOperationId is None

    [workflow] = session.orchestration_workflows.values()
    assert workflow.status == WorkflowStatus.FAILED
    assert "orchestration unreachable" in workflow.diagnostics["error"]


def test_start_teardown_reuses_persisted_terraform_variables(session: MemorySession) -> None:
    functions_client = FakeFunctionsClient()
    provisioner = AzureProvisioner(
        session_factory=_session_factory(session),
        settings=Settings(),
        functions_client_factory=lambda: functions_client,
    )
    environment = session.environments["env-demo"]
    environment.providerState = {
        **environment.providerState,
        "terraform": {"variables": {"subscription_id": "sub-123", "environment_id": "env-demo"}},
    }
    environment.activeOperationId = None

    provisioner._run_teardown("env-demo", "op-teardown-1", "presenter@example.com")

    assert len(functions_client.calls) == 1
    call = functions_client.calls[0]
    assert call["workflow_type"] == "teardown"
    assert call["job_input"]["action"] == "destroy"
    assert call["job_input"]["terraformVariables"] == {
        "subscription_id": "sub-123",
        "environment_id": "env-demo",
    }
    assert environment.lifecycleState == DemoEnvironmentState.TEARING_DOWN


def test_start_teardown_fails_cleanly_without_persisted_variables(
    session: MemorySession,
) -> None:
    """An environment that never completed a successful apply through this
    provisioner has no persisted terraformVariables to reuse for `terraform
    destroy` - this must surface as a normal failed-workflow-style state
    transition rather than an unhandled exception reaching the caller."""
    functions_client = FakeFunctionsClient()
    provisioner = AzureProvisioner(
        session_factory=_session_factory(session),
        settings=Settings(),
        functions_client_factory=lambda: functions_client,
    )
    environment = session.environments["env-demo"]
    environment.providerState = {}
    environment.activeOperationId = None

    provisioner._run_teardown("env-demo", "op-teardown-2", "presenter@example.com")

    assert functions_client.calls == []
    environment = session.environments["env-demo"]
    assert environment.lifecycleState == DemoEnvironmentState.TEARDOWN_FAILED
    diagnostics = environment.providerState["currentOperation"]["diagnostics"]
    assert any("no persisted Terraform variables" in message for message in diagnostics)


class FakeJobDispatcher:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self._raises = raises

    def __call__(
        self, resource_group: str, job_name: str, env_overrides: dict[str, str]
    ) -> JobDispatchResult:
        self.calls.append((resource_group, job_name, env_overrides))
        if self._raises is not None:
            raise self._raises
        return JobDispatchResult(execution_name="model-deployment-exec-1")


def _deployment_revision(session: MemorySession):
    from src.domain.deployment_revision import DeploymentRevision
    from src.domain.enums import DeploymentRevisionState

    revision = DeploymentRevision(
        deploymentRevisionId="revision-1",
        environmentId="env-demo",
        modelConfigId="model-config-1",
        inferenceConfigId="inference-config-1",
        engineId="vllm",
        lifecycleState=DeploymentRevisionState.PENDING,
        health={"status": "unknown", "diagnostics": []},
        activePeriod={},
    )
    session.add(revision)
    return revision


def test_deployer_dispatches_job_then_starts_orchestration(session: MemorySession) -> None:
    _deployment_revision(session)
    functions_client = FakeFunctionsClient()
    job_dispatcher = FakeJobDispatcher()
    deployer = AzureDeployer(
        session_factory=_session_factory(session),
        settings=Settings(
            container_apps_resource_group="rg-container-apps",
            job_name_model_deployment="model-deployment",
        ),
        functions_client_factory=lambda: functions_client,
        job_dispatcher=job_dispatcher,
    )
    context = DeploymentContext(
        environmentId="env-demo",
        deploymentRevisionId="revision-1",
        operationId="op-deploy-1",
        actorEmail="presenter@example.com",
        engineId="vllm",
        modelConfig={"resolvedCheckpointRef": "Qwen/Qwen3-4B"},
        inferenceConfig={},
        targetEnvironment={},
        hfToken="hf-token-value",
    )
    session.environments["env-demo"].activeOperationId = None

    deployer._run(context)

    assert len(job_dispatcher.calls) == 1
    resource_group, job_name, env_overrides = job_dispatcher.calls[0]
    assert resource_group == "rg-container-apps"
    assert job_name == "model-deployment"
    job_input = json.loads(env_overrides["JOB_INPUT_JSON"])
    assert job_input["environmentId"] == "env-demo"
    assert job_input["modelRepo"] == "Qwen/Qwen3-4B"
    assert job_input["hfToken"] == "hf-token-value"

    assert len(functions_client.calls) == 1
    call = functions_client.calls[0]
    assert call["workflow_type"] == "deploy"
    assert call["pre_dispatched_execution_name"] == "model-deployment-exec-1"

    [workflow] = session.orchestration_workflows.values()
    assert workflow.diagnostics["deploymentRevisionId"] == "revision-1"


def test_deployer_prefers_hugging_face_repo_id_over_resolved_checkpoint_ref(
    session: MemorySession,
) -> None:
    """Regression test for the "vLLM never came up" production bug: the job
    must load the real Hugging Face repo id via `--model`, while the (often
    "main") `resolvedCheckpointRef` is only forwarded as `--revision`. Passing
    "main" alone as `--model` caused every deployment carrying only a
    `resolvedCheckpointRef` (and no repo id) to fail because "main" is not a
    valid Hugging Face repo.
    """
    _deployment_revision(session)
    functions_client = FakeFunctionsClient()
    job_dispatcher = FakeJobDispatcher()
    deployer = AzureDeployer(
        session_factory=_session_factory(session),
        settings=Settings(
            container_apps_resource_group="rg-container-apps",
            job_name_model_deployment="model-deployment",
        ),
        functions_client_factory=lambda: functions_client,
        job_dispatcher=job_dispatcher,
    )
    context = DeploymentContext(
        environmentId="env-demo",
        deploymentRevisionId="revision-1",
        operationId="op-deploy-1",
        actorEmail="presenter@example.com",
        engineId="vllm",
        modelConfig={
            "huggingFaceRepoId": "Qwen/Qwen3-4B",
            "resolvedCheckpointRef": "main",
        },
        inferenceConfig={},
        targetEnvironment={},
        hfToken="hf-token-value",
    )
    session.environments["env-demo"].activeOperationId = None

    deployer._run(context)

    job_input = json.loads(job_dispatcher.calls[0][2]["JOB_INPUT_JSON"])
    assert job_input["modelRepo"] == "Qwen/Qwen3-4B"
    assert job_input["revision"] == "main"


def test_deployer_marks_revision_failed_when_job_dispatch_raises(
    session: MemorySession,
) -> None:
    from src.domain.enums import DeploymentRevisionState

    _deployment_revision(session)
    functions_client = FakeFunctionsClient()
    job_dispatcher = FakeJobDispatcher(raises=RuntimeError("job start failed"))
    deployer = AzureDeployer(
        session_factory=_session_factory(session),
        settings=Settings(
            container_apps_resource_group="rg-container-apps",
            job_name_model_deployment="model-deployment",
        ),
        functions_client_factory=lambda: functions_client,
        job_dispatcher=job_dispatcher,
    )
    context = DeploymentContext(
        environmentId="env-demo",
        deploymentRevisionId="revision-1",
        operationId="op-deploy-2",
        actorEmail="presenter@example.com",
        engineId="vllm",
        modelConfig={"resolvedCheckpointRef": "Qwen/Qwen3-4B"},
        inferenceConfig={},
        targetEnvironment={},
        hfToken="hf-token-value",
    )
    session.environments["env-demo"].activeOperationId = None

    deployer._run(context)

    assert functions_client.calls == []
    revision = session.deployment_revisions["revision-1"]
    assert revision.lifecycleState == DeploymentRevisionState.DEPLOYMENT_FAILED
    assert revision.health["status"] == "unhealthy"

    [workflow] = session.orchestration_workflows.values()
    assert workflow.status == WorkflowStatus.FAILED
    assert session.environments["env-demo"].activeOperationId is None


def test_generate_admin_ssh_keypair_produces_rsa_key() -> None:
    """Azure's admin_ssh_key resource only accepts RSA keys and rejects ed25519
    keys (regression test for bug #9)."""
    public_key, private_key_pem = _generate_admin_ssh_keypair()

    assert public_key.startswith("ssh-rsa ")

    loaded_key = serialization.load_ssh_private_key(private_key_pem.encode(), password=None)
    assert isinstance(loaded_key, rsa.RSAPrivateKey)


def test_state_service_reads_vm_power_state(monkeypatch, tmp_path) -> None:
    working_dir = tmp_path / "env-demo"
    working_dir.mkdir(parents=True, exist_ok=True)
    environment = DemoEnvironment(
        environmentId="env-demo",
        profileId="azure-single-gpu-3b",
        provider=ProviderType.AZURE,
        region="eastus2",
        regionRecommendation=None,
        lifecycleState=DemoEnvironmentState.READY,
        activeDeploymentRevisionId=None,
        providerState={
            "resourceGroupName": "rg-llmserving-env-demo",
            "vmName": "llmserving-env-demo-vm",
            "terraform": {"workingDirectory": str(working_dir)},
        },
        createdBy="presenter@example.com",
        lastModifiedBy="presenter@example.com",
    )
    session = MemorySession()
    session.environments["env-demo"] = environment
    compute_client = SimpleNamespace(
        virtual_machines=SimpleNamespace(
            instance_view=lambda resource_group, vm_name: SimpleNamespace(
                statuses=[SimpleNamespace(code="PowerState/running")]
            )
        )
    )
    monkeypatch.setattr(
        "src.providers.azure.state.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"public_ip_address": {"value": "1.2.3.4"}}),
            stderr="",
        ),
    )

    service = AzureEnvironmentStateService(
        session_factory=lambda: MemorySessionContext(session),
        settings=Settings(azure_subscription_id="sub-123"),
        compute_client=compute_client,
    )

    state = service.getEnvironmentState("env-demo")

    assert state.lifecycleState == "ready"
    assert state.context["resourceState"] == "running"
    assert state.providerState["public_ip_address"] == "1.2.3.4"
