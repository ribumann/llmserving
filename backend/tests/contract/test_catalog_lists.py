from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.benchmark_definition import BenchmarkDefinition
from src.domain.enums import (
    DatasetProvenance,
    DemoEnvironmentState,
    ExperimentRunStatus,
    ExperimentRunType,
    ProviderType,
    RetentionClass,
    ReviewStatus,
)
from src.domain.environment import DemoEnvironment
from src.domain.experiment_run import ExperimentRun
from src.domain.golden_dataset import GoldenDataset
from src.domain.performance_workload import PerformanceWorkload
from src.persistence.db import get_db_session


class FakeScalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._rows)


class FakeSession:
    def __init__(
        self, rows: list[object], *, get_map: dict[tuple[type, str], object] | None = None
    ) -> None:
        self._rows = rows
        self._get_map = get_map or {}

    def execute(self, _stmt) -> FakeResult:
        return FakeResult(self._rows)

    def scalars(self, _stmt) -> FakeScalars:
        return FakeScalars(self._rows)

    def get(self, model: type, key: str) -> object | None:
        return self._get_map.get((model, key))


def _client(session: FakeSession) -> TestClient:
    app = create_app()
    app.state.provider_adapter = None
    app.state.session_factory = None
    app.state.telemetry = None

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    return TestClient(app)


def _golden_dataset(dataset_id: str) -> GoldenDataset:
    return GoldenDataset(
        goldenDatasetId=dataset_id,
        name="Demo golden set",
        version=1,
        cases=[{"caseId": "c1", "input": "hi", "evaluationRule": "contains:hi"}],
        provenance=DatasetProvenance.CURATED,
        reviewStatus=ReviewStatus.REVIEWED,
        createdAt=datetime(2026, 8, 19, tzinfo=UTC),
    )


def test_list_golden_datasets_returns_summaries() -> None:
    rows = [_golden_dataset("golden-demo-v1")]
    client = _client(FakeSession(rows))

    response = client.get("/golden-datasets", headers={"X-Demo-User": "presenter@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["goldenDatasets"][0]["goldenDatasetId"] == "golden-demo-v1"
    assert body["goldenDatasets"][0]["reviewStatus"] == "reviewed"
    assert body["goldenDatasets"][0]["caseCount"] == 1


def test_list_benchmark_definitions_returns_summaries() -> None:
    rows = [BenchmarkDefinition(benchmarkId="gsm8k", version="1.0")]
    client = _client(FakeSession(rows))

    response = client.get(
        "/benchmark-definitions", headers={"X-Demo-User": "presenter@example.com"}
    )

    assert response.status_code == 200
    assert response.json()["benchmarkDefinitions"] == [{"benchmarkId": "gsm8k", "version": "1.0"}]


def test_list_performance_workloads_returns_summaries() -> None:
    rows = [PerformanceWorkload(workloadId="perf-demo-v1", version=1, concurrency=4)]
    client = _client(FakeSession(rows))

    response = client.get(
        "/performance-workloads", headers={"X-Demo-User": "presenter@example.com"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["performanceWorkloads"] == [
        {"workloadId": "perf-demo-v1", "version": 1, "concurrency": 4}
    ]


def test_list_runs_returns_runs_for_environment() -> None:
    now = datetime(2026, 8, 19, tzinfo=UTC)
    environment = DemoEnvironment(
        environmentId="env-123",
        profileId="azure-single-gpu-3b",
        provider=ProviderType.AZURE,
        region="eastus2",
        lifecycleState=DemoEnvironmentState.READY,
        providerState={},
        createdBy="presenter@example.com",
        lastModifiedBy="presenter@example.com",
        createdAt=now,
        updatedAt=now,
    )
    run = ExperimentRun(
        runId="run-1",
        deploymentRevisionId="dep-1",
        runType=ExperimentRunType.QUALITY_GOLDEN,
        testDefinitionRef="golden-demo-v1",
        status=ExperimentRunStatus.COMPLETED,
        environmentContextSnapshot={},
        startedAt=now,
        diagnostics=[],
        cancellationRequests=[],
        retentionClass=RetentionClass.PERSISTED,
    )
    session = FakeSession([run], get_map={(DemoEnvironment, "env-123"): environment})
    client = _client(session)

    response = client.get(
        "/environments/env-123/runs", headers={"X-Demo-User": "presenter@example.com"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["runs"][0]["runId"] == "run-1"
    assert body["runs"][0]["status"] == "completed"


def test_list_runs_returns_404_for_missing_environment() -> None:
    session = FakeSession([], get_map={})
    client = _client(session)

    response = client.get(
        "/environments/env-missing/runs", headers={"X-Demo-User": "presenter@example.com"}
    )

    assert response.status_code == 404
