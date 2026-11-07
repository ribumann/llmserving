"""Persisted, allowlisted public projections; never invoke a provider or an engine."""

from __future__ import annotations

import math
import re
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.errors import ApiError, with_request_id
from src.domain.benchmark_definition import BenchmarkDefinition
from src.domain.catalog import ModelCatalogEntry
from src.domain.comparison import Comparison
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import RetentionClass
from src.domain.environment import DemoEnvironment
from src.domain.experiment_run import ExperimentRun
from src.domain.golden_dataset import GoldenDataset
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.domain.performance_workload import PerformanceWorkload
from src.domain.profile import CloudDeploymentProfile
from src.domain.result_report import ResultReport
from src.persistence.db import get_db_session
from src.providers.registry import PROVIDER_CAPABILITIES

router = APIRouter(prefix="/public", tags=["public"])

SETTING_NUMBERS = {
    "maxModelLen",
    "max_model_len",
    "tensorParallelSize",
    "tensor_parallel_size",
    "gpuMemoryUtilization",
    "gpu_memory_utilization",
    "maxNumSeqs",
    "max_num_seqs",
    "maxNumBatchedTokens",
    "max_num_batched_tokens",
    "temperature",
    "topP",
    "top_p",
    "topK",
    "top_k",
    "maxTokens",
    "max_tokens",
    "seed",
    "repetitionPenalty",
    "repetition_penalty",
    "frequencyPenalty",
    "frequency_penalty",
    "presencePenalty",
    "presence_penalty",
    "numCtx",
    "num_ctx",
    "numPredict",
    "num_predict",
}
SETTING_ENUMS = {
    "dtype": {"auto", "half", "float16", "bfloat16", "float", "float32"},
    "quantization": {"awq", "gptq", "fp8", "int4", "gguf", "none"},
}
QUALITY_NUMBERS = {"totalCases", "passed", "failed", "errored", "skipped", "incomplete", "passRate"}
METRICS = {
    "timeToFirstTokenMs",
    "interTokenLatencyMs",
    "endToEndLatencyMs",
    "throughputTokensPerSec",
}
WORKLOAD_NUMBERS = {
    "requestCount",
    "durationSeconds",
    "meanInputTokens",
    "stddevInputTokens",
    "meanOutputTokens",
    "stddevOutputTokens",
    "inputTokens",
    "outputTokens",
    "maxRequests",
    "maxConcurrency",
    "timeoutSeconds",
    "minSuccessfulRequests",
    "maxFailureRate",
    "targetCompletedRequests",
}


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _numbers(value: Any, keys: set[str]) -> dict:
    return {
        key: number
        for key, number in _mapping(value).items()
        if key in keys
        and (type(number) is int or (type(number) is float and math.isfinite(number)))
    }


def _settings(value: Any) -> dict:
    source = _mapping(value)
    result = _numbers(source, SETTING_NUMBERS)
    for key, choices in SETTING_ENUMS.items():
        if isinstance(source.get(key), str) and source[key] in choices:
            result[key] = source[key]
    return result


def _date(value: Any) -> str | None:
    return value.isoformat() if value else None


def _identifier(value: Any) -> str | None:
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][\w.-]{0,99}", value)
        else None
    )


def _response(request: Request, payload: dict) -> dict:
    return with_request_id(payload, getattr(request.state, "request_id", None))


def _require(session: Session, model: Any, identifier: str) -> Any:
    row = session.get(model, identifier)
    if row is None:
        raise ApiError(
            status_code=404,
            code="public_resource_not_found",
            message="The public resource was not found.",
        )
    return row


def _environment(row: DemoEnvironment) -> dict:
    return {
        "environmentId": row.environmentId,
        "profileId": row.profileId,
        "provider": row.provider.value,
        "region": row.region,
        "lifecycleState": row.lifecycleState.value,
        "state": row.lifecycleState.value,
        "activeDeploymentRevisionId": row.activeDeploymentRevisionId,
        "regionRecommendation": None,
        "providerState": {},
        "createdAt": _date(row.createdAt),
        "updatedAt": _date(row.updatedAt),
    }


def _configuration(snapshot: Any, revision_id: str) -> dict:
    source = _mapping(snapshot)
    deployment = _mapping(source.get("deploymentRevision"))
    model = _mapping(source.get("modelConfiguration"))
    inference = _mapping(source.get("inferenceConfiguration"))
    return {
        "deploymentRevisionId": revision_id,
        "engineId": (
            deployment.get("engineId") if deployment.get("engineId") in ("vllm", "ollama") else None
        ),
        "catalogEntryId": _identifier(model.get("catalogEntryId")),
        "resolvedCheckpointRef": "",
        "modelSettings": _settings(model.get("modelSettings")),
        "servingSettings": _settings(inference.get("servingSettings")),
        "generationSettings": _settings(inference.get("generationSettings")),
    }


