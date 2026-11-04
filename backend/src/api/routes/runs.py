from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.errors import ApiError, with_request_id
from src.api.routes.deployments import _require_environment
from src.api.routes.environments import _provider, _user
from src.domain.benchmark_definition import BenchmarkDefinition
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    CompletenessIndicator,
    DeploymentRevisionState,
    ExperimentRunStatus,
    ExperimentRunType,
    RetentionClass,
)
from src.domain.environment_lock import (
    EnvironmentLockedError,
    EnvironmentLockService,
    EnvironmentNotFoundError,
)
from src.domain.experiment_run import ExperimentRun
from src.domain.golden_dataset import GoldenDataset
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.domain.performance_workload import PerformanceWorkload
from src.domain.result_report_repo import ResultReportRepository, build_quality_aggregate
from src.evaluation.golden_dataset import (
    GoldenDatasetValidationError,
    validate_golden_dataset_for_run,
)
from src.evaluation.run_quality import QualityRunContext, QualityRunOrchestrator
from src.performance.workload import (
    PerformanceWorkloadValidationError,
    validate_performance_workload_for_run,
)
from src.persistence.db import get_db_session
from src.providers.azure.adapter import AzureProviderAdapter

router = APIRouter(tags=["runs"])
TERMINAL_STATUSES = {
    ExperimentRunStatus.COMPLETED,
    ExperimentRunStatus.CANCELLED,
    ExperimentRunStatus.FAILED,
    ExperimentRunStatus.INCOMPLETE,
}


class RunCreateRequest(BaseModel):
    runType: str
    testDefinitionRef: str


def _orchestrator(request: Request) -> QualityRunOrchestrator:
    orchestrator = getattr(request.app.state, "quality_run_orchestrator", None)
    if orchestrator is None:
        orchestrator = QualityRunOrchestrator(
            session_factory=request.app.state.session_factory,
            provider=_provider(request),
            telemetry=getattr(request.app.state, "telemetry", None),
            benchmark_runner=getattr(request.app.state, "lm_eval_runner", None),
            performance_runner=getattr(request.app.state, "performance_runner", None),
        )
        request.app.state.quality_run_orchestrator = orchestrator
    return orchestrator


def _serialize_golden_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "caseId": str(case.get("caseId") or ""),
        "input": str(case.get("input") or ""),
        "evaluationRule": str(case.get("evaluationRule") or ""),
        "observedOutcome": "",
        "status": "incomplete",
    }


def _serialize_definition_snapshot(
    definition: GoldenDataset | BenchmarkDefinition | PerformanceWorkload,
) -> dict[str, Any]:
    if isinstance(definition, GoldenDataset):
        return {
            "goldenDatasetId": definition.goldenDatasetId,
            "name": definition.name,
            "version": definition.version,
            "provenance": definition.provenance.value,
            "reviewStatus": definition.reviewStatus.value,
            "duplicateCheckState": definition.duplicateCheckState.value,
            "generationContext": definition.generationContext,
            "cases": list(definition.cases or []),
        }
    if isinstance(definition, PerformanceWorkload):
        return {
            "workloadId": definition.workloadId,
            "version": definition.version,
            "warmup": dict(definition.warmup or {}),
            "inputProfile": dict(definition.inputProfile or {}),
            "concurrency": definition.concurrency,
            "durationOrRequestCount": dict(definition.durationOrRequestCount or {}),
            "safetyLimits": dict(definition.safetyLimits or {}),
            "completionCriteria": dict(definition.completionCriteria or {}),
        }
    return {
        "benchmarkId": definition.benchmarkId,
        "version": definition.version,
        "presentationSubset": dict(definition.presentationSubset or {}),
        "passFailThreshold": dict(definition.passFailThreshold or {}),
    }


def _resolve_run_type(value: str) -> ExperimentRunType:
    try:
        return ExperimentRunType(value)
    except ValueError as exc:
        raise ApiError(
            status_code=400,
            code="invalid_run_type",
            message=f"Run type '{value}' is not supported by this endpoint.",
            details={"runType": value},
        ) from exc


