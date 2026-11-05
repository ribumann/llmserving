from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.evaluation.lm_eval_runner import LmEvalRunner
from src.evaluation.run_quality import QualityRunOrchestrator
from src.persistence.db import get_db_session
from tests.integration.test_performance_flow import _prepare_ready_deployment
from tests.support.demo_backend import FakeProvider, MemorySession, MemorySessionContext

pytestmark = pytest.mark.integration
HEADERS = {"X-Demo-User": "presenter@example.com"}


class DeferredExecutor:
    def submit(self, fn, *args, **kwargs):
        self.pending = (fn, args, kwargs)
        return None

    def execute(self):
        fn, args, kwargs = self.pending
        fn(*args, **kwargs)


@pytest.fixture
def queued_runner():
    session = MemorySession()
    session.seed_defaults()
    _prepare_ready_deployment(session)
    session.golden_datasets["golden-default"].cases = [
        {
            "caseId": "frozen-case",
            "input": "original",
            "evaluationRule": "exact-match",
            "expectedOutput": "echo:original",
            "parameters": {"temperature": 0.1},
        }
    ]
    session.benchmark_definitions["gsm8k"].presentationSubset["taskKwargs"] = {"limit": 2}
    session.environments["env-demo"].providerState["nested"] = {"retained": True}
    provider = FakeProvider(session)
    engine = provider.get_engine_adapter("vllm")
    engine.submitPromptWithParameters = MagicMock(wraps=engine.submitPromptWithParameters)
    engine.runPerformanceWorkload = MagicMock(wraps=engine.runPerformanceWorkload)
    provider.get_engine_adapter = lambda _engine_id: engine
    evaluate = MagicMock(return_value={"results": {"gsm8k": {"exact_match,strict-match": 0.83}}})
    executor = DeferredExecutor()
    app = create_app()
    app.state.provider_adapter = provider
    app.state.session_factory = lambda: MemorySessionContext(session)
    app.state.telemetry = None
    app.state.quality_run_orchestrator = QualityRunOrchestrator(
        session_factory=app.state.session_factory,
        provider=provider,
        benchmark_runner=LmEvalRunner(evaluator=evaluate),
        executor=executor,
    )

    def database():
        yield session

    app.dependency_overrides[get_db_session] = database
    return TestClient(app), session, executor, engine, evaluate


@pytest.mark.parametrize(
    "run_type,reference",
    [
        ("quality-golden", "golden-default"),
        ("quality-benchmark", "gsm8k"),
        ("performance", "workload-default"),
    ],
)
@pytest.mark.parametrize("remove", [False, True])
def test_queued_execution_uses_accepted_definition_not_current_catalog(
    queued_runner, run_type, reference, remove
) -> None:
    client, session, executor, engine, evaluate = queued_runner
    accepted = client.post(
        "/environments/env-demo/runs",
        headers=HEADERS,
        json={"runType": run_type, "testDefinitionRef": reference},
    )
    assert accepted.status_code == 202
    run_id = accepted.json()["runId"]
    snapshot = deepcopy(session.experiment_runs[run_id].environmentContextSnapshot)
    session.environments["env-demo"].providerState["nested"]["retained"] = False
    if run_type == "quality-golden":
        catalog = session.golden_datasets
        catalog[reference].cases[0]["input"] = "changed"
        catalog[reference].cases[0]["expectedOutput"] = "not the original answer"
        catalog[reference].cases[0]["parameters"]["temperature"] = 0.9
    elif run_type == "quality-benchmark":
        catalog = session.benchmark_definitions
        catalog[reference].presentationSubset["task"] = "changed"
        catalog[reference].passFailThreshold["baselineScore"] = 100.0
        catalog[reference].presentationSubset["taskKwargs"]["limit"] = 999
        catalog[reference].version = "changed"
    else:
        catalog = session.performance_workloads
        catalog[reference].inputProfile["meanInputTokens"] = 999
        catalog[reference].concurrency = 32
        catalog[reference].version = 999
    if remove:
        del catalog[reference]

    executor.execute()

    saved = session.experiment_runs[run_id]
    assert saved.status.value == "completed"
    assert saved.environmentContextSnapshot == snapshot
    if run_type == "quality-golden":
        engine.submitPromptWithParameters.assert_called_once_with(
            saved.deploymentRevisionId, "original", {"temperature": 0.1}
        )
    elif run_type == "quality-benchmark":
        assert evaluate.call_args.kwargs["tasks"] == ["gsm8k"]
        assert evaluate.call_args.kwargs["limit"] == 2
        report = client.get(f"/environments/env-demo/runs/{run_id}/report", headers=HEADERS).json()
        assert (
            report["quality"]["benchmarks"][0]["version"] == snapshot["testDefinition"]["version"]
        )
        assert report["quality"]["benchmarks"][0]["baseline"] == 75.0
    else:
        assert engine.runPerformanceWorkload.call_args.args[1] == snapshot["testDefinition"]


@pytest.mark.parametrize(
    "run_type,reference,identity_key",
    [
        ("quality-golden", "golden-default", "goldenDatasetId"),
        ("quality-benchmark", "gsm8k", "benchmarkId"),
        ("performance", "workload-default", "workloadId"),
    ],
)
@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_mismatched_snapshot_fails_without_reading_current_catalog(
    queued_runner, run_type, reference, identity_key, missing
) -> None:
    client, session, executor, engine, evaluate = queued_runner
    accepted = client.post(
        "/environments/env-demo/runs",
        headers=HEADERS,
        json={"runType": run_type, "testDefinitionRef": reference},
    )
    assert accepted.status_code == 202
    run = session.experiment_runs[accepted.json()["runId"]]
    if missing:
        del run.environmentContextSnapshot["testDefinition"]
    else:
        run.environmentContextSnapshot["testDefinition"][identity_key] = "not-this-definition"

    executor.execute()

    assert run.status.value == "failed"
    assert any("snapshot" in item["message"] for item in run.diagnostics)
    assert session.environments["env-demo"].activeOperationId is None
    engine.submitPromptWithParameters.assert_not_called()
    engine.runPerformanceWorkload.assert_not_called()
    evaluate.assert_not_called()


def test_benchmark_model_uses_accepted_snapshot(queued_runner) -> None:
    client, session, executor, _engine, evaluate = queued_runner
    accepted = client.post(
        "/environments/env-demo/runs",
        headers=HEADERS,
        json={"runType": "quality-benchmark", "testDefinitionRef": "gsm8k"},
    )
    assert accepted.status_code == 202
    run = session.experiment_runs[accepted.json()["runId"]]
    expected = run.environmentContextSnapshot["modelConfiguration"]["resolvedCheckpointRef"]
    session.model_configurations["env-demo-model-1"].resolvedCheckpointRef = "changed"

    executor.execute()

    assert run.status.value == "completed"
    assert evaluate.call_args.kwargs["model_args"]["model"] == expected
