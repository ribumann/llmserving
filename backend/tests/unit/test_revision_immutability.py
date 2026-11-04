from __future__ import annotations

from datetime import UTC, datetime

from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DeploymentRevisionState, WorkflowStatus, WorkflowType
from src.domain.orchestration_workflow import OrchestrationWorkflow
from src.domain.workflow_reconciliation import WorkflowReconciliationService
from tests.support.demo_backend import MemorySession


def _revision(
    revision_id: str, *, lifecycle_state: DeploymentRevisionState, created_at: datetime
) -> DeploymentRevision:
    return DeploymentRevision(
        deploymentRevisionId=revision_id,
        environmentId="env-demo",
        engineId="vllm",
        modelConfigId="model-config-1",
        inferenceConfigId="inference-config-1",
        lifecycleState=lifecycle_state,
        health={},
        createdAt=created_at,
    )


def test_reconcile_deploy_marks_prior_ready_revision_superseded() -> None:
    session = MemorySession()
    session.seed_defaults()
    environment = session.environments["env-demo"]
    environment.activeDeploymentRevisionId = "revision-old"

    old_revision = _revision(
        "revision-old",
        lifecycle_state=DeploymentRevisionState.READY,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    new_revision = _revision(
        "revision-new",
        lifecycle_state=DeploymentRevisionState.DEPLOYING,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    session.deployment_revisions[old_revision.deploymentRevisionId] = old_revision
    session.deployment_revisions[new_revision.deploymentRevisionId] = new_revision

    workflow = OrchestrationWorkflow(
        workflowId="workflow-1",
        environmentId="env-demo",
        operationId="op-1",
        workflowType=WorkflowType.DEPLOY,
        status=WorkflowStatus.COMPLETED,
        diagnostics={"deploymentRevisionId": "revision-new", "vllmBaseUrl": "http://vllm.local"},
    )

    WorkflowReconciliationService().reconcile(session, workflow=workflow)

    assert new_revision.lifecycleState == DeploymentRevisionState.READY
    assert old_revision.lifecycleState == DeploymentRevisionState.SUPERSEDED
    assert environment.activeDeploymentRevisionId == "revision-new"


def test_reconcile_deploy_does_not_supersede_revisions_from_other_environments() -> None:
    session = MemorySession()
    session.seed_defaults()
    session.environments["env-other"] = session.environments["env-demo"].__class__(
        environmentId="env-other",
        profileId="azure-single-gpu-3b",
        provider=session.environments["env-demo"].provider,
        region="eastus2",
        regionRecommendation=None,
        lifecycleState=session.environments["env-demo"].lifecycleState,
        activeDeploymentRevisionId="revision-other",
        providerState={},
        createdBy="presenter@example.com",
        lastModifiedBy="presenter@example.com",
    )
    other_env_revision = _revision(
        "revision-other-env",
        lifecycle_state=DeploymentRevisionState.READY,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    other_env_revision.environmentId = "env-other"
    new_revision = _revision(
        "revision-new",
        lifecycle_state=DeploymentRevisionState.DEPLOYING,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    session.deployment_revisions[other_env_revision.deploymentRevisionId] = other_env_revision
    session.deployment_revisions[new_revision.deploymentRevisionId] = new_revision

    workflow = OrchestrationWorkflow(
        workflowId="workflow-1",
        environmentId="env-demo",
        operationId="op-1",
        workflowType=WorkflowType.DEPLOY,
        status=WorkflowStatus.COMPLETED,
        diagnostics={"deploymentRevisionId": "revision-new", "vllmBaseUrl": "http://vllm.local"},
    )

    WorkflowReconciliationService().reconcile(session, workflow=workflow)

    assert other_env_revision.lifecycleState == DeploymentRevisionState.READY
    assert new_revision.lifecycleState == DeploymentRevisionState.READY
