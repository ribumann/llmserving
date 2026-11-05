from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from src.api.app import create_app
from src.config import Settings
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    DemoEnvironmentState,
    DeploymentRevisionState,
    ExperimentRunStatus,
    ExperimentRunType,
    ProviderType,
    RetentionClass,
    WorkflowStatus,
    WorkflowType,
)
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import EnvironmentLockedError, EnvironmentLockService
from src.domain.experiment_run import ExperimentRun
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.domain.orchestration_workflow import OrchestrationWorkflow
from src.domain.orchestration_workflow_service import (
    OrchestrationWorkflowService,
    WorkflowNotRunningError,
)
from src.domain.profile import CloudDeploymentProfile
from src.evaluation.run_quality import QualityRunContext, QualityRunOrchestrator
from src.persistence.db import create_engine_from_settings
from src.providers.local.adapter import LocalProviderAdapter

pytestmark = pytest.mark.integration


@pytest.fixture
def database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set TEST_DATABASE_URL to an explicitly disposable, migrated PostgreSQL database."
        )
    if not url.startswith("postgresql+psycopg://"):
        pytest.fail("TEST_DATABASE_URL must use real PostgreSQL through psycopg.")
    engine = create_engine_from_settings(Settings(database_url=url))
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_database()")).scalar_one()
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def environment(database):
    session_factory = sessionmaker(bind=database, expire_on_commit=False)
    environment_id = f"postgres-test-{uuid4().hex}"
    with session_factory() as session:
        assert session.get(CloudDeploymentProfile, "local-ollama") is not None
        session.add(
            DemoEnvironment(
                environmentId=environment_id,
                profileId="local-ollama",
                provider=ProviderType.LOCAL,
                region="local",
                lifecycleState=DemoEnvironmentState.READY,
                providerState={"runtime": "ollama", "nested": {"verified": True}},
                createdBy="postgres-test@example.com",
                lastModifiedBy="postgres-test@example.com",
            )
        )
        session.commit()
    try:
        yield session_factory, environment_id
    finally:
        with session_factory() as session:
            session.execute(
                delete(DemoEnvironment).where(DemoEnvironment.environmentId == environment_id)
            )
            session.commit()


def test_migrated_postgres_serves_real_catalog(database) -> None:
    settings = Settings(database_url=os.environ["TEST_DATABASE_URL"])
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/profiles", headers={"X-Demo-User": "postgres-test@example.com"})
        assert response.status_code == 200
        profiles = {profile["profileId"]: profile for profile in response.json()["profiles"]}
        assert profiles["local-ollama"]["provider"] == "local"
        assert isinstance(profiles["local-ollama"]["capacityAssumptions"], dict)
        catalog = client.get("/catalog", headers={"X-Demo-User": "postgres-test@example.com"})
        assert catalog.status_code == 200
        assert any(
            entry["catalogEntryId"] == "qwen2.5-0.5b-instruct"
            for entry in catalog.json()["catalog"]
        )
    app.state.session_factory.kw["bind"].dispose()


def test_jsonb_roundtrip_and_owner_safe_lock_release(environment) -> None:
    session_factory, environment_id = environment
    locks = EnvironmentLockService()
    with session_factory() as session:
        saved = session.get(DemoEnvironment, environment_id)
        assert saved.providerState == {"runtime": "ollama", "nested": {"verified": True}}
        locks.acquire(session, environment_id=environment_id, operation_id="owner")
        session.commit()
    with session_factory() as session:
        with pytest.raises(EnvironmentLockedError):
            locks.release(session, environment_id=environment_id, operation_id="not-owner")
        session.rollback()
    with session_factory() as session:
        assert locks.current(session, environment_id=environment_id).operation_id == "owner"
        locks.release(session, environment_id=environment_id, operation_id="owner")
        session.commit()
    with session_factory() as session:
        assert locks.current(session, environment_id=environment_id).operation_id is None


@pytest.mark.parametrize("operation", ["acquire", "release"])
def test_lock_ownership_refreshes_cached_environment_without_losing_other_changes(
    environment, operation
) -> None:
    session_factory, environment_id = environment
    locks = EnvironmentLockService()
    with session_factory() as session:
        locks.acquire(session, environment_id=environment_id, operation_id="old-owner")
        session.commit()
    with session_factory(autoflush=False) as stale:
        cached = stale.get(DemoEnvironment, environment_id)
        assert cached.activeOperationId == "old-owner"
        cached.lastModifiedBy = "pending-change@example.com"
        with session_factory() as fresh:
            locks.release(fresh, environment_id=environment_id, operation_id="old-owner")
            locks.acquire(fresh, environment_id=environment_id, operation_id="new-owner")
            fresh.commit()
        action = getattr(locks, operation)
        with pytest.raises(EnvironmentLockedError):
            action(stale, environment_id=environment_id, operation_id="old-owner")
        assert cached.activeOperationId == "new-owner"
        assert cached.lastModifiedBy == "pending-change@example.com"
        stale.commit()
    with session_factory() as session:
        saved = session.get(DemoEnvironment, environment_id)
        assert saved.activeOperationId == "new-owner"
        assert saved.lastModifiedBy == "pending-change@example.com"


