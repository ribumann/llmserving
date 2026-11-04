from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.benchmark_definition import BenchmarkDefinition
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    DatasetProvenance,
    DeploymentRevisionState,
    DuplicateCheckState,
    ReviewStatus,
)
from src.domain.golden_dataset import GoldenDataset
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.evaluation.lm_eval_runner import LmEvalRunner
from src.evaluation.run_quality import QualityRunOrchestrator
from src.persistence.db import get_db_session
from tests.support.demo_backend import (
    FakeProvider,
    MemorySession,
    MemorySessionContext,
)


class ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


class DeferredExecutor:
    def submit(self, fn, *args, **kwargs):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        return None


def _benchmark_runner(score: float = 0.82) -> LmEvalRunner:
    def evaluator(**_kwargs):
        return {"results": {"gsm8k": {"exact_match,strict-match": score}}}

    return LmEvalRunner(evaluator=evaluator)


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


def _build_client(
    session: MemorySession,
    *,
    executor,
    benchmark_runner: LmEvalRunner | None = None,
    performance_runner=None,
) -> TestClient:
    app = create_app()
    app.state.provider_adapter = FakeProvider(session)
    app.state.session_factory = lambda: MemorySessionContext(session)
    app.state.telemetry = None
    app.state.quality_run_orchestrator = QualityRunOrchestrator(
        session_factory=app.state.session_factory,
        provider=app.state.provider_adapter,
        telemetry=None,
        benchmark_runner=benchmark_runner or _benchmark_runner(),
        performance_runner=performance_runner,
        executor=executor,
    )

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    return TestClient(app)


def test_quality_golden_run_routes_follow_contract() -> None:
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)
    session.golden_datasets["golden-contract"] = GoldenDataset(
        goldenDatasetId="golden-contract",
        name="Contract Golden",
        version=2,
        cases=[
            {
                "caseId": "case-1",
                "input": "alpha",
                "evaluationRule": "exact-match",
                "expectedOutput": "gold:alpha",
            }
        ],
        duplicateCheckState=DuplicateCheckState.CLEAN,
        provenance=DatasetProvenance.CURATED,
        reviewStatus=ReviewStatus.REVIEWED,
        generationContext=None,
    )
    session.prompt_responses["alpha"] = "gold:alpha"
    client = _build_client(session, executor=ImmediateExecutor())
    headers = {"X-Demo-User": "presenter@example.com"}

    create = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "quality-golden", "testDefinitionRef": "golden-contract"},
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
    body = report.json()
    assert body["quality"]["cases"] == [
        {
            "caseId": "case-1",
            "input": "alpha",
            "evaluationRule": "exact-match",
            "observedOutcome": "gold:alpha",
            "status": "passed",
        }
    ]
    assert body["quality"]["aggregate"]["passRate"] == 1.0
    assert body["quality"]["benchmarks"] == []
    assert body["performance"] is None


def test_quality_benchmark_run_routes_follow_contract() -> None:
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)
    session.benchmark_definitions["gsm8k"] = BenchmarkDefinition(
        benchmarkId="gsm8k",
        version="presentation-50-seed-42",
        presentationSubset={"task": "gsm8k", "metric": "exact_match,strict-match"},
        passFailThreshold={"baselineScore": 75.0, "regressionThresholdPoints": 5.0},
    )
    client = _build_client(
        session,
        executor=ImmediateExecutor(),
        benchmark_runner=_benchmark_runner(),
    )
    headers = {"X-Demo-User": "presenter@example.com"}

    create = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "quality-benchmark", "testDefinitionRef": "gsm8k"},
    )
    assert create.status_code == 202
    run_id = create.json()["runId"]

    report = client.get(f"/environments/env-demo/runs/{run_id}/report", headers=headers)
    assert report.status_code == 200
    benchmark = report.json()["quality"]["benchmarks"][0]
    assert benchmark["benchmarkId"] == "gsm8k"
    assert benchmark["passFail"] == "pass"
    assert benchmark["regressionFlag"] is False


def test_quality_run_error_contracts() -> None:
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)
    client = _build_client(session, executor=ImmediateExecutor())
    headers = {"X-Demo-User": "presenter@example.com"}

    invalid = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "unknown", "testDefinitionRef": "golden-default"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_run_type"

    performance_missing = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "performance", "testDefinitionRef": "missing-workload"},
    )
    assert performance_missing.status_code == 404
    assert performance_missing.json()["error"]["code"] == "test_definition_not_found"

    missing = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "quality-golden", "testDefinitionRef": "missing"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "test_definition_not_found"

    session.environments["env-demo"].activeOperationId = "other-op"
    busy = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "quality-golden", "testDefinitionRef": "golden-default"},
    )
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "environment_busy"
    session.environments["env-demo"].activeOperationId = None

    session.environments["env-demo"].activeDeploymentRevisionId = None
    no_ready = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "quality-golden", "testDefinitionRef": "golden-default"},
    )
    assert no_ready.status_code == 409
    assert no_ready.json()["error"]["code"] == "no_ready_deployment"

    missing_run = client.get("/environments/env-demo/runs/missing-run", headers=headers)
    assert missing_run.status_code == 404
    assert missing_run.json()["error"]["code"] == "run_not_found"


def test_cancel_route_is_idempotent_and_report_waits_for_terminal_state() -> None:
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)
    deferred = DeferredExecutor()
    client = _build_client(session, executor=deferred)
    headers = {"X-Demo-User": "presenter@example.com"}

    create = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "quality-golden", "testDefinitionRef": "golden-default"},
    )
    run_id = create.json()["runId"]

    pending_report = client.get(f"/environments/env-demo/runs/{run_id}/report", headers=headers)
    assert pending_report.status_code == 409
    assert pending_report.json()["error"]["code"] == "report_not_ready"

    cancel = client.post(f"/environments/env-demo/runs/{run_id}/cancel", headers=headers)
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    assert len(cancel.json()["cancellationRequests"]) == 1

    cancel_again = client.post(f"/environments/env-demo/runs/{run_id}/cancel", headers=headers)
    assert cancel_again.status_code == 200
    assert cancel_again.json()["status"] == "cancelled"
    assert cancel_again.json()["cancellationRequests"] == cancel.json()["cancellationRequests"]
