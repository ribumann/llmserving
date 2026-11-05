from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from src.config import Settings
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    DemoEnvironmentState,
    DeploymentRevisionState,
    WorkflowStatus,
    WorkflowType,
)
from src.domain.orchestration_workflow_service import OrchestrationWorkflowService
from src.providers.azure.deploy import AzureDeployer, DeploymentContext
from src.providers.azure.provision import AzureProvisioner
from tests.support.demo_backend import MemorySession, MemorySessionContext


@pytest.fixture
def session() -> MemorySession:
    session = MemorySession()
    session.seed_defaults()
    session.add(
        DeploymentRevision(
            deploymentRevisionId="revision-1",
            environmentId="env-demo",
            modelConfigId="model-config-1",
            inferenceConfigId="inference-config-1",
            engineId="vllm",
            lifecycleState=DeploymentRevisionState.PENDING,
            health={"status": "unknown", "diagnostics": []},
            activePeriod={},
        )
    )
    return session


def _cleanup(session: MemorySession, kind: str, workflow_id: str | None, telemetry) -> None:
    def factory():
        return MemorySessionContext(session)

    if kind == "deploy":
        deployer = AzureDeployer(session_factory=factory, settings=Settings(), telemetry=telemetry)
        deployer._fail(
            DeploymentContext(
                environmentId="env-demo",
                deploymentRevisionId="revision-1",
                operationId="old-operation",
                actorEmail="cleanup@example.com",
                engineId="vllm",
                modelConfig={},
                inferenceConfig={},
                targetEnvironment={},
            ),
            workflow_id=workflow_id,
            error=RuntimeError("dispatch failed"),
        )
    else:
        provisioner = AzureProvisioner(
            session_factory=factory, settings=Settings(), telemetry=telemetry
        )
        provisioner._fail_dispatch(
            environment_id="env-demo",
            operation_id="old-operation",
            actor_email="cleanup@example.com",
            lifecycle_state=(
                DemoEnvironmentState.PROVISIONING_FAILED
                if kind == "provision"
                else DemoEnvironmentState.TEARDOWN_FAILED
            ),
            workflow_id=workflow_id,
            telemetry_phase=kind,
            error=RuntimeError("dispatch failed"),
        )


@pytest.mark.parametrize("kind", ["provision", "teardown", "deploy"])
@pytest.mark.parametrize("workflow_state", ["none", "running", "terminal", "missing"])
@pytest.mark.parametrize("owner", ["old-operation", "new-operation", None])
def test_dispatch_failure_cleanup_requires_current_ownership(
    session, kind, workflow_state, owner, caplog
) -> None:
    workflow = None
    workflow_id = None
    if workflow_state in {"running", "terminal"}:
        workflow = OrchestrationWorkflowService().create_workflow(
            session,
            environment_id="env-demo",
            operation_id="old-operation",
            workflow_type=WorkflowType.DEPLOY if kind == "deploy" else WorkflowType.PROVISION,
        )
        workflow_id = workflow.workflowId
        if workflow_state == "terminal":
            workflow.status = WorkflowStatus.COMPLETED
    elif workflow_state == "missing":
        workflow_id = "missing-workflow"
    environment = session.environments["env-demo"]
    environment.activeOperationId = owner
    revision = session.get(DeploymentRevision, "revision-1")
    before = (
        environment.lifecycleState,
        deepcopy(environment.providerState),
        environment.lastModifiedBy,
        revision.lifecycleState,
        deepcopy(revision.health),
    )
    telemetry = MagicMock()

    _cleanup(session, kind, workflow_id, telemetry)

    accepted = owner == "old-operation" and workflow_state in {"none", "running"}
    if accepted:
        assert environment.activeOperationId is None
        assert environment.providerState["currentOperation"]["operationId"] == "old-operation"
        assert environment.providerState["currentOperation"]["phase"] == "failed"
        assert environment.lastModifiedBy == "cleanup@example.com"
        if kind == "deploy":
            assert revision.lifecycleState == DeploymentRevisionState.DEPLOYMENT_FAILED
            assert revision.health["diagnostics"] == ["dispatch failed"]
        else:
            assert environment.lifecycleState == (
                DemoEnvironmentState.PROVISIONING_FAILED
                if kind == "provision"
                else DemoEnvironmentState.TEARDOWN_FAILED
            )
        if workflow is not None:
            assert workflow.status == WorkflowStatus.FAILED
        telemetry.emit.assert_called_once()
        assert "Rejected dispatch-failure cleanup" not in caplog.text
    else:
        assert environment.activeOperationId == owner
        assert (
            environment.lifecycleState,
            environment.providerState,
            environment.lastModifiedBy,
            revision.lifecycleState,
            revision.health,
        ) == before
        if workflow is not None:
            assert workflow.status == (
                WorkflowStatus.COMPLETED if workflow_state == "terminal" else WorkflowStatus.RUNNING
            )
            assert workflow.diagnostics == {}
        telemetry.emit.assert_not_called()
        assert "Rejected dispatch-failure cleanup" in caplog.text


@pytest.mark.parametrize("kind", ["provision", "teardown", "deploy"])
def test_dispatch_cleanup_does_not_swallow_unexpected_completion_failure(
    session, kind, monkeypatch
) -> None:
    environment = session.environments["env-demo"]
    environment.activeOperationId = "old-operation"
    before = deepcopy(environment.providerState)
    telemetry = MagicMock()

    def fail_completion(*args, **kwargs):
        raise RuntimeError("completion unavailable")

    monkeypatch.setattr(OrchestrationWorkflowService, "complete_workflow", fail_completion)
    with pytest.raises(RuntimeError, match="completion unavailable"):
        _cleanup(session, kind, "workflow-1", telemetry)

    assert environment.activeOperationId == "old-operation"
    assert environment.providerState == before
    assert (
        session.get(DeploymentRevision, "revision-1").lifecycleState
        == DeploymentRevisionState.PENDING
    )
    telemetry.emit.assert_not_called()
