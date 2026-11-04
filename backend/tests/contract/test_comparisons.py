from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    CompletenessIndicator,
    DeploymentRevisionState,
    ExperimentRunStatus,
    ExperimentRunType,
    RetentionClass,
)
from src.domain.experiment_run import ExperimentRun
from src.domain.result_report import ResultReport
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
    client = TestClient(app)
    client.headers.update({"X-Demo-User": "presenter@example.com"})
    return client, session


def _base_snapshot(**overrides) -> dict:
    snapshot = {
        "environmentId": "env-demo",
        "profileId": "azure-single-gpu-3b",
        "region": "eastus2",
        "provider": "azure",
        "providerState": {"inferenceApiUrl": "http://vllm.local"},
        "deploymentRevision": {
            "deploymentRevisionId": "revision-1",
            "engineId": "vllm",
            "modelConfigId": "model-config-1",
            "inferenceConfigId": "inference-config-1",
        },
        "modelConfiguration": {
            "modelConfigId": "model-config-1",
            "resolvedCheckpointRef": "Qwen/Qwen3-4B@main",
            "modelSettings": {},
        },
        "inferenceConfiguration": {
            "inferenceConfigId": "inference-config-1",
            "servingSettings": {},
            "generationSettings": {},
        },
        "testDefinition": {"goldenDatasetId": "golden-default"},
    }
    snapshot.update(overrides)
    return snapshot


def _seed_run_and_report(
    session: MemorySession,
    *,
    run_id: str,
    report_id: str,
    revision_id: str,
    snapshot: dict,
    passed: int = 1,
    failed: int = 0,
) -> None:
    session.deployment_revisions[revision_id] = DeploymentRevision(
        deploymentRevisionId=revision_id,
        environmentId="env-demo",
        engineId="vllm",
        modelConfigId="model-config-1",
        inferenceConfigId="inference-config-1",
        lifecycleState=DeploymentRevisionState.READY,
        health={"status": "healthy", "diagnostics": []},
        createdAt=datetime.now(UTC),
    )
    session.experiment_runs[run_id] = ExperimentRun(
        runId=run_id,
        deploymentRevisionId=revision_id,
        runType=ExperimentRunType.QUALITY_GOLDEN,
        testDefinitionRef="golden-default",
        status=ExperimentRunStatus.COMPLETED,
        environmentContextSnapshot=snapshot,
        startedAt=datetime.now(UTC),
        diagnostics=[],
        cancellationRequests=[],
        retentionClass=RetentionClass.PERSISTED,
    )
    session.result_reports[report_id] = ResultReport(
        resultReportId=report_id,
        runId=run_id,
        quality={
            "aggregate": {
                "totalCases": passed + failed,
                "passed": passed,
                "failed": failed,
                "errored": 0,
                "incomplete": 0,
                "passRate": passed / (passed + failed) if (passed + failed) else 0.0,
            }
        },
        performance=None,
        completenessIndicator=CompletenessIndicator.COMPLETE,
    )


def test_create_comparison_flags_comparable_runs() -> None:
    client, session = _build_client()
    _seed_run_and_report(
        session,
        run_id="run-1",
        report_id="report-1",
        revision_id="revision-1",
        snapshot=_base_snapshot(),
        passed=8,
        failed=2,
    )
    _seed_run_and_report(
        session,
        run_id="run-2",
        report_id="report-2",
        revision_id="revision-1",
        snapshot=_base_snapshot(),
        passed=9,
        failed=1,
    )

    response = client.post("/comparisons", json={"reportIds": ["report-1", "report-2"]})

    assert response.status_code == 201
    body = response.json()
    assert body["comparabilityStatus"] == "comparable"
    assert body["reasons"] == []
    assert {report["reportId"] for report in body["reports"]} == {"report-1", "report-2"}
    section_titles = [section["title"] for section in body["sections"]]
    assert section_titles == [
        "Configuration",
        "Quality",
        "Performance",
        "Failures",
        "Accelerator utilization",
    ]
    quality_section = next(s for s in body["sections"] if s["title"] == "Quality")
    assert len(quality_section["items"]) == 2


def test_create_comparison_flags_different_checkpoints_as_not_comparable() -> None:
    client, session = _build_client()
    _seed_run_and_report(
        session,
        run_id="run-1",
        report_id="report-1",
        revision_id="revision-1",
        snapshot=_base_snapshot(),
    )
    _seed_run_and_report(
        session,
        run_id="run-2",
        report_id="report-2",
        revision_id="revision-2",
        snapshot=_base_snapshot(
            modelConfiguration={
                "modelConfigId": "model-config-2",
                "resolvedCheckpointRef": "Qwen/Qwen3-4B@v2",
                "modelSettings": {},
            }
        ),
    )

    response = client.post("/comparisons", json={"reportIds": ["report-1", "report-2"]})

    assert response.status_code == 201
    body = response.json()
    assert body["comparabilityStatus"] == "not-directly-comparable"
    assert any("checkpoint" in reason.lower() for reason in body["reasons"])


def test_create_comparison_requires_at_least_two_reports() -> None:
    client, session = _build_client()
    _seed_run_and_report(
        session,
        run_id="run-1",
        report_id="report-1",
        revision_id="revision-1",
        snapshot=_base_snapshot(),
    )

    response = client.post("/comparisons", json={"reportIds": ["report-1"]})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "insufficient_reports"


def test_create_comparison_404s_for_unknown_report() -> None:
    client, _session = _build_client()

    response = client.post("/comparisons", json={"reportIds": ["missing-1", "missing-2"]})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "result_report_not_found"


def test_get_comparison_round_trips_persisted_comparison() -> None:
    client, session = _build_client()
    _seed_run_and_report(
        session,
        run_id="run-1",
        report_id="report-1",
        revision_id="revision-1",
        snapshot=_base_snapshot(),
    )
    _seed_run_and_report(
        session,
        run_id="run-2",
        report_id="report-2",
        revision_id="revision-1",
        snapshot=_base_snapshot(),
    )
    created = client.post("/comparisons", json={"reportIds": ["report-1", "report-2"]}).json()

    response = client.get(f"/comparisons/{created['comparisonId']}")

    assert response.status_code == 200
    body = response.json()
    assert body["comparisonId"] == created["comparisonId"]
    assert body["comparabilityStatus"] == "comparable"
    assert {report["reportId"] for report in body["reports"]} == {"report-1", "report-2"}


def test_get_comparison_404s_for_unknown_id() -> None:
    client, _session = _build_client()

    response = client.get("/comparisons/comparison-missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "comparison_not_found"