def _performance(value: Any) -> dict | None:
    if value is None:
        return None
    source = _mapping(value)
    metrics = _numbers(source.get("metrics"), METRICS)
    for key in METRICS:
        quantiles = _numbers(_mapping(source.get("metrics")).get(key), {"p50", "p95", "p99"})
        if quantiles:
            metrics[key] = quantiles
    conditions = _mapping(source.get("testConditions"))
    return {
        "metrics": metrics,
        "units": {
            key: ("tokens/sec" if key == "throughputTokensPerSec" else "ms") for key in metrics
        },
        "testConditions": {
            **_numbers(conditions, {"concurrency"}),
            **{
                key: _numbers(conditions.get(key), WORKLOAD_NUMBERS)
                for key in (
                    "warmup",
                    "inputProfile",
                    "durationOrRequestCount",
                    "safetyLimits",
                    "completionCriteria",
                )
            },
        },
        "requestFailures": _numbers(source.get("requestFailures"), {"count", "total"}),
        "acceleratorUtilization": {"available": False, "details": None},
        "diagnostics": [],
    }


def _report(row: ResultReport, run: ExperimentRun) -> dict:
    benchmarks = []
    for item in _mapping(row.quality).get("benchmarks", []) or []:
        item = _mapping(item)
        safe = _numbers(item, {"score", "baseline", "delta"})
        if safe:
            safe["benchmarkId"] = run.testDefinitionRef
            if item.get("passFail") in ("pass", "fail"):
                safe["passFail"] = item["passFail"]
            if type(item.get("regressionFlag")) is bool:
                safe["regressionFlag"] = item["regressionFlag"]
            benchmarks.append(safe)
    return {
        "resultReportId": row.resultReportId,
        "runId": row.runId,
        "completenessIndicator": row.completenessIndicator.value,
        "quality": {
            "cases": [],
            "aggregate": _numbers(_mapping(row.quality).get("aggregate"), QUALITY_NUMBERS),
            "benchmarks": benchmarks,
        },
        "performance": _performance(row.performance),
        "referenceExecutionProfileRef": None,
        "configuration": _configuration(run.environmentContextSnapshot, run.deploymentRevisionId),
    }


def _lineage(row: Comparison, session: Session) -> list[dict]:
    reports = []
    for report_id in row.resultReportIds or []:
        report = session.get(ResultReport, report_id)
        run = session.get(ExperimentRun, report.runId) if report else None
        revision = session.get(DeploymentRevision, run.deploymentRevisionId) if run else None
        reports.append(
            {
                "reportId": report_id,
                "revisionId": run.deploymentRevisionId if run else None,
                "environmentId": revision.environmentId if revision else None,
            }
        )
    return reports


def _comparison(row: Comparison, session: Session, *, detail: bool = False) -> dict:
    result = {
        "comparisonId": row.comparisonId,
        "comparabilityStatus": row.comparabilityStatus.value,
        "reports": _lineage(row, session),
    }
    if detail:
        sections = []
        # Keep saved numeric diffs, not raw configuration/failure text or arbitrary JSON.
        for title, source, keys in (
            ("Configuration", row.configurationDiff, set()),
            ("Quality", row.qualityDiff, QUALITY_NUMBERS),
            ("Performance", row.performanceDiff, METRICS),
            (
                "Failures",
                row.failureDiff,
                {
                    "qualityFailed",
                    "qualityErrored",
                    "performanceFailedRequests",
                    "performanceTotalRequests",
                },
            ),
            ("Accelerator utilization", row.utilizationDiff, set()),
        ):
            items = []
            for item in _mapping(source).get("rows", []) or []:
                item = _mapping(item)
                if item.get("reportId") not in (row.resultReportIds or []):
                    continue
                safe = _numbers(item, keys)
                if title == "Performance":
                    for key in METRICS:
                        quantiles = _numbers(item.get(key), {"p50", "p95", "p99"})
                        if quantiles:
                            safe[key] = quantiles
                if title == "Configuration":
                    safe = {
                        "checkpoint": "",
                        "servingSettings": _settings(item.get("servingSettings")),
                        "generationSettings": _settings(item.get("generationSettings")),
                    }
                if safe:
                    items.append({"reportId": item["reportId"], **safe})
            sections.append({"title": title, "items": items})
        result.update({"reasons": [], "sections": sections})
    return result


