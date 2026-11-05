from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from src.api.app import create_app
from src.config import Settings
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    CompletenessIndicator,
    DeploymentRevisionState,
    ExperimentRunStatus,
    ExperimentRunType,
    RetentionClass,
)
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import EnvironmentLockService
from src.domain.experiment_run import ExperimentRun
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.domain.result_report import ResultReport
from src.domain.result_report_repo import ResultReportRepository
from tests.integration.test_postgresql import database as database
from tests.integration.test_postgresql import environment as environment

pytestmark = pytest.mark.integration
ACTOR = "postgres-test@example.com"
HEADERS = {"X-Demo-User": ACTOR}


@pytest.fixture
def api(environment):
    session_factory, environment_id = environment
    app = create_app(Settings(database_url=os.environ["TEST_DATABASE_URL"], auth_mode="local-demo"))
    with TestClient(app) as client:
        yield client, session_factory, environment_id
    app.state.session_factory.kw["bind"].dispose()
    app.state.database_readiness.close()
    with session_factory() as session:
        revision_ids = select(DeploymentRevision.deploymentRevisionId).where(
            DeploymentRevision.environmentId == environment_id
        )
        run_ids = select(ExperimentRun.runId).where(
            ExperimentRun.deploymentRevisionId.in_(revision_ids)
        )
        session.execute(delete(ResultReport).where(ResultReport.runId.in_(run_ids)))
        session.execute(delete(ExperimentRun).where(ExperimentRun.runId.in_(run_ids)))
        session.get(DemoEnvironment, environment_id).activeDeploymentRevisionId = None
        session.flush()
        session.execute(
            delete(DeploymentRevision).where(DeploymentRevision.environmentId == environment_id)
        )
        for model in (ModelConfiguration, InferenceConfiguration):
            session.execute(delete(model).where(model.environmentId == environment_id))
        session.commit()


def create(client, environment_id, kind):
    payload = (
        {
            "catalogEntryId": "qwen2.5-0.5b-instruct",
            "resolvedCheckpointRef": "a" * 40,
            "modelSettings": {"acceptance": "scratch"},
        }
        if kind == "model"
        else {"engineId": "ollama", "generationSettings": {"temperature": 0.0}}
    )
    response = client.post(
        f"/environments/{environment_id}/{kind}-configurations", headers=HEADERS, json=payload
    )
    assert response.status_code == 201, response.text
    result = response.json()
    configuration_id = result[f"{kind}ConfigId"]
    assert str(UUID(configuration_id)) == configuration_id
    return configuration_id


def reference(session, environment_id, model_id, inference_id, state):
    revision = DeploymentRevision(
        deploymentRevisionId=str(uuid4()),
        environmentId=environment_id,
        modelConfigId=model_id,
        inferenceConfigId=inference_id,
        engineId="ollama",
        lifecycleState=state,
        activePeriod={},
        health={"status": "healthy"},
        createdBy=ACTOR,
    )
    session.add(revision)
    session.flush()
    return revision


@pytest.mark.parametrize("kind", ["model", "inference"])
def test_owned_scratch_roundtrip_delete_and_create_again(api, kind):
    client, session_factory, environment_id = api
    root = f"/environments/{environment_id}/{kind}-configurations"
    ids = [create(client, environment_id, kind) for _ in range(3)]
    rows = client.get(root, headers=HEADERS).json()["items"]
    assert {row[f"{kind}ConfigId"] for row in rows} == set(ids)
    assert client.delete(f"{root}/{ids[0]}", headers=HEADERS).status_code == 204
    # Deleting a non-last row must not cause the old COUNT+1 ID collision.
    newest = create(client, environment_id, kind)
    assert newest not in ids
    assert client.delete(f"{root}/{ids[0]}", headers=HEADERS).status_code == 404
    assert {
        row[f"{kind}ConfigId"] for row in client.get(root, headers=HEADERS).json()["items"]
    } == {ids[1], ids[2], newest}
    with session_factory() as session:
        assert session.get(DemoEnvironment, environment_id).activeOperationId is None


