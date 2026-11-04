from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.benchmark_definition import BenchmarkDefinition
from src.domain.enums import DatasetProvenance, DuplicateCheckState, ReviewStatus
from src.domain.golden_dataset import GoldenDataset
from src.evaluation.lm_eval_runner import LmEvalRunner
from src.evaluation.run_quality import QualityRunOrchestrator
from src.persistence.db import get_db_session
from tests.support.demo_backend import FakeProvider, MemorySession, MemorySessionContext


class ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


@pytest.mark.integration
def test_quality_flow_runs_golden_and_benchmark() -> None:
    app = create_app()
    session = MemorySession()
    session.seed_defaults()
    app.state.provider_adapter = FakeProvider(session)
    app.state.session_factory = lambda: MemorySessionContext(session)
    app.state.telemetry = None
    app.state.quality_run_orchestrator = QualityRunOrchestrator(
        session_factory=app.state.session_factory,
        provider=app.state.provider_adapter,
        telemetry=None,
        benchmark_runner=LmEvalRunner(
            evaluator=lambda **_kwargs: {"results": {"gsm8k": {"exact_match,strict-match": 0.83}}}
        ),
        executor=ImmediateExecutor(),
    )

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    client = TestClient(app)
    headers = {"X-Demo-User": "presenter@example.com"}

    model = client.post(
        "/environments/env-demo/model-configurations",
        headers=headers,
        json={
            "catalogEntryId": "qwen3-4b",
            "resolvedCheckpointRef": "Qwen/Qwen3-4B@main",
            "modelSettings": {"revisionLabel": "v1"},
        },
    ).json()
    inference = client.post(
        "/environments/env-demo/inference-configurations",
        headers=headers,
        json={
            "engineId": "vllm",
            "servingSettings": {"gpu_memory_utilization": 0.9},
            "generationSettings": {"temperature": 0.2},
        },
    ).json()
    client.post(
        "/environments/env-demo/deployments",
        headers=headers,
        json={
            "modelConfigId": model["modelConfigId"],
            "inferenceConfigId": inference["inferenceConfigId"],
        },
    )

    session.prompt_responses.update(
        {
            "alpha": "gold:alpha",
            "beta": "missing",
        }
    )
    session.prompt_errors["gamma"] = "synthetic error"
    session.golden_datasets["golden-flow"] = GoldenDataset(
        goldenDatasetId="golden-flow",
        name="Golden Flow",
        version=1,
        cases=[
            {
                "caseId": "case-pass",
                "input": "alpha",
                "evaluationRule": "exact-match",
                "expectedOutput": "gold:alpha",
            },
            {
                "caseId": "case-fail",
                "input": "beta",
                "evaluationRule": "contains",
                "expectedSubstring": "expected",
            },
            {
                "caseId": "case-error",
                "input": "gamma",
                "evaluationRule": "exact-match",
                "expectedOutput": "never",
            },
        ],
        duplicateCheckState=DuplicateCheckState.CLEAN,
        provenance=DatasetProvenance.CURATED,
        reviewStatus=ReviewStatus.REVIEWED,
        generationContext=None,
    )
    session.benchmark_definitions["gsm8k"] = BenchmarkDefinition(
        benchmarkId="gsm8k",
        version="presentation-50-seed-42",
        presentationSubset={"task": "gsm8k", "metric": "exact_match,strict-match"},
        passFailThreshold={"baselineScore": 75.0, "regressionThresholdPoints": 5.0},
    )

    golden = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "quality-golden", "testDefinitionRef": "golden-flow"},
    ).json()
    golden_report = client.get(
        f"/environments/env-demo/runs/{golden['runId']}/report",
        headers=headers,
    ).json()
    assert golden_report["quality"]["aggregate"] == {
        "totalCases": 3,
        "passed": 1,
        "failed": 1,
        "errored": 1,
        "skipped": 0,
        "incomplete": 0,
        "passRate": pytest.approx(1 / 3, rel=0, abs=0.0001),
    }

    benchmark = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "quality-benchmark", "testDefinitionRef": "gsm8k"},
    ).json()
    benchmark_report = client.get(
        f"/environments/env-demo/runs/{benchmark['runId']}/report",
        headers=headers,
    ).json()
    assert benchmark_report["quality"]["benchmarks"][0]["score"] == 83.0
    assert benchmark_report["quality"]["benchmarks"][0]["passFail"] == "pass"
