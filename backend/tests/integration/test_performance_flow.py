from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import src.performance.llmperf_runner as runner_module
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DeploymentRevisionState
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.engines.vllm.adapter import VllmEngineAdapter
from src.engines.vllm.performance import VllmPerformanceRunner
from src.evaluation.run_quality import QualityRunOrchestrator
from src.performance.llmperf_runner import LlmPerfRunner
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


@pytest.mark.integration
@pytest.mark.parametrize("duration_warmup", [False, True])
def test_performance_flow_runs_workload_end_to_end(monkeypatch, duration_warmup) -> None:
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)
    if duration_warmup:
        session.performance_workloads["workload-default"].warmup = {"durationSeconds": 2}
    clock = [0.0]
    monkeypatch.setattr(runner_module, "monotonic", lambda: clock[0])
    phases = []

    def evaluator(**kwargs):
        if kwargs["workload"].get("_warmupPhase"):
            phases.append("warmup")
            clock[0] += 1
            count = kwargs["workload"]["durationOrRequestCount"]["requestCount"]
            return {
                "results_num_completed_requests": count,
                "results_num_requests_started": count,
                "results_number_errors": 0,
            }
        phases.append("measured")
        return {
            "metrics": {
                "timeToFirstTokenMs": {"p50": 15.5, "p95": 22.0},
                "interTokenLatencyMs": {"p50": 2.2, "p95": 3.9},
                "endToEndLatencyMs": {"p50": 48.0, "p95": 63.0},
                "throughputTokensPerSec": 188.4,
            },
            "requestFailures": {"count": 1, "total": 20, "rate": 0.05},
            "units": {
                "timeToFirstTokenMs": "ms",
                "interTokenLatencyMs": "ms",
                "endToEndLatencyMs": "ms",
                "throughputTokensPerSec": "tokens/sec",
            },
        }

    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(
                200,
                text=(
                    "# TYPE DCGM_FI_DEV_GPU_UTIL gauge\n"
                    'DCGM_FI_DEV_GPU_UTIL{gpu="0"} 76\n'
                    'DCGM_FI_DEV_GPU_UTIL{gpu="1"} 82\n'
                ),
            )
            if request.url.path.endswith("/metrics")
            else httpx.Response(404)
        )
    )
    http_client = httpx.Client(transport=transport)
    engine = VllmEngineAdapter(
        http_client=http_client,
        session_factory=lambda: MemorySessionContext(session),
        performance_runner=VllmPerformanceRunner(
            http_client=http_client,
            llmperf_runner=LlmPerfRunner(evaluator=evaluator),
        ),
    )

    app = create_app()
    app.state.provider_adapter = FakeProvider(session, engine_adapter=engine)
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
    client = TestClient(app)
    headers = {"X-Demo-User": "presenter@example.com"}

    create = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "performance", "testDefinitionRef": "workload-default"},
    )
    assert create.status_code == 202

    report = client.get(
        f"/environments/env-demo/runs/{create.json()['runId']}/report",
        headers=headers,
    )
    assert report.status_code == 200
    payload = report.json()["performance"]
    assert payload["metrics"]["timeToFirstTokenMs"] == {"p50": 15.5, "p95": 22.0}
    assert payload["metrics"]["throughputTokensPerSec"] == 188.4
    assert payload["requestFailures"] == {"count": 1, "total": 20, "rate": 0.05}
    if duration_warmup:
        assert phases == ["warmup", "warmup", "measured"]
        assert payload["testConditions"]["warmupExecution"] == {
            "completedRequests": 2,
            "failedRequests": 0,
            "elapsedSeconds": 2,
        }
    else:
        assert phases == ["warmup", "measured"]
        assert payload["testConditions"]["warmupExecution"] == {
            "completedRequests": 2,
            "failedRequests": 0,
        }
    assert payload["acceleratorUtilization"] == {
        "available": True,
        "details": {
            "metric": "DCGM_FI_DEV_GPU_UTIL",
            "average": 79.0,
            "max": 82.0,
            "samples": [76.0, 82.0],
        },
    }
