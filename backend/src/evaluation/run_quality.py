from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Lock
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from src.domain.benchmark_definition import BenchmarkDefinition
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    CompletenessIndicator,
    ExperimentRunStatus,
    ExperimentRunType,
)
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import (
    EnvironmentLockedError,
    EnvironmentLockService,
    EnvironmentNotFoundError,
)
from src.domain.experiment_run import ExperimentRun
from src.domain.golden_dataset import GoldenDataset
from src.domain.model_configuration import ModelConfiguration
from src.domain.performance_workload import PerformanceWorkload
from src.domain.result_report_repo import ResultReportRepository, build_quality_aggregate
from src.evaluation.lm_eval_runner import LmEvalRunner
from src.evaluation.scoring import evaluate_golden_case, strip_reasoning_trace
from src.performance.llmperf_runner import PerformanceRunOverloadError
from src.performance.run_performance import PerformanceRunner

ACTIVE_STATUSES = {ExperimentRunStatus.QUEUED, ExperimentRunStatus.RUNNING}
TERMINAL_STATUSES = {
    ExperimentRunStatus.COMPLETED,
    ExperimentRunStatus.CANCELLED,
    ExperimentRunStatus.FAILED,
    ExperimentRunStatus.INCOMPLETE,
}
ALLOWED_TRANSITIONS = {
    ExperimentRunStatus.QUEUED: {
        ExperimentRunStatus.RUNNING,
        ExperimentRunStatus.CANCELLED,
        ExperimentRunStatus.FAILED,
    },
    ExperimentRunStatus.RUNNING: {
        ExperimentRunStatus.COMPLETED,
        ExperimentRunStatus.CANCELLED,
        ExperimentRunStatus.FAILED,
        ExperimentRunStatus.INCOMPLETE,
    },
}


@dataclass(slots=True, frozen=True)
class QualityRunContext:
    environmentId: str
    deploymentRevisionId: str
    engineId: str
    runId: str
    operationId: str
    actorEmail: str
    runType: ExperimentRunType
    testDefinitionRef: str
    inferenceApiUrl: str


