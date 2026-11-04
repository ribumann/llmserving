from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DeploymentRevisionState
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.evaluation.run_quality import QualityRunOrchestrator
from src.performance.llmperf_runner import PerformanceRunOverloadError
from src.persistence.db import get_db_session
from tests.support.demo_backend import FakeProvider, MemorySession, MemorySessionContext


class ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


class OverloadPerformanceRunner:
    def run(self, *, engine, deployment_revision_id: str, workload):  # noqa: ANN001
        _ = (engine, deployment_revision_id, workload)
        raise PerformanceRunOverloadError(
            "Synthetic overload",
            partial_result={
                "runner": "llmperf",
                "metrics": {
                    "timeToFirstTokenMs": {"p50": 25.0, "p95": 40.0},
                    "interTokenLatencyMs": {"p50": 4.0, "p95": 6.5},
                    "endToEndLatencyMs": {"p50": 90.0, "p95": 120.0},
                    "throughputTokensPerSec": 70.0,
                },
                "requestFailures": {"count": 6, "total": 10, "rate": 0.6},
                "units": {
                    "timeToFirstTokenMs": "ms",
                    "interTokenLatencyMs": "ms",
                    "endToEndLatencyMs": "ms",
                    "throughputTokensPerSec": "tokens/sec",
                },
                "testConditions": {
                    "warmup": {"requestCount": 2},
                    "inputProfile": {
                        "meanInputTokens": 128,
                        "stddevInputTokens": 16,
                        "meanOutputTokens": 64,
                        "stddevOutputTokens": 8,
                    },
                    "concurrency": 2,
                    "durationOrRequestCount": {"requestCount": 10},
                    "safetyLimits": {"maxConcurrency": 8, "maxRequests": 20},
                    "completionCriteria": {"targetCompletedRequests": 10},
                },
                "acceleratorUtilization": {
                    "available": False,
                    "details": None,
                },
            },
        )


class NoDataOverloadPerformanceRunner:
    """Simulates a runner that crashes before capturing any usable metrics."""

    def run(self, *, engine, deployment_revision_id: str, workload):  # noqa: ANN001
        _ = (engine, deployment_revision_id, workload)
        raise PerformanceRunOverloadError(
            "LLMPerf crashed before producing any output.",
            partial_result=None,
        )


def _prepare_ready_deployment(session: MemorySession) -> None:
    now = datetime.now(UTC)
    session.model_configurations["env-demo-model-1"] = ModelConfiguration(
        modelConfigId="env-demo-model-1",
        environmentId="env-demo",
        catalogEntryId="qwen3-4b",
        resolvedCheckpointRef="Qwen/Qwen3-4B@main",
        modelSettings={"revisionLabel": "v1"},
        version=1,
        createdBy="presenter@example.com",
        createdAt=now,
    )
    session.inference_configurations["env-demo-inference-1"] = InferenceConfiguration(
        inferenceConfigId="env-demo-inference-1",
        environmentId="env-demo",
        engineId="vllm",
        servingSettings={"gpu_memory_utilization": 0.9},
        generationSettings={"temperature": 0.2},
        version=1,
        createdBy="presenter@example.com",
        createdAt=now,
    )
    session.deployment_revisions["env-demo-deployment-1"] = DeploymentRevision(
        deploymentRevisionId="env-demo-deployment-1",
        environmentId="env-demo",
        modelConfigId="env-demo-model-1",
        inferenceConfigId="env-demo-inference-1",
        engineId="vllm",
        lifecycleState=DeploymentRevisionState.READY,
        activePeriod={"startedAt": now.isoformat(), "endedAt": None},
        health={"status": "healthy", "diagnostics": []},
        createdBy="presenter@example.com",
        createdAt=now,
    )
    session.environments["env-demo"].activeDeploymentRevisionId = "env-demo-deployment-1"


def test_performance_overload_is_incomplete_and_preserves_partial_results() -> None:
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)

    app = create_app()
    app.state.provider_adapter = FakeProvider(session)
    app.state.session_factory = lambda: MemorySessionContext(session)
    app.state.telemetry = None
    app.state.quality_run_orchestrator = QualityRunOrchestrator(
        session_factory=app.state.session_factory,
        provider=app.state.provider_adapter,
        telemetry=None,
        performance_runner=OverloadPerformanceRunner(),
        executor=ImmediateExecutor(),
    )

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    client = TestClient(app)
    headers = {"X-Demo-User": "presenter@example.com"}

    create = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "performance", "testDefinitionRef": "workload-default"},
    )
    assert create.status_code == 202
    run_id = create.json()["runId"]

    run = client.get(f"/environments/env-demo/runs/{run_id}", headers=headers)
    assert run.status_code == 200
    assert run.json()["status"] == "incomplete"

    report = client.get(f"/environments/env-demo/runs/{run_id}/report", headers=headers)
    assert report.status_code == 200
    payload = report.json()
    assert payload["completenessIndicator"] == "partial"
    assert payload["performance"]["metrics"]["throughputTokensPerSec"] == 70.0
    assert payload["performance"]["requestFailures"] == {"count": 6, "total": 10, "rate": 0.6}


def test_performance_overload_with_no_partial_data_is_failed_not_incomplete() -> None:
    """A crash before any metrics are captured must be FAILED, never a silent INCOMPLETE."""
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)

    app = create_app()
    app.state.provider_adapter = FakeProvider(session)
    app.state.session_factory = lambda: MemorySessionContext(session)
    app.state.telemetry = None
    app.state.quality_run_orchestrator = QualityRunOrchestrator(
        session_factory=app.state.session_factory,
        provider=app.state.provider_adapter,
        telemetry=None,
        performance_runner=NoDataOverloadPerformanceRunner(),
        executor=ImmediateExecutor(),
    )

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    client = TestClient(app)
    headers = {"X-Demo-User": "presenter@example.com"}

    create = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "performance", "testDefinitionRef": "workload-default"},
    )
    assert create.status_code == 202
    run_id = create.json()["runId"]

    run = client.get(f"/environments/env-demo/runs/{run_id}", headers=headers)
    assert run.status_code == 200
    assert run.json()["status"] == "failed"

    report = client.get(f"/environments/env-demo/runs/{run_id}/report", headers=headers)
    assert report.status_code == 200
    payload = report.json()
    assert payload["performance"] is None