@pytest.mark.parametrize(
    ("kind", "model"), [("model", ModelConfiguration), ("inference", InferenceConfiguration)]
)
def test_existing_legacy_ids_remain_unchanged_and_deletable(api, kind, model):
    client, session_factory, environment_id = api
    configuration_id = create(client, environment_id, kind)
    legacy_id = f"{environment_id}-{kind}-1"
    with session_factory() as session:
        configuration = session.get(model, configuration_id)
        setattr(configuration, f"{kind}ConfigId", legacy_id)
        session.commit()
    root = f"/environments/{environment_id}/{kind}-configurations"
    assert client.get(root, headers=HEADERS).json()["items"][0][f"{kind}ConfigId"] == legacy_id
    assert create(client, environment_id, kind) != legacy_id
    assert client.delete(f"{root}/{legacy_id}", headers=HEADERS).status_code == 204


@pytest.mark.parametrize("kind", ["model", "inference"])
def test_cleanup_rejects_anonymous_other_owner_wrong_scope_and_busy(api, kind):
    client, session_factory, environment_id = api
    configuration_id = create(client, environment_id, kind)
    path = f"/environments/{environment_id}/{kind}-configurations/{configuration_id}"
    assert client.delete(path).status_code == 401
    response = client.delete(path, headers={"X-Demo-User": "other@example.com"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "configuration_not_owned"
    assert (
        client.delete(path.replace(environment_id, "missing"), headers=HEADERS).status_code == 404
    )
    # A real different environment exists, but cannot address this environment's row.
    with session_factory() as session:
        original = session.get(DemoEnvironment, environment_id)
        other_id = f"other-{uuid4().hex}"
        session.add(
            DemoEnvironment(
                environmentId=other_id,
                profileId=original.profileId,
                provider=original.provider,
                region=original.region,
                lifecycleState=original.lifecycleState,
                providerState={},
                createdBy=ACTOR,
                lastModifiedBy=ACTOR,
            )
        )
        session.commit()
    try:
        assert (
            client.delete(path.replace(environment_id, other_id), headers=HEADERS).status_code
            == 404
        )
    finally:
        with session_factory() as session:
            session.execute(
                delete(DemoEnvironment).where(DemoEnvironment.environmentId == other_id)
            )
            session.commit()
    with session_factory() as session:
        assert session.get(DemoEnvironment, environment_id).activeOperationId is None
        EnvironmentLockService().acquire(
            session, environment_id=environment_id, operation_id="actual-deployment"
        )
        session.commit()
    response = client.delete(path, headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "environment_busy"
    with session_factory() as session:
        assert session.get(DemoEnvironment, environment_id).activeOperationId == "actual-deployment"
        EnvironmentLockService().release(
            session, environment_id=environment_id, operation_id="actual-deployment"
        )
        session.commit()
    assert client.delete(path, headers=HEADERS).status_code == 204


@pytest.mark.parametrize("state", list(DeploymentRevisionState))
def test_every_revision_state_protects_configs_and_existing_report(api, state):
    client, session_factory, environment_id = api
    model_id = create(client, environment_id, "model")
    inference_id = create(client, environment_id, "inference")
    with session_factory() as session:
        revision = reference(session, environment_id, model_id, inference_id, state)
        revision_id = revision.deploymentRevisionId
        if state == DeploymentRevisionState.READY:
            session.get(DemoEnvironment, environment_id).activeDeploymentRevisionId = revision_id
        run = ExperimentRun(
            runId=str(uuid4()),
            deploymentRevisionId=revision_id,
            runType=ExperimentRunType.QUALITY_GOLDEN,
            testDefinitionRef="retained",
            status=ExperimentRunStatus.COMPLETED,
            environmentContextSnapshot={"immutable": True},
            diagnostics=[],
            cancellationRequests=[],
            retentionClass=RetentionClass.PERSISTED,
        )
        session.add(run)
        session.flush()
        report = ResultReportRepository().upsert(
            session,
            run_id=run.runId,
            quality={"cases": [], "aggregate": {}},
            performance=None,
            completeness_indicator=CompletenessIndicator.COMPLETE,
        )
        report_id = report.resultReportId
        session.commit()
    for kind, configuration_id in (("model", model_id), ("inference", inference_id)):
        response = client.delete(
            f"/environments/{environment_id}/{kind}-configurations/{configuration_id}",
            headers=HEADERS,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "configuration_in_use"
    with session_factory() as session:
        assert session.get(DeploymentRevision, revision_id).lifecycleState == state
        assert session.get(ResultReport, report_id).quality == {"cases": [], "aggregate": {}}
        assert session.get(DemoEnvironment, environment_id).activeOperationId is None
        if state == DeploymentRevisionState.READY:
            assert (
                session.get(DemoEnvironment, environment_id).activeDeploymentRevisionId
                == revision_id
            )


def wait_for_real_database_lock(session_factory, holder_pid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with session_factory() as observer:
            blocked = observer.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))"
                ),
                {"pid": holder_pid},
            )
        if blocked:
            return
        time.sleep(0.01)
    pytest.fail("HTTP writer did not wait on the existing PostgreSQL environment row lock")


@pytest.mark.parametrize("kind", ["model", "inference"])
def test_cleanup_waits_for_deployment_writer_then_rejects_its_new_reference(api, kind):
    client, session_factory, environment_id = api
    model_id = create(client, environment_id, "model")
    inference_id = create(client, environment_id, "inference")
    target = model_id if kind == "model" else inference_id
    with ThreadPoolExecutor(max_workers=1) as executor:
        with session_factory() as deployment:
            EnvironmentLockService().acquire(
                deployment, environment_id=environment_id, operation_id="deployment-writer"
            )
            holder_pid = deployment.scalar(text("SELECT pg_backend_pid()"))
            pending = executor.submit(
                client.delete,
                f"/environments/{environment_id}/{kind}-configurations/{target}",
                headers=HEADERS,
            )
            try:
                wait_for_real_database_lock(session_factory, holder_pid)
                reference(
                    deployment,
                    environment_id,
                    model_id,
                    inference_id,
                    DeploymentRevisionState.READY,
                )
                EnvironmentLockService().release(
                    deployment, environment_id=environment_id, operation_id="deployment-writer"
                )
                deployment.commit()
            finally:
                deployment.rollback()
        response = pending.result(timeout=5)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "configuration_in_use"


@pytest.mark.parametrize("kind", ["model", "inference"])
def test_deployment_waits_for_cleanup_then_rereads_configuration_as_missing(api, kind):
    client, session_factory, environment_id = api
    model_id = create(client, environment_id, "model")
    inference_id = create(client, environment_id, "inference")
    model = ModelConfiguration if kind == "model" else InferenceConfiguration
    target = model_id if kind == "model" else inference_id
    with ThreadPoolExecutor(max_workers=1) as executor:
        with session_factory() as cleanup:
            EnvironmentLockService().acquire(
                cleanup, environment_id=environment_id, operation_id="cleanup-writer"
            )
            holder_pid = cleanup.scalar(text("SELECT pg_backend_pid()"))
            pending = executor.submit(
                client.post,
                f"/environments/{environment_id}/deployments",
                headers=HEADERS,
                json={"modelConfigId": model_id, "inferenceConfigId": inference_id},
            )
            try:
                wait_for_real_database_lock(session_factory, holder_pid)
                cleanup.delete(cleanup.get(model, target))
                EnvironmentLockService().release(
                    cleanup, environment_id=environment_id, operation_id="cleanup-writer"
                )
                cleanup.commit()
            finally:
                cleanup.rollback()
        response = pending.result(timeout=5)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == f"{kind}_configuration_not_found"
    with session_factory() as session:
        assert session.get(DemoEnvironment, environment_id).activeOperationId is None
        assert (
            session.scalar(
                select(DeploymentRevision).where(DeploymentRevision.environmentId == environment_id)
            )
            is None
        )