class QualityRunOrchestrator:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | Any,
        provider: Any,
        telemetry: Any | None = None,
        benchmark_runner: LmEvalRunner | None = None,
        performance_runner: PerformanceRunner | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._telemetry = telemetry
        self._benchmark_runner = benchmark_runner or LmEvalRunner()
        self._performance_runner = performance_runner or PerformanceRunner()
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="quality-run"
        )
        self._environment_lock_service = EnvironmentLockService()
        self._report_repo = ResultReportRepository()
        self._cancel_events: dict[str, Event] = {}
        self._futures: dict[str, Future] = {}
        self._cancel_lock = Lock()

    def submit(self, context: QualityRunContext) -> None:
        with self._cancel_lock:
            self._cancel_events.setdefault(context.runId, Event())
        future = self._executor.submit(self._run, context)
        with self._cancel_lock:
            self._futures[context.runId] = future

    def cancel(self, *, run_id: str, requested_by: str) -> ExperimentRun:
        with self._session_factory() as session:
            run = session.get(ExperimentRun, run_id)
            if run is None:
                raise LookupError(run_id)
            if run.status in TERMINAL_STATUSES:
                return run

            if not run.cancellationRequests:
                run.cancellationRequests = [
                    {
                        "requestedAt": datetime.now(UTC).isoformat(),
                        "requestedBy": requested_by,
                    }
                ]
                run.diagnostics = [
                    *list(run.diagnostics or []),
                    self._diagnostic("warning", "Cancellation requested by operator."),
                ]
                session.add(run)
                session.commit()

        # Signal cancellation and, if a background worker actually owns this run,
        # wait for it to observe the signal and perform its own terminal
        # transition + lock release. This avoids releasing the environment lock
        # (or flipping run status) here in the request thread while the worker
        # may still be mid-flight against the same deployment/engine.
        self._signal_cancel(run_id)
        with self._cancel_lock:
            future = self._futures.get(run_id)

        if future is not None:
            try:
                future.result(timeout=30)
            except Exception:
                pass  # best-effort: fall through and report whatever state resulted

        with self._session_factory() as session:
            run = session.get(ExperimentRun, run_id)
            if future is None and run is not None and run.status not in TERMINAL_STATUSES:
                # No real background worker is tracked for this run (e.g. it never
                # started, or a synchronous test double already returned before
                # this point) — safe to finish the cancellation directly here.
                self._synchronously_cancel(session, run, requested_by=requested_by)
            return run

    def _synchronously_cancel(
        self, session: Session, run: ExperimentRun, *, requested_by: str
    ) -> None:
        run.status = ExperimentRunStatus.CANCELLED
        if run.endedAt is None:
            run.endedAt = datetime.now(UTC)
        session.add(run)

        report = self._report_repo.get_by_run_id(session, run.runId)
        if report is not None:
            quality = dict(report.quality or {})
            if quality.get("cases"):
                cases = [dict(case) for case in quality.get("cases") or []]
                for case in cases:
                    if case.get("status") == "incomplete":
                        case["status"] = "skipped"
                        case["observedOutcome"] = "Skipped after cancellation."
                quality["cases"] = cases
                quality["aggregate"] = build_quality_aggregate(
                    [str(case.get("status") or "incomplete") for case in cases]
                )
            else:
                aggregate = dict(quality.get("aggregate") or {})
                total = int(aggregate.get("totalCases") or 0)
                if total:
                    quality["aggregate"] = {
                        "totalCases": total,
                        "passed": 0,
                        "failed": 0,
                        "errored": 0,
                        "skipped": total,
                        "incomplete": 0,
                        "passRate": 0.0,
                    }
            completeness = self._completeness_indicator(quality)
            self._report_repo.upsert(
                session,
                run_id=run.runId,
                quality=quality,
                performance=report.performance,
                completeness_indicator=completeness,
                reference_execution_profile_ref=report.referenceExecutionProfileRef,
            )

        self._sync_environment(
            session,
            environment_id=self._environment_id_for_run(session, run),
            operation_id=run.runId,
            phase="cancelled",
            state=run.status.value,
            actor_email=requested_by,
            release_lock=True,
        )
        session.commit()

    def _run(self, context: QualityRunContext) -> None:
        try:
            with self._session_factory() as session:
                existing = session.get(ExperimentRun, context.runId)
                if existing is None or existing.status in TERMINAL_STATUSES:
                    # Already finalized (e.g. cancelled while still queued) before
                    # this worker got scheduled — nothing left to do.
                    return
            self._set_status(context=context, status=ExperimentRunStatus.RUNNING, phase="running")
            if context.runType == ExperimentRunType.QUALITY_GOLDEN:
                self._run_golden(context)
            elif context.runType == ExperimentRunType.QUALITY_BENCHMARK:
                self._run_benchmark(context)
            elif context.runType == ExperimentRunType.PERFORMANCE:
                self._run_performance(context)
        except Exception as exc:  # pragma: no cover - asserted via tests through state
            self._fail_run(context=context, exc=exc)
        finally:
            with self._cancel_lock:
                self._cancel_events.pop(context.runId, None)
                self._futures.pop(context.runId, None)

    def _run_golden(self, context: QualityRunContext) -> None:
        with self._session_factory() as session:
            dataset = session.get(GoldenDataset, context.testDefinitionRef)
            if dataset is None:
                raise RuntimeError("Golden dataset run context was not persisted.")
            cases = [dict(case) for case in list(dataset.cases or [])]

        engine = self._provider.get_engine_adapter(context.engineId)
        for index, case in enumerate(cases):
            if self._should_cancel(context.runId):
                self._finish_cancelled(context)
                return

            prompt_input = str(case["input"])
            parameters = dict(case.get("parameters") or {})
            try:
                if hasattr(engine, "submitPromptWithParameters"):
                    response = engine.submitPromptWithParameters(
                        context.deploymentRevisionId, prompt_input, parameters
                    )
                else:
                    response = engine.submitPrompt(context.deploymentRevisionId, prompt_input)
                observed = str(getattr(response, "responseText", ""))
                passed = self._evaluate_case(case, observed)
                case["observedOutcome"] = observed
                case["status"] = "passed" if passed else "failed"
            except Exception as exc:
                case["observedOutcome"] = str(exc)
                case["status"] = "errored"

            self._persist_case_update(context=context, index=index, case=case)

        if self._should_cancel(context.runId):
            self._finish_cancelled(context)
            return
        self._finish_completed(context)

    def _run_benchmark(self, context: QualityRunContext) -> None:
        if self._should_cancel(context.runId):
            self._finish_cancelled(context)
            return

        with self._session_factory() as session:
            definition = session.get(BenchmarkDefinition, context.testDefinitionRef)
            report = self._report_repo.get_by_run_id(session, context.runId)
            if definition is None or report is None:
                raise RuntimeError("Benchmark run context was not persisted.")
            revision = session.get(DeploymentRevision, context.deploymentRevisionId)
            model_configuration = (
                session.get(ModelConfiguration, revision.modelConfigId)
                if revision is not None
                else None
            )
            model_id = (
                model_configuration.resolvedCheckpointRef
                if model_configuration is not None
                else context.deploymentRevisionId
            )

        result = self._benchmark_runner.evaluate(
            base_url=context.inferenceApiUrl,
            benchmark_definition=definition,
            model_id=model_id,
        )
        self._persist_benchmark_update(context=context, result=result)
        if self._should_cancel(context.runId):
            self._finish_cancelled(context)
            return
        self._finish_completed(context)

    def _run_performance(self, context: QualityRunContext) -> None:
        if self._should_cancel(context.runId):
            self._finish_cancelled(context)
            return

        with self._session_factory() as session:
            workload = session.get(PerformanceWorkload, context.testDefinitionRef)
            report = self._report_repo.get_by_run_id(session, context.runId)
            if workload is None or report is None:
                raise RuntimeError("Performance run context was not persisted.")

        engine = self._provider.get_engine_adapter(context.engineId)
        result = self._performance_runner.run(
            engine=engine,
            deployment_revision_id=context.deploymentRevisionId,
            workload={
                "workloadId": workload.workloadId,
                "version": workload.version,
                "warmup": dict(workload.warmup or {}),
                "inputProfile": dict(workload.inputProfile or {}),
                "concurrency": workload.concurrency,
                "durationOrRequestCount": dict(workload.durationOrRequestCount or {}),
                "safetyLimits": dict(workload.safetyLimits or {}),
                "completionCriteria": dict(workload.completionCriteria or {}),
            },
        )
        self._persist_performance_update(context=context, result=result)
        if self._should_cancel(context.runId):
            self._finish_cancelled(context)
            return
        self._finish_completed(context)

    def _fail_run(self, *, context: QualityRunContext, exc: Exception) -> None:
        with self._session_factory() as session:
            run = session.get(ExperimentRun, context.runId)
            if run is None:
                return
            report = self._report_repo.get_by_run_id(session, context.runId)
            quality = dict(report.quality or {}) if report is not None else {}
            completed = self._report_repo.progress(report)["completedCases"]
            total = self._report_repo.progress(report)["totalCases"]
            performance = report.performance if report is not None else None
            completeness = CompletenessIndicator.PARTIAL
            if isinstance(exc, PerformanceRunOverloadError) and exc.partial_result is not None:
                status = ExperimentRunStatus.INCOMPLETE
                performance = self._normalize_performance_payload(exc.partial_result)
                quality = self._performance_quality_payload(incomplete=True)
            elif isinstance(exc, PerformanceRunOverloadError):
                # Overloaded/crashed before producing any usable metrics: there is
                # nothing partial to preserve, so this must be a hard failure, not
                # a silently-labeled "incomplete" success-adjacent state.
                status = ExperimentRunStatus.FAILED
                performance = None
                quality = self._performance_quality_payload(incomplete=False, failed=True)
                completeness = CompletenessIndicator.PARTIAL
            else:
                status = (
                    ExperimentRunStatus.INCOMPLETE
                    if completed and completed < total
                    else ExperimentRunStatus.FAILED
                )
            if quality.get("cases"):
                cases = [dict(case) for case in quality.get("cases") or []]
                for case in cases:
                    if case.get("status") == "incomplete":
                        case["observedOutcome"] = str(exc)
                quality["cases"] = cases
                quality["aggregate"] = build_quality_aggregate(
                    [str(case.get("status") or "incomplete") for case in cases]
                )
            self._report_repo.upsert(
                session,
                run_id=context.runId,
                quality=quality,
                performance=performance,
                completeness_indicator=completeness,
                reference_execution_profile_ref=(
                    report.referenceExecutionProfileRef if report is not None else None
                ),
            )
            self._transition(run, status)
            run.endedAt = run.endedAt or datetime.now(UTC)
            run.diagnostics = [
                *list(run.diagnostics or []),
                self._diagnostic("error", str(exc)),
            ]
            session.add(run)
            self._sync_environment(
                session,
                environment_id=context.environmentId,
                operation_id=context.runId,
                phase="failed",
                state=run.status.value,
                actor_email=context.actorEmail,
                release_lock=True,
            )
            session.commit()

    def _persist_case_update(
        self, *, context: QualityRunContext, index: int, case: dict[str, Any]
    ) -> None:
        with self._session_factory() as session:
            report = self._report_repo.get_by_run_id(session, context.runId)
            run = session.get(ExperimentRun, context.runId)
            if report is None or run is None:
                return
            quality = dict(report.quality or {})
            cases = [dict(item) for item in quality.get("cases") or []]
            cases[index] = {
                "caseId": str(case.get("caseId") or ""),
                "input": str(case.get("input") or ""),
                "evaluationRule": str(case.get("evaluationRule") or ""),
                "observedOutcome": str(case.get("observedOutcome") or ""),
                "status": str(case.get("status") or "incomplete"),
            }
            quality["cases"] = cases
            quality["aggregate"] = build_quality_aggregate(
                [str(item.get("status") or "incomplete") for item in cases]
            )
            self._report_repo.upsert(
                session,
                run_id=context.runId,
                quality=quality,
                performance=report.performance,
                completeness_indicator=self._completeness_indicator(quality),
                reference_execution_profile_ref=report.referenceExecutionProfileRef,
            )
            run.diagnostics = [
                *list(run.diagnostics or []),
                self._diagnostic("info", f"Processed case {case['caseId']}."),
            ]
            session.add(run)
            session.commit()

    def _persist_benchmark_update(
        self, *, context: QualityRunContext, result: dict[str, Any]
    ) -> None:
        with self._session_factory() as session:
            report = self._report_repo.get_by_run_id(session, context.runId)
            run = session.get(ExperimentRun, context.runId)
            if report is None or run is None:
                return
            quality = dict(report.quality or {})
            quality["benchmarks"] = [result]
            quality["aggregate"] = {
                "totalCases": 1,
                "passed": 1 if result["passFail"] == "pass" else 0,
                "failed": 1 if result["passFail"] == "fail" else 0,
                "errored": 0,
                "skipped": 0,
                "incomplete": 0,
                "passRate": 1.0 if result["passFail"] == "pass" else 0.0,
            }
            self._report_repo.upsert(
                session,
                run_id=context.runId,
                quality=quality,
                performance=report.performance,
                completeness_indicator=CompletenessIndicator.COMPLETE,
                reference_execution_profile_ref=report.referenceExecutionProfileRef,
            )
            run.diagnostics = [
                *list(run.diagnostics or []),
                self._diagnostic("info", f"Benchmark {result['benchmarkId']} completed."),
            ]
            session.add(run)
            session.commit()

    def _persist_performance_update(self, *, context: QualityRunContext, result: Any) -> None:
        with self._session_factory() as session:
            report = self._report_repo.get_by_run_id(session, context.runId)
            run = session.get(ExperimentRun, context.runId)
            if report is None or run is None:
                return
            performance = self._performance_payload_from_stream(result)
            self._report_repo.upsert(
                session,
                run_id=context.runId,
                quality=self._performance_quality_payload(incomplete=False),
                performance=performance,
                completeness_indicator=CompletenessIndicator.COMPLETE,
                reference_execution_profile_ref=(
                    str(
                        dict(performance.get("testConditions", {}))
                        .get("completionCriteria", {})
                        .get("referenceExecutionProfileRef")
                        or f"performance-workload:{context.testDefinitionRef}"
                    )
                ),
            )
            run.diagnostics = [
                *list(run.diagnostics or []),
                self._diagnostic("info", "Performance workload completed."),
            ]
            session.add(run)
            session.commit()

    def _finish_completed(self, context: QualityRunContext) -> None:
        with self._session_factory() as session:
            run = session.get(ExperimentRun, context.runId)
            report = self._report_repo.get_by_run_id(session, context.runId)
            if run is None or report is None or run.status in TERMINAL_STATUSES:
                return
            self._transition(run, ExperimentRunStatus.COMPLETED)
            run.endedAt = datetime.now(UTC)
            quality = dict(report.quality or {})
            completeness = self._completeness_indicator(quality)
            self._report_repo.upsert(
                session,
                run_id=context.runId,
                quality=quality,
                performance=report.performance,
                completeness_indicator=completeness,
                reference_execution_profile_ref=report.referenceExecutionProfileRef,
            )
            session.add(run)
            self._sync_environment(
                session,
                environment_id=context.environmentId,
                operation_id=context.runId,
                phase="completed",
                state=run.status.value,
                actor_email=context.actorEmail,
                release_lock=True,
            )
            session.commit()

    def _finish_cancelled(self, context: QualityRunContext) -> None:
        with self._session_factory() as session:
            run = session.get(ExperimentRun, context.runId)
            report = self._report_repo.get_by_run_id(session, context.runId)
            if run is None:
                return
            if report is not None:
                quality = dict(report.quality or {})
                if quality.get("cases"):
                    cases = [dict(case) for case in quality.get("cases") or []]
                    for case in cases:
                        if case.get("status") == "incomplete":
                            case["status"] = "skipped"
                            case["observedOutcome"] = "Skipped after cancellation."
                    quality["cases"] = cases
                    quality["aggregate"] = build_quality_aggregate(
                        [str(case.get("status") or "incomplete") for case in cases]
                    )
                else:
                    aggregate = dict(quality.get("aggregate") or {})
                    total = int(aggregate.get("totalCases") or 0)
                    executed = (
                        int(aggregate.get("passed") or 0)
                        + int(aggregate.get("failed") or 0)
                        + int(aggregate.get("errored") or 0)
                    )
                    skipped = max(total - executed, 0)
                    quality["aggregate"] = {
                        "totalCases": total,
                        "passed": int(aggregate.get("passed") or 0),
                        "failed": int(aggregate.get("failed") or 0),
                        "errored": int(aggregate.get("errored") or 0),
                        "skipped": skipped,
                        "incomplete": 0,
                        "passRate": float(aggregate.get("passRate") or 0.0),
                    }
                self._report_repo.upsert(
                    session,
                    run_id=context.runId,
                    quality=quality,
                    performance=report.performance,
                    completeness_indicator=self._completeness_indicator(quality),
                    reference_execution_profile_ref=report.referenceExecutionProfileRef,
                )
            if run.status in ACTIVE_STATUSES:
                self._transition(run, ExperimentRunStatus.CANCELLED)
            run.endedAt = run.endedAt or datetime.now(UTC)
            session.add(run)
            self._sync_environment(
                session,
                environment_id=context.environmentId,
                operation_id=context.runId,
                phase="cancelled",
                state=run.status.value,
                actor_email=context.actorEmail,
                release_lock=True,
            )
            session.commit()

    def _set_status(
        self, *, context: QualityRunContext, status: ExperimentRunStatus, phase: str
    ) -> None:
        with self._session_factory() as session:
            run = session.get(ExperimentRun, context.runId)
            if run is None or run.status in TERMINAL_STATUSES:
                return
            self._transition(run, status)
            session.add(run)
            self._sync_environment(
                session,
                environment_id=context.environmentId,
                operation_id=context.runId,
                phase=phase,
                state=status.value,
                actor_email=context.actorEmail,
            )
            session.commit()

    def _sync_environment(
        self,
        session: Session,
        *,
        environment_id: str,
        operation_id: str,
        phase: str,
        state: str,
        actor_email: str,
        release_lock: bool = False,
    ) -> None:
        environment = session.get(DemoEnvironment, environment_id)
        if environment is None:
            return
        environment.providerState = {
            **dict(environment.providerState or {}),
            "currentOperation": {
                "operationId": operation_id,
                "phase": phase,
                "state": state,
                "updatedAt": datetime.now(UTC).isoformat(),
                "diagnostics": [],
            },
        }
        environment.lastModifiedBy = actor_email
        if release_lock:
            try:
                self._environment_lock_service.release(
                    session,
                    environment_id=environment_id,
                    operation_id=operation_id,
                )
            except EnvironmentLockedError:
                # The lock is currently held by a different operation (e.g. a
                # newer run already started). Do not clobber it — only ever
                # clear activeOperationId when it still belongs to us.
                pass
            except EnvironmentNotFoundError:
                pass
        session.add(environment)
        if self._telemetry is not None:
            self._telemetry.emit(
                operation_id=operation_id,
                event_type=f"evaluation.quality.{phase}",
                payload={"environmentId": environment_id, "state": state},
                environment_id=environment_id,
            )

    def _environment_id_for_run(self, session: Session, run: ExperimentRun) -> str:
        revision = session.get(DeploymentRevision, run.deploymentRevisionId)
        return revision.environmentId if revision is not None else ""

    def _should_cancel(self, run_id: str) -> bool:
        with self._cancel_lock:
            event = self._cancel_events.get(run_id)
            if event is not None and event.is_set():
                return True
        with self._session_factory() as session:
            run = session.get(ExperimentRun, run_id)
            return bool(run and run.status == ExperimentRunStatus.CANCELLED)

    def _signal_cancel(self, run_id: str) -> None:
        with self._cancel_lock:
            self._cancel_events.setdefault(run_id, Event()).set()

    @staticmethod
    def _transition(run: ExperimentRun, status: ExperimentRunStatus) -> None:
        if run.status == status:
            return
        allowed = ALLOWED_TRANSITIONS.get(run.status, set())
        if status not in allowed:
            raise RuntimeError(
                f"Invalid run state transition: {run.status.value} -> {status.value}"
            )
        run.status = status

    @staticmethod
    def _diagnostic(severity: str, message: str) -> dict[str, str]:
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": severity,
            "message": message,
        }

    @staticmethod
    def _completeness_indicator(quality: Mapping[str, Any]) -> CompletenessIndicator:
        aggregate = dict(quality.get("aggregate") or {})
        if int(aggregate.get("incomplete") or 0) or int(aggregate.get("skipped") or 0):
            return CompletenessIndicator.PARTIAL
        return CompletenessIndicator.COMPLETE

    @staticmethod
    def _performance_quality_payload(*, incomplete: bool, failed: bool = False) -> dict[str, Any]:
        return {
            "cases": [],
            "aggregate": {
                "totalCases": 1,
                "passed": 0 if (incomplete or failed) else 1,
                "failed": 1 if failed else 0,
                "errored": 0,
                "skipped": 0,
                "incomplete": 1 if incomplete else 0,
                "passRate": 0.0 if (incomplete or failed) else 1.0,
            },
            "benchmarks": [],
        }

    @staticmethod
    def _normalize_performance_payload(
        payload: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if payload is None:
            return None
        normalized = dict(payload)
        normalized["acceleratorUtilization"] = dict(
            normalized.get("acceleratorUtilization") or {"available": False, "details": None}
        )
        return normalized

    def _performance_payload_from_stream(self, result: Any) -> dict[str, Any]:
        samples = list(getattr(result, "samples", []) or [])
        if not samples:
            raise RuntimeError("Performance workload did not return any samples.")
        sample = dict(samples[0] or {})
        return {
            "metrics": dict(sample.get("metrics") or {}),
            "requestFailures": dict(sample.get("requestFailures") or {}),
            "units": dict(sample.get("units") or getattr(result, "units", {}) or {}),
            "testConditions": dict(sample.get("testConditions") or {}),
            "acceleratorUtilization": dict(
                sample.get("acceleratorUtilization")
                or {
                    "available": bool(getattr(result, "acceleratorUtilizationAvailable", False)),
                    "details": None,
                }
            ),
            "runner": str(sample.get("runner") or "llmperf"),
        }

    @staticmethod
    def _strip_reasoning_trace(observed: str) -> str:
        # Qwen3-style hybrid-reasoning models emit a "<think>...</think>" block
        # before their actual answer. Grading the raw response text lets facts
        # or expected substrings mentioned merely while *thinking* count as a
        # pass even when the model's final answer disagrees (e.g. reasoning
        # about "the Nile" before ultimately answering "Amazon") - so grade
        # only what comes after the last closing think tag, mirroring the
        # `think_end_token` handling already applied to lm-eval benchmark runs
        # (see lm_eval_runner.py).
        return strip_reasoning_trace(observed)

    @classmethod
    def _evaluate_case(cls, case: Mapping[str, Any], observed: str) -> bool:
        return evaluate_golden_case(case, observed)