@pytest.fixture
def workflow(environment):
    session_factory, environment_id = environment
    with session_factory() as session:
        workflow = OrchestrationWorkflowService().create_workflow(
            session,
            environment_id=environment_id,
            operation_id="original-operation",
            workflow_type=WorkflowType.PROVISION,
        )
        workflow_id = workflow.workflowId
        session.commit()
    try:
        yield session_factory, environment_id, workflow_id
    finally:
        with session_factory() as session:
            session.execute(
                delete(OrchestrationWorkflow).where(OrchestrationWorkflow.workflowId == workflow_id)
            )
            session.commit()


@pytest.mark.parametrize("owner", ["new-operation", None])
@pytest.mark.parametrize(
    "status", [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]
)
def test_restarted_workflow_completion_preserves_new_owner_and_original_state(
    workflow, owner, status
) -> None:
    session_factory, environment_id, workflow_id = workflow
    with session_factory() as session:
        saved = session.get(DemoEnvironment, environment_id)
        saved.activeOperationId = owner
        session.commit()
    with session_factory() as callback:
        with pytest.raises(EnvironmentLockedError):
            OrchestrationWorkflowService().complete_workflow(
                callback,
                workflow_id=workflow_id,
                status=status,
                phase="late-completion",
                diagnostics={"late": True},
            )
        callback.commit()
    with session_factory() as session:
        saved = session.get(OrchestrationWorkflow, workflow_id)
        assert saved.status == WorkflowStatus.RUNNING
        assert saved.phase == "accepted"
        assert saved.diagnostics == {}
        assert saved.endedAt is None
        assert session.get(DemoEnvironment, environment_id).activeOperationId == owner


@pytest.mark.parametrize(
    "status", [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]
)
def test_restarted_completion_and_duplicate_preserve_new_lock(workflow, status) -> None:
    session_factory, environment_id, workflow_id = workflow
    with session_factory() as callback:
        OrchestrationWorkflowService().complete_workflow(
            callback,
            workflow_id=workflow_id,
            status=status,
            phase="finished",
            diagnostics={"retained": True},
        )
        callback.commit()
    with session_factory() as session:
        assert session.get(DemoEnvironment, environment_id).activeOperationId is None
        EnvironmentLockService().acquire(
            session, environment_id=environment_id, operation_id="new-operation"
        )
        session.commit()
    with session_factory() as duplicate:
        with pytest.raises(WorkflowNotRunningError):
            OrchestrationWorkflowService().complete_workflow(
                duplicate,
                workflow_id=workflow_id,
                status=WorkflowStatus.FAILED,
                phase="late-completion",
                diagnostics={"late": True},
            )
        duplicate.commit()
    with session_factory() as session:
        saved = session.get(OrchestrationWorkflow, workflow_id)
        assert saved.status == status
        assert saved.phase == "finished"
        assert saved.diagnostics == {"retained": True}
        assert saved.endedAt is not None
        assert session.get(DemoEnvironment, environment_id).activeOperationId == "new-operation"


def test_workflow_completion_rollback_retains_lock_and_nonterminal_state(workflow) -> None:
    session_factory, environment_id, workflow_id = workflow
    with session_factory() as callback:
        OrchestrationWorkflowService().complete_workflow(
            callback,
            workflow_id=workflow_id,
            status=WorkflowStatus.COMPLETED,
            phase="uncommitted",
            diagnostics={"uncommitted": True},
        )
        callback.rollback()
    with session_factory() as session:
        saved = session.get(OrchestrationWorkflow, workflow_id)
        assert saved.status == WorkflowStatus.RUNNING
        assert saved.phase == "accepted"
        assert saved.diagnostics == {}
        assert saved.endedAt is None
        assert (
            session.get(DemoEnvironment, environment_id).activeOperationId == "original-operation"
        )


def test_postgres_serializes_concurrent_lock_acquisition(environment) -> None:
    session_factory, environment_id = environment
    locks = EnvironmentLockService()
    with session_factory() as owner, session_factory() as contender:
        locks.acquire(owner, environment_id=environment_id, operation_id="owner")
        contender.execute(text("SET LOCAL lock_timeout = '250ms'"))
        with pytest.raises(OperationalError) as error:
            locks.acquire(contender, environment_id=environment_id, operation_id="contender")
        assert error.value.orig.sqlstate == "55P03"
        contender.rollback()
        owner.commit()
    with session_factory() as session:
        with pytest.raises(EnvironmentLockedError):
            locks.acquire(session, environment_id=environment_id, operation_id="contender")
        session.rollback()


