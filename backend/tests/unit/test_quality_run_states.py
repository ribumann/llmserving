from __future__ import annotations

from datetime import UTC, datetime

from src.domain.enums import (
    CompletenessIndicator,
    ExperimentRunStatus,
    ExperimentRunType,
    RetentionClass,
)
from src.domain.experiment_run import ExperimentRun
from src.domain.result_report_repo import ResultReportRepository
from src.evaluation.lm_eval_runner import LmEvalRunner
from src.evaluation.run_quality import QualityRunOrchestrator
from tests.support.demo_backend import FakeProvider, MemorySession, MemorySessionContext


class DeferredExecutor:
    def submit(self, fn, *args, **kwargs):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        return None


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
    report = ResultReportRepository().get_by_run_id(session, updated.runId)

    assert updated.status == ExperimentRunStatus.CANCELLED
    assert [case["status"] for case in report.quality["cases"]] == ["passed", "failed", "skipped"]
    assert report.quality["aggregate"]["passed"] == 1
    assert report.quality["aggregate"]["failed"] == 1
    assert report.quality["aggregate"]["skipped"] == 1