@router.get("/providers")
def providers(request: Request) -> dict:
    return _response(request, {"providers": [asdict(item) for item in PROVIDER_CAPABILITIES]})


@router.get("/profiles")
def profiles(request: Request, session: Session = Depends(get_db_session)) -> dict:
    return _response(
        request,
        {
            "profiles": [
                {
                    "profileId": row.profileId,
                    "provider": row.provider.value,
                    "modelSizeClass": row.modelSizeClass.value,
                    "eligibleRegions": row.eligibleRegions,
                    "vmSku": row.vmSku,
                    "version": row.version,
                    "capacityAssumptions": _numbers(
                        row.capacityAssumptions, {"gpuCount", "gpuMemoryGb"}
                    ),
                    "configurableInputs": {},
                    "knownLimitations": [],
                }
                for row in session.scalars(
                    select(CloudDeploymentProfile).order_by(CloudDeploymentProfile.profileId)
                ).all()
            ]
        },
    )


@router.get("/catalog")
def catalog(request: Request, session: Session = Depends(get_db_session)) -> dict:
    return _response(
        request,
        {
            "catalog": [
                {
                    "catalogEntryId": row.catalogEntryId,
                    "family": row.family.value,
                    "sizeClass": row.sizeClass.value,
                    "isGated": row.isGated,
                    "quantizationRequired": row.quantizationRequired,
                    "compatibleProfileIds": row.compatibleProfileIds,
                    "huggingFaceRepoId": "",
                    "checkpointRef": "",
                    "license": "",
                    "notes": "",
                }
                for row in session.scalars(
                    select(ModelCatalogEntry).order_by(ModelCatalogEntry.catalogEntryId)
                ).all()
            ]
        },
    )


@router.get("/environments")
def environments(request: Request, session: Session = Depends(get_db_session)) -> dict:
    return _response(
        request,
        {
            "environments": [
                _environment(row)
                for row in session.scalars(
                    select(DemoEnvironment).order_by(DemoEnvironment.createdAt.desc())
                ).all()
            ]
        },
    )


@router.get("/environments/{environment_id}")
def environment(
    environment_id: str, request: Request, session: Session = Depends(get_db_session)
) -> dict:
    return _response(request, _environment(_require(session, DemoEnvironment, environment_id)))


@router.get("/environments/{environment_id}/model-configurations")
def model_configurations(
    environment_id: str, request: Request, session: Session = Depends(get_db_session)
) -> dict:
    _require(session, DemoEnvironment, environment_id)
    return _response(
        request,
        {
            "items": [
                {
                    "modelConfigId": row.modelConfigId,
                    "catalogEntryId": row.catalogEntryId,
                    "resolvedCheckpointRef": "",
                    "modelSettings": _settings(row.modelSettings),
                    "version": row.version,
                    "createdAt": _date(row.createdAt),
                }
                for row in session.scalars(
                    select(ModelConfiguration)
                    .where(ModelConfiguration.environmentId == environment_id)
                    .order_by(ModelConfiguration.version.desc())
                ).all()
            ]
        },
    )


@router.get("/environments/{environment_id}/inference-configurations")
def inference_configurations(
    environment_id: str, request: Request, session: Session = Depends(get_db_session)
) -> dict:
    _require(session, DemoEnvironment, environment_id)
    return _response(
        request,
        {
            "items": [
                {
                    "inferenceConfigId": row.inferenceConfigId,
                    "engineId": row.engineId,
                    "servingSettings": _settings(row.servingSettings),
                    "generationSettings": _settings(row.generationSettings),
                    "version": row.version,
                    "createdAt": _date(row.createdAt),
                }
                for row in session.scalars(
                    select(InferenceConfiguration)
                    .where(InferenceConfiguration.environmentId == environment_id)
                    .order_by(InferenceConfiguration.version.desc())
                ).all()
            ]
        },
    )


