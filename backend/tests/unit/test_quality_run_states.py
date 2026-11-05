from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from src.domain.enums import (
    CompletenessIndicator,
    ExperimentRunStatus,
    ExperimentRunType,
    RetentionClass,
)
from src.domain.experiment_run import ExperimentRun
from src.domain.result_report_repo import ResultReportRepository
from src.evaluation.lm_eval_runner import LmEvalRunner
from src.evaluation.run_quality import QualityRunContext, QualityRunOrchestrator
from tests.support.demo_backend import FakeProvider, MemorySession, MemorySessionContext


class DeferredExecutor:
    def submit(self, fn, *args, **kwargs):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        return None


def _orchestrator(session: MemorySession) -> QualityRunOrchestrator:
    return QualityRunOrchestrator(
        session_factory=lambda: MemorySessionContext(session),
        provider=FakeProvider(session),
        executor=DeferredExecutor(),
    )


def _running_run(session: MemorySession, run_type=ExperimentRunType.QUALITY_GOLDEN):
    run = ExperimentRun(
        runId="env-demo-run-1",
        deploymentRevisionId="env-demo-deployment-1",
        runType=run_type,
        testDefinitionRef="golden-default",
        status=ExperimentRunStatus.RUNNING,
        environmentContextSnapshot={},
        startedAt=datetime.now(UTC),
        endedAt=None,
        diagnostics=[],
        cancellationRequests=[],
        retentionClass=RetentionClass.PERSISTED,
    )
    session.add(run)
    session.environments["env-demo"].activeOperationId = run.runId
    return run


@pytest.mark.parametrize(
    "run_type",
    [
        ExperimentRunType.QUALITY_GOLDEN,
        ExperimentRunType.QUALITY_BENCHMARK,
        ExperimentRunType.PERFORMANCE,
    ],
)
def test_worker_observes_persisted_cancellation_without_local_event(run_type) -> None:
    session = MemorySession()
    session.seed_defaults()
    run = _running_run(session, run_type)
    run.cancellationRequests = [{"requestedBy": "other-replica@example.com"}]
    worker = _orchestrator(session)

    assert worker._should_cancel(run.runId)
    assert run.status == ExperimentRunStatus.RUNNING


@pytest.mark.parametrize("status", [ExperimentRunStatus.QUEUED, ExperimentRunStatus.RUNNING])
def test_untracked_worker_keeps_lock_until_acknowledgement(status) -> None:
    session = MemorySession()
    session.seed_defaults()
    run = _running_run(session)
    run.status = status
    requester = _orchestrator(session)
    worker = _orchestrator(session)

    first = requester.cancel(run_id=run.runId, requested_by="presenter@example.com")
    requests = list(first.cancellationRequests)
    second = requester.cancel(run_id=run.runId, requested_by="presenter@example.com")

    assert second.status == status
    assert second.endedAt is None
    assert second.cancellationRequests == requests
    assert len(requests) == 1
    assert session.environments["env-demo"].activeOperationId == run.runId
    assert worker._should_cancel(run.runId)
    assert not requester._cancel_events


def test_known_worker_timeout_keeps_running_state_and_logs_pending_ack(caplog) -> None:
    session = MemorySession()
    session.seed_defaults()
    run = _running_run(session)
    requester = _orchestrator(session)
    future = Mock()
    future.cancel.return_value = False
    future.result.side_effect = TimeoutError("still running")
    requester._futures[run.runId] = future

    updated = requester.cancel(run_id=run.runId, requested_by="presenter@example.com")

    assert updated.status == ExperimentRunStatus.RUNNING
    assert session.environments["env-demo"].activeOperationId == run.runId
    assert "awaiting worker acknowledgement" in caplog.text
    future.result.assert_called_once_with(timeout=30)


def test_known_worker_failure_is_not_silently_ignored() -> None:
    session = MemorySession()
    session.seed_defaults()
    run = _running_run(session)
    requester = _orchestrator(session)
    future = Mock()
    future.cancel.return_value = False
    future.result.side_effect = RuntimeError("worker persistence failed")
    requester._futures[run.runId] = future

    with pytest.raises(RuntimeError, match="worker persistence failed"):
        requester.cancel(run_id=run.runId, requested_by="presenter@example.com")

    assert session.environments["env-demo"].activeOperationId == run.runId