def _contract_quality_payload(quality: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(quality or {})
    cases = []
    for case in payload.get("cases") or []:
        source = dict(case)
        cases.append(
            {
                "caseId": source.get("caseId", ""),
                "input": source.get("input", ""),
                "evaluationRule": source.get("evaluationRule", ""),
                "observedOutcome": source.get("observedOutcome", ""),
                "status": source.get("status", "incomplete"),
            }
        )
    return {
        "cases": cases,
        "aggregate": dict(payload.get("aggregate") or {}),
        "benchmarks": list(payload.get("benchmarks") or []),
    }


def _require_run(
    session: Session, *, environment_id: str, run_id: str
) -> tuple[ExperimentRun, DeploymentRevision]:
    run = session.get(ExperimentRun, run_id)
    revision = (
        session.get(DeploymentRevision, run.deploymentRevisionId) if run is not None else None
    )
    if run is None or revision is None or revision.environmentId != environment_id:
        raise ApiError(
            status_code=404,
            code="run_not_found",
            message=f"Run '{run_id}' was not found.",
            details={"environmentId": environment_id, "runId": run_id},
        )
    return run, revision


def _ready_revision(session: Session, environment_id: str) -> DeploymentRevision:
    environment = _require_environment(session, environment_id)
    active_revision_id = environment.activeDeploymentRevisionId
    revision = session.get(DeploymentRevision, active_revision_id) if active_revision_id else None
    if (
        revision is None
        or revision.environmentId != environment_id
        or revision.lifecycleState != DeploymentRevisionState.READY
    ):
        raise ApiError(
            status_code=409,
            code="no_ready_deployment",
            message="The environment has no active ready deployment.",
            details={"environmentId": environment_id},
        )
    return revision


def _configuration_summary(snapshot: dict[str, Any]) -> dict[str, object]:
    """Summarize a run's immutable environmentContextSnapshot (FR-020) into the
    model/engine/settings detail operators need to understand which
    configuration produced this run. Read from the run's own captured
    snapshot rather than re-joining the current DeploymentRevision/
    ModelConfiguration/InferenceConfiguration rows, since those are versioned
    and may have changed since the run executed."""
    deployment_revision = dict(snapshot.get("deploymentRevision") or {})
    model_configuration = dict(snapshot.get("modelConfiguration") or {})
    inference_configuration = dict(snapshot.get("inferenceConfiguration") or {})
    return {
        "deploymentRevisionId": deployment_revision.get("deploymentRevisionId"),
        "engineId": deployment_revision.get("engineId"),
        "catalogEntryId": model_configuration.get("catalogEntryId"),
        "resolvedCheckpointRef": model_configuration.get("resolvedCheckpointRef"),
        "modelSettings": model_configuration.get("modelSettings") or {},
        "servingSettings": inference_configuration.get("servingSettings") or {},
        "generationSettings": inference_configuration.get("generationSettings") or {},
    }


@router.get("/environments/{environment_id}/runs")
def list_runs(
    environment_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    _require_environment(session, environment_id)
    rows = (
        session.execute(
            select(ExperimentRun)
            .join(
                DeploymentRevision,
                ExperimentRun.deploymentRevisionId == DeploymentRevision.deploymentRevisionId,
            )
            .where(DeploymentRevision.environmentId == environment_id)
            .order_by(ExperimentRun.startedAt.desc())
        )
        .scalars()
        .all()
    )
    return with_request_id(
        {
            "runs": [
                {
                    "runId": run.runId,
                    "runType": run.runType.value,
                    "testDefinitionRef": run.testDefinitionRef,
                    "status": run.status.value,
                    "startedAt": run.startedAt.isoformat(),
                    "endedAt": run.endedAt.isoformat() if run.endedAt else None,
                    "configuration": _configuration_summary(run.environmentContextSnapshot or {}),
                }
                for run in rows
            ]
        },
        getattr(request.state, "request_id", None),
    )


@router.get("/golden-datasets")
def list_golden_datasets(
    request: Request, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    rows = session.scalars(select(GoldenDataset).order_by(GoldenDataset.createdAt.desc())).all()
    return with_request_id(
        {
            "goldenDatasets": [
                {
                    "goldenDatasetId": row.goldenDatasetId,
                    "name": row.name,
                    "version": row.version,
                    "provenance": row.provenance.value,
                    "reviewStatus": row.reviewStatus.value,
                    "caseCount": len(row.cases or []),
                }
                for row in rows
            ]
        },
        getattr(request.state, "request_id", None),
    )


@router.get("/benchmark-definitions")
def list_benchmark_definitions(
    request: Request, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    rows = session.scalars(
        select(BenchmarkDefinition).order_by(BenchmarkDefinition.benchmarkId)
    ).all()
    return with_request_id(
        {
            "benchmarkDefinitions": [
                {
                    "benchmarkId": row.benchmarkId,
                    "version": row.version,
                }
                for row in rows
            ]
        },
        getattr(request.state, "request_id", None),
    )


@router.get("/performance-workloads")
def list_performance_workloads(
    request: Request, session: Session = Depends(get_db_session)
) -> dict[str, object]:
    rows = session.scalars(
        select(PerformanceWorkload).order_by(PerformanceWorkload.workloadId)
    ).all()
    return with_request_id(
        {
            "performanceWorkloads": [
                {
                    "workloadId": row.workloadId,
                    "version": row.version,
                    "concurrency": row.concurrency,
                }
                for row in rows
            ]
        },
        getattr(request.state, "request_id", None),
    )


@router.post("/environments/{environment_id}/runs", status_code=202)
def create_run(
    environment_id: str,
    payload: RunCreateRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    provider: AzureProviderAdapter = Depends(_provider),
) -> dict[str, object]:
    environment = _require_environment(session, environment_id)
    revision = _ready_revision(session, environment_id)
    run_type = _resolve_run_type(payload.runType)
    if run_type == ExperimentRunType.INTERACTIVE_PROMPT:
        raise ApiError(
            status_code=400,
            code="invalid_run_type",
            message="Interactive prompt runs cannot be started from this endpoint.",
            details={"runType": payload.runType},
        )

    definition: GoldenDataset | BenchmarkDefinition | PerformanceWorkload | None
    if run_type == ExperimentRunType.QUALITY_GOLDEN:
        definition = session.get(GoldenDataset, payload.testDefinitionRef)
        if definition is None:
            raise ApiError(
                status_code=404,
                code="test_definition_not_found",
                message=f"Golden dataset '{payload.testDefinitionRef}' was not found.",
                details={"testDefinitionRef": payload.testDefinitionRef},
            )
        try:
            validate_golden_dataset_for_run(definition)
        except GoldenDatasetValidationError as exc:
            raise ApiError(
                status_code=400,
                code=exc.code,
                message=exc.message,
                details=exc.details,
            ) from exc
    elif run_type == ExperimentRunType.PERFORMANCE:
        definition = session.get(PerformanceWorkload, payload.testDefinitionRef)
        if definition is None:
            raise ApiError(
                status_code=404,
                code="test_definition_not_found",
                message=f"Performance workload '{payload.testDefinitionRef}' was not found.",
                details={"testDefinitionRef": payload.testDefinitionRef},
            )
        try:
            validate_performance_workload_for_run(definition)
        except PerformanceWorkloadValidationError as exc:
            raise ApiError(
                status_code=400,
                code=exc.code,
                message=exc.message,
                details=exc.details,
            ) from exc
    else:
        definition = session.get(BenchmarkDefinition, payload.testDefinitionRef)
        if definition is None:
            raise ApiError(
                status_code=404,
                code="test_definition_not_found",
                message=f"Benchmark definition '{payload.testDefinitionRef}' was not found.",
                details={"testDefinitionRef": payload.testDefinitionRef},
            )

    # Scope the run counter to the whole environment (not just the current
    # deployment revision) so run IDs stay unique across retune/redeploy
    # cycles. Scoping by revision alone would let a rerun after redeploy
    # collide with and silently overwrite an earlier run's ID, violating the
    # immutability guarantee for prior results (FR-019/020).
    next_id = session.scalar(
        select(func.count())
        .select_from(ExperimentRun)
        .join(
            DeploymentRevision,
            DeploymentRevision.deploymentRevisionId == ExperimentRun.deploymentRevisionId,
        )
        .where(DeploymentRevision.environmentId == environment_id)
    )
    run_id = f"{environment_id}-run-{int(next_id or 0) + 1}"
    try:
        EnvironmentLockService().acquire(
            session, environment_id=environment_id, operation_id=run_id
        )
    except EnvironmentNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="environment_not_found",
            message=str(exc),
            details={"environmentId": environment_id},
        ) from exc
    except EnvironmentLockedError as exc:
        raise ApiError(
            status_code=409,
            code="environment_busy",
            message=f"Environment '{environment_id}' is busy with another operation.",
            details={"environmentId": environment_id, "operationId": exc.active_operation_id},
        ) from exc
    user = _user(request)
    model_configuration = session.get(ModelConfiguration, revision.modelConfigId)
    inference_configuration = session.get(InferenceConfiguration, revision.inferenceConfigId)
    run = ExperimentRun(
        runId=run_id,
        deploymentRevisionId=revision.deploymentRevisionId,
        runType=run_type,
        testDefinitionRef=payload.testDefinitionRef,
        status=ExperimentRunStatus.QUEUED,
        environmentContextSnapshot={
            "environmentId": environment.environmentId,
            "profileId": environment.profileId,
            "region": environment.region,
            "provider": environment.provider.value,
            "providerState": dict(environment.providerState or {}),
            "deploymentRevision": {
                "deploymentRevisionId": revision.deploymentRevisionId,
                "engineId": revision.engineId,
                "modelConfigId": revision.modelConfigId,
                "inferenceConfigId": revision.inferenceConfigId,
            },
            "modelConfiguration": {
                "modelConfigId": getattr(model_configuration, "modelConfigId", None),
                "catalogEntryId": getattr(model_configuration, "catalogEntryId", None),
                "resolvedCheckpointRef": getattr(
                    model_configuration, "resolvedCheckpointRef", None
                ),
                "modelSettings": dict(getattr(model_configuration, "modelSettings", {}) or {}),
            },
            "inferenceConfiguration": {
                "inferenceConfigId": getattr(inference_configuration, "inferenceConfigId", None),
                "servingSettings": dict(
                    getattr(inference_configuration, "servingSettings", {}) or {}
                ),
                "generationSettings": dict(
                    getattr(inference_configuration, "generationSettings", {}) or {}
                ),
            },
            "testDefinition": _serialize_definition_snapshot(definition),
        },
        diagnostics=[],
        cancellationRequests=[],
        retentionClass=RetentionClass.PERSISTED,
    )
    session.add(run)
    environment.providerState = {
        **dict(environment.providerState or {}),
        "currentOperation": {
            "operationId": run_id,
            "phase": "accepted",
            "state": ExperimentRunStatus.QUEUED.value,
            "updatedAt": datetime.now(UTC).isoformat(),
            "diagnostics": [],
        },
    }
    environment.activeOperationId = run_id
    session.add(environment)

    report_repo = ResultReportRepository()
    if run_type == ExperimentRunType.QUALITY_GOLDEN:
        cases = [_serialize_golden_case(case) for case in list(definition.cases or [])]
        quality = {
            "cases": cases,
            "aggregate": build_quality_aggregate(
                [str(case.get("status") or "incomplete") for case in cases]
            ),
            "benchmarks": [],
        }
    else:
        quality = {
            "cases": [],
            "aggregate": {
                "totalCases": 1,
                "passed": 0,
                "failed": 0,
                "errored": 0,
                "skipped": 0,
                "incomplete": 1,
                "passRate": 0.0,
            },
            "benchmarks": [],
        }
    report_repo.upsert(
        session,
        run_id=run_id,
        quality=quality,
        performance=None,
        completeness_indicator=CompletenessIndicator.PARTIAL,
    )
    session.commit()

    context = QualityRunContext(
        environmentId=environment_id,
        deploymentRevisionId=revision.deploymentRevisionId,
        engineId=revision.engineId,
        runId=run_id,
        operationId=run_id,
        actorEmail=user.email,
        runType=run_type,
        testDefinitionRef=payload.testDefinitionRef,
        inferenceApiUrl=str(dict(environment.providerState or {}).get("inferenceApiUrl") or ""),
    )
    try:
        _orchestrator(request).submit(context)
    except Exception as exc:
        EnvironmentLockService().release(
            session, environment_id=environment_id, operation_id=run_id
        )
        run.status = ExperimentRunStatus.FAILED
        run.endedAt = datetime.now(UTC)
        run.diagnostics = [
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "severity": "error",
                "message": str(exc),
            }
        ]
        session.add(run)
        session.add(environment)
        session.commit()
        raise ApiError(
            status_code=500,
            code="run_start_failed",
            message="The quality run was created, but orchestration could not start.",
            details={"environmentId": environment_id, "runId": run_id},
        ) from exc

    return with_request_id(
        {
            "runId": run_id,
            "runType": run_type.value,
            "status": ExperimentRunStatus.QUEUED.value,
            "deploymentRevisionId": revision.deploymentRevisionId,
        },
        getattr(request.state, "request_id", None),
    )


@router.get("/environments/{environment_id}/runs/{run_id}")
def get_run(
    environment_id: str,
    run_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    run, _revision = _require_run(session, environment_id=environment_id, run_id=run_id)
    report = ResultReportRepository().get_by_run_id(session, run_id)
    progress = ResultReportRepository.progress(report)
    return with_request_id(
        {
            "runId": run.runId,
            "environmentId": environment_id,
            "deploymentRevisionId": run.deploymentRevisionId,
            "runType": run.runType.value,
            "testDefinitionRef": run.testDefinitionRef,
            "status": run.status.value,
            "startedAt": run.startedAt.isoformat(),
            "endedAt": run.endedAt.isoformat() if run.endedAt else None,
            "diagnostics": list(run.diagnostics or []),
            "progress": progress,
            "configuration": _configuration_summary(run.environmentContextSnapshot or {}),
        },
        getattr(request.state, "request_id", None),
    )


@router.post("/environments/{environment_id}/runs/{run_id}/cancel")
def cancel_run(
    environment_id: str,
    run_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    run, _revision = _require_run(session, environment_id=environment_id, run_id=run_id)
    if run.status not in {ExperimentRunStatus.QUEUED, ExperimentRunStatus.RUNNING}:
        return with_request_id(
            {
                "runId": run.runId,
                "status": run.status.value,
                "cancellationRequests": list(run.cancellationRequests or []),
            },
            getattr(request.state, "request_id", None),
        )

    updated = _orchestrator(request).cancel(run_id=run_id, requested_by=_user(request).email)
    return with_request_id(
        {
            "runId": updated.runId,
            "status": updated.status.value,
            "cancellationRequests": list(updated.cancellationRequests or []),
        },
        getattr(request.state, "request_id", None),
    )


@router.get("/environments/{environment_id}/runs/{run_id}/report")
def get_run_report(
    environment_id: str,
    run_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    run, _revision = _require_run(session, environment_id=environment_id, run_id=run_id)
    if run.status not in TERMINAL_STATUSES:
        raise ApiError(
            status_code=409,
            code="report_not_ready",
            message="The result report is not ready until the run reaches a terminal state.",
            details={"runId": run_id, "status": run.status.value},
        )
    report = ResultReportRepository().get_by_run_id(session, run_id)
    if report is None:
        raise ApiError(
            status_code=409,
            code="report_not_ready",
            message="The result report is not available yet.",
            details={"runId": run_id},
        )
    return with_request_id(
        {
            "resultReportId": report.resultReportId,
            "runId": run.runId,
            "completenessIndicator": report.completenessIndicator.value,
            "quality": _contract_quality_payload(report.quality),
            "performance": report.performance,
            "referenceExecutionProfileRef": report.referenceExecutionProfileRef,
            "configuration": _configuration_summary(run.environmentContextSnapshot or {}),
        },
        getattr(request.state, "request_id", None),
    )