@router.get("/environments/{environment_id}/deployments/{revision_id}")
def deployment(
    environment_id: str,
    revision_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict:
    row = _require(session, DeploymentRevision, revision_id)
    if row.environmentId != environment_id:
        raise ApiError(
            status_code=404,
            code="public_resource_not_found",
            message="The public resource was not found.",
        )
    return _response(
        request,
        {
            "deploymentRevisionId": row.deploymentRevisionId,
            "environmentId": row.environmentId,
            "modelConfigId": row.modelConfigId,
            "inferenceConfigId": row.inferenceConfigId,
            "engineId": row.engineId,
            "lifecycleState": row.lifecycleState.value,
            "activePeriod": {},
            "health": {
                "status": (
                    _mapping(row.health).get("status")
                    if _mapping(row.health).get("status")
                    in ("healthy", "unhealthy", "unknown", "ready")
                    else "unknown"
                ),
                "diagnostics": [],
            },
            "createdAt": _date(row.createdAt),
        },
    )


@router.get("/environments/{environment_id}/runs")
def runs(environment_id: str, request: Request, session: Session = Depends(get_db_session)) -> dict:
    _require(session, DemoEnvironment, environment_id)
    rows = session.scalars(
        select(ExperimentRun)
        .join(
            DeploymentRevision,
            ExperimentRun.deploymentRevisionId == DeploymentRevision.deploymentRevisionId,
        )
        .where(
            DeploymentRevision.environmentId == environment_id,
            ExperimentRun.retentionClass == RetentionClass.PERSISTED,
        )
        .order_by(ExperimentRun.startedAt.desc())
    ).all()
    return _response(
        request,
        {
            "runs": [
                {
                    "runId": row.runId,
                    "runType": row.runType.value,
                    "testDefinitionRef": row.testDefinitionRef,
                    "status": row.status.value,
                    "startedAt": _date(row.startedAt),
                    "endedAt": _date(row.endedAt),
                    "configuration": _configuration(
                        row.environmentContextSnapshot, row.deploymentRevisionId
                    ),
                    "diagnostics": [],
                }
                for row in rows
            ]
        },
    )


@router.get("/environments/{environment_id}/runs/{run_id}/report")
def report(
    environment_id: str, run_id: str, request: Request, session: Session = Depends(get_db_session)
) -> dict:
    run = _require(session, ExperimentRun, run_id)
    revision = _require(session, DeploymentRevision, run.deploymentRevisionId)
    if revision.environmentId != environment_id or run.retentionClass != RetentionClass.PERSISTED:
        raise ApiError(
            status_code=404,
            code="public_resource_not_found",
            message="The public resource was not found.",
        )
    row = session.scalars(select(ResultReport).where(ResultReport.runId == run_id)).first()
    if row is None:
        raise ApiError(
            status_code=404,
            code="result_report_not_found",
            message="No persisted report is available.",
        )
    return _response(request, _report(row, run))


@router.get("/golden-datasets")
def golden_datasets(request: Request, session: Session = Depends(get_db_session)) -> dict:
    return _response(
        request,
        {
            "goldenDatasets": [
                {
                    "goldenDatasetId": row.goldenDatasetId,
                    "name": row.goldenDatasetId,
                    "version": row.version,
                    "caseCount": len(row.cases or []),
                    "provenance": row.provenance.value,
                    "reviewStatus": row.reviewStatus.value,
                }
                for row in session.scalars(
                    select(GoldenDataset).order_by(GoldenDataset.createdAt.desc())
                ).all()
            ]
        },
    )


@router.get("/benchmark-definitions")
def benchmark_definitions(request: Request, session: Session = Depends(get_db_session)) -> dict:
    return _response(
        request,
        {
            "benchmarkDefinitions": [
                {"benchmarkId": row.benchmarkId, "version": row.version}
                for row in session.scalars(
                    select(BenchmarkDefinition).order_by(BenchmarkDefinition.benchmarkId)
                ).all()
            ]
        },
    )


@router.get("/performance-workloads")
def performance_workloads(request: Request, session: Session = Depends(get_db_session)) -> dict:
    return _response(
        request,
        {
            "performanceWorkloads": [
                {
                    "workloadId": row.workloadId,
                    "version": row.version,
                    "concurrency": row.concurrency,
                    **{
                        key: _numbers(getattr(row, key), WORKLOAD_NUMBERS)
                        for key in (
                            "warmup",
                            "inputProfile",
                            "durationOrRequestCount",
                            "safetyLimits",
                            "completionCriteria",
                        )
                    },
                }
                for row in session.scalars(
                    select(PerformanceWorkload).order_by(PerformanceWorkload.workloadId)
                ).all()
            ]
        },
    )


@router.get("/comparisons")
def comparisons(request: Request, session: Session = Depends(get_db_session)) -> dict:
    return _response(
        request,
        {
            "comparisons": [
                _comparison(row, session)
                for row in session.scalars(
                    select(Comparison).order_by(Comparison.comparisonId)
                ).all()
            ]
        },
    )


@router.get("/comparisons/{comparison_id}")
def comparison(
    comparison_id: str, request: Request, session: Session = Depends(get_db_session)
) -> dict:
    return _response(
        request, _comparison(_require(session, Comparison, comparison_id), session, detail=True)
    )