@pytest.mark.parametrize(
    "concurrent_state,owner,expected",
    [
        (DemoEnvironmentState.TORN_DOWN, None, DemoEnvironmentState.TORN_DOWN),
        (DemoEnvironmentState.TEARING_DOWN, "teardown-owner", DemoEnvironmentState.TEARING_DOWN),
        (
            DemoEnvironmentState.PROVISIONING_FAILED,
            "new-owner",
            DemoEnvironmentState.PROVISIONING_FAILED,
        ),
        (DemoEnvironmentState.PROVISIONING_FAILED, None, DemoEnvironmentState.READY),
    ],
)
def test_local_runtime_recovery_rechecks_state_and_lock_owner(
    environment, monkeypatch, concurrent_state, owner, expected
) -> None:
    session_factory, environment_id = environment
    with session_factory() as session:
        saved = session.get(DemoEnvironment, environment_id)
        saved.lifecycleState = DemoEnvironmentState.PROVISIONING_FAILED
        session.commit()

    def probe_after_initial_read():
        with session_factory() as concurrent:
            saved = concurrent.get(DemoEnvironment, environment_id)
            saved.lifecycleState = concurrent_state
            saved.activeOperationId = owner
            saved.providerState = {"fresh": True}
            concurrent.commit()
        return None

    adapter = LocalProviderAdapter(session_factory=session_factory, settings=Settings())
    monkeypatch.setattr(adapter, "_probe_runtime", probe_after_initial_read)
    state = adapter.getEnvironmentState(environment_id)
    assert state.lifecycleState == expected.value
    with session_factory() as session:
        saved = session.get(DemoEnvironment, environment_id)
        assert saved.lifecycleState == expected
        assert saved.activeOperationId == owner
        assert saved.providerState["fresh"] is True


@pytest.mark.parametrize("status", [ExperimentRunStatus.QUEUED, ExperimentRunStatus.RUNNING])
def test_persisted_cancellation_waits_for_worker_in_another_session(environment, status) -> None:
    session_factory, environment_id = environment
    model_id = f"{environment_id}-model"
    inference_id = f"{environment_id}-inference"
    revision_id = f"{environment_id}-revision"
    run_id = f"{environment_id}-run"
    actor = "postgres-test@example.com"
    with session_factory() as session:
        session.add(
            ModelConfiguration(
                modelConfigId=model_id,
                environmentId=environment_id,
                catalogEntryId="qwen2.5-0.5b-instruct",
                resolvedCheckpointRef="qwen2.5:0.5b-instruct",
                modelSettings={},
                version=1,
                createdBy=actor,
            )
        )
        session.add(
            InferenceConfiguration(
                inferenceConfigId=inference_id,
                environmentId=environment_id,
                engineId="ollama",
                servingSettings={},
                generationSettings={},
                version=1,
                createdBy=actor,
            )
        )
        session.flush()
        session.add(
            DeploymentRevision(
                deploymentRevisionId=revision_id,
                environmentId=environment_id,
                modelConfigId=model_id,
                inferenceConfigId=inference_id,
                engineId="ollama",
                lifecycleState=DeploymentRevisionState.READY,
                activePeriod={},
                health={},
                createdBy=actor,
            )
        )
        session.flush()
        session.add(
            ExperimentRun(
                runId=run_id,
                deploymentRevisionId=revision_id,
                runType=ExperimentRunType.QUALITY_GOLDEN,
                testDefinitionRef="golden-default",
                status=status,
                environmentContextSnapshot={},
                diagnostics=[],
                cancellationRequests=[],
                retentionClass=RetentionClass.PERSISTED,
            )
        )
        session.get(DemoEnvironment, environment_id).activeOperationId = run_id
        session.commit()
    try:
        requester = QualityRunOrchestrator(session_factory=session_factory, provider=object())
        worker = QualityRunOrchestrator(session_factory=session_factory, provider=object())
        first = requester.cancel(run_id=run_id, requested_by=actor)
        second = requester.cancel(run_id=run_id, requested_by=actor)
        assert first.status == second.status == status
        assert first.cancellationRequests == second.cancellationRequests
        assert len(second.cancellationRequests) == 1
        with session_factory() as session:
            assert session.get(DemoEnvironment, environment_id).activeOperationId == run_id
        assert worker._should_cancel(run_id)
        worker._finish_cancelled(
            QualityRunContext(
                environmentId=environment_id,
                deploymentRevisionId=revision_id,
                engineId="ollama",
                runId=run_id,
                operationId=run_id,
                actorEmail=actor,
                runType=ExperimentRunType.QUALITY_GOLDEN,
                testDefinitionRef="golden-default",
                inferenceApiUrl="http://unused",
            )
        )
        with session_factory() as session:
            assert session.get(ExperimentRun, run_id).status == ExperimentRunStatus.CANCELLED
            assert session.get(DemoEnvironment, environment_id).activeOperationId is None
    finally:
        with session_factory() as session:
            session.execute(delete(ExperimentRun).where(ExperimentRun.runId == run_id))
            session.execute(
                delete(DeploymentRevision).where(
                    DeploymentRevision.deploymentRevisionId == revision_id
                )
            )
            session.execute(
                delete(InferenceConfiguration).where(
                    InferenceConfiguration.inferenceConfigId == inference_id
                )
            )
            session.execute(
                delete(ModelConfiguration).where(ModelConfiguration.modelConfigId == model_id)
            )
            session.commit()