@pytest.mark.parametrize(
    "run_type",
    [
        ExperimentRunType.QUALITY_GOLDEN,
        ExperimentRunType.QUALITY_BENCHMARK,
        ExperimentRunType.PERFORMANCE,
    ],
)
def test_prestart_persisted_cancellation_skips_inference(run_type) -> None:
    session = MemorySession()
    session.seed_defaults()
    run = _running_run(session, run_type)
    run.status = ExperimentRunStatus.QUEUED
    run.cancellationRequests = [{"requestedBy": "other-replica@example.com"}]
    worker = _orchestrator(session)
    worker._provider = Mock()

    worker._run(
        QualityRunContext(
            environmentId="env-demo",
            deploymentRevisionId=run.deploymentRevisionId,
            engineId="vllm",
            runId=run.runId,
            operationId=run.runId,
            actorEmail="presenter@example.com",
            runType=run_type,
            testDefinitionRef=run.testDefinitionRef,
            inferenceApiUrl="http://unused",
        )
    )

    assert run.status == ExperimentRunStatus.CANCELLED
    assert session.environments["env-demo"].activeOperationId is None
    worker._provider.get_engine_adapter.assert_not_called()


def test_cancelled_run_preserves_completed_failed_and_skipped_case_states() -> None:
    session = MemorySession()
    session.seed_defaults()
    run = ExperimentRun(
        runId="env-demo-run-1",
        deploymentRevisionId="env-demo-deployment-1",
        runType=ExperimentRunType.QUALITY_GOLDEN,
        testDefinitionRef="golden-default",
        status=ExperimentRunStatus.RUNNING,
        environmentContextSnapshot={},
        startedAt=datetime.now(UTC),
        endedAt=None,
        diagnostics=[],
        cancellationRequests=[],
        retentionClass=RetentionClass.PERSISTED,
    )
    session.add(run)
    session.environments["env-demo"].activeOperationId = run.runId
    ResultReportRepository().upsert(
        session,
        run_id=run.runId,
        quality={
            "cases": [
                {
                    "caseId": "case-pass",
                    "input": "alpha",
                    "evaluationRule": "exact-match",
                    "observedOutcome": "gold:alpha",
                    "status": "passed",
                },
                {
                    "caseId": "case-fail",
                    "input": "beta",
                    "evaluationRule": "contains",
                    "observedOutcome": "wrong",
                    "status": "failed",
                },
                {
                    "caseId": "case-pending",
                    "input": "gamma",
                    "evaluationRule": "exact-match",
                    "observedOutcome": "",
                    "status": "incomplete",
                },
            ],
            "aggregate": {
                "totalCases": 3,
                "passed": 1,
                "failed": 1,
                "errored": 0,
                "skipped": 0,
                "incomplete": 1,
                "passRate": 1 / 3,
            },
            "benchmarks": [],
        },
        performance=None,
        completeness_indicator=CompletenessIndicator.PARTIAL,
    )
    orchestrator = QualityRunOrchestrator(
        session_factory=lambda: MemorySessionContext(session),
        provider=FakeProvider(session),
        telemetry=None,
        benchmark_runner=LmEvalRunner(evaluator=lambda **_kwargs: {}),
        executor=DeferredExecutor(),
    )

    updated = orchestrator.cancel(run_id="env-demo-run-1", requested_by="presenter@example.com")
    assert updated.status == ExperimentRunStatus.RUNNING
    orchestrator._finish_cancelled(
        QualityRunContext(
            environmentId="env-demo",
            deploymentRevisionId=run.deploymentRevisionId,
            engineId="vllm",
            runId=run.runId,
            operationId=run.runId,
            actorEmail="presenter@example.com",
            runType=run.runType,
            testDefinitionRef=run.testDefinitionRef,
            inferenceApiUrl="http://inference",
        )
    )
    report = ResultReportRepository().get_by_run_id(session, updated.runId)

    assert updated.status == ExperimentRunStatus.CANCELLED
    assert [case["status"] for case in report.quality["cases"]] == ["passed", "failed", "skipped"]
    assert report.quality["aggregate"]["passed"] == 1
    assert report.quality["aggregate"]["failed"] == 1
    assert report.quality["aggregate"]["skipped"] == 1
