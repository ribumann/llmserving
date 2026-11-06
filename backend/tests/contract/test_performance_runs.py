from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DeploymentRevisionState
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.evaluation.run_quality import QualityRunOrchestrator
from src.persistence.db import get_db_session
from tests.support.demo_backend import FakeProvider, MemorySession, MemorySessionContext


class ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


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


def _build_client(session: MemorySession) -> TestClient:
    app = create_app()
    app.state.provider_adapter = FakeProvider(session)
    app.state.session_factory = lambda: MemorySessionContext(session)
    app.state.telemetry = None
    app.state.quality_run_orchestrator = QualityRunOrchestrator(
        session_factory=app.state.session_factory,
        provider=app.state.provider_adapter,
        telemetry=None,
        executor=ImmediateExecutor(),
    )

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    return TestClient(app)


def test_performance_run_routes_follow_contract() -> None:
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)
    client = _build_client(session)
    headers = {"X-Demo-User": "presenter@example.com"}

    create = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "performance", "testDefinitionRef": "workload-default"},
    )
    assert create.status_code == 202
    assert create.json()["status"] == "queued"
    run_id = create.json()["runId"]

    get_run = client.get(f"/environments/env-demo/runs/{run_id}", headers=headers)
    assert get_run.status_code == 200
    assert get_run.json()["status"] == "completed"
    assert get_run.json()["progress"] == {"totalCases": 1, "completedCases": 1}

    report = client.get(f"/environments/env-demo/runs/{run_id}/report", headers=headers)
    assert report.status_code == 200
    payload = report.json()
    assert payload["completenessIndicator"] == "complete"
    assert payload["quality"]["aggregate"] == {
        "totalCases": 1,
        "passed": 1,
        "failed": 0,
        "errored": 0,
        "skipped": 0,
        "incomplete": 0,
        "passRate": 1.0,
    }
    assert payload["performance"] == {
        "metrics": {
            "timeToFirstTokenMs": {"p50": 12.0, "p95": 20.0},
            "interTokenLatencyMs": {"p50": 2.0, "p95": 3.0},
            "endToEndLatencyMs": {"p50": 40.0, "p95": 55.0},
            "throughputTokensPerSec": 150.0,
        },
        "requestFailures": {"count": 0, "total": 10, "rate": 0.0},
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
        "acceleratorUtilization": {"available": False, "details": None},
        "runner": "llmperf",
    }


def test_performance_run_validation_errors_follow_contract() -> None:
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)
    session.performance_workloads["invalid-workload"] = session.performance_workloads[
        "workload-default"
    ].__class__(
        workloadId="invalid-workload",
        version=1,
        warmup={},
        inputProfile={},
        concurrency=0,
        durationOrRequestCount={},
        safetyLimits={},
        completionCriteria={},
    )
    client = _build_client(session)
    headers = {"X-Demo-User": "presenter@example.com"}

    invalid = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "performance", "testDefinitionRef": "invalid-workload"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_performance_workload"


@pytest.mark.parametrize(
    "warmup",
    [
        {"durationSeconds": 5},
        {"durationSeconds": 5, "requestCount": 2},
        {"requestCount": -1},
        {"requestCount": 1.5},
        {"requestCount": True},
    ],
)
def test_vllm_unsupported_warmup_is_rejected_before_run(warmup) -> None:
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)
    session.performance_workloads["workload-default"].warmup = warmup
    response = _build_client(session).post(
        "/environments/env-demo/runs",
        headers={"X-Demo-User": "presenter@example.com"},
        json={"runType": "performance", "testDefinitionRef": "workload-default"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_performance_workload"
    assert response.json()["error"]["details"]["field"] == "warmup"
