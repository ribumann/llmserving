from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from src.domain.benchmark_definition import BenchmarkDefinition
from src.domain.catalog import ModelCatalogEntry
from src.domain.comparison import Comparison
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    DatasetProvenance,
    DemoEnvironmentState,
    DeploymentRevisionState,
    DuplicateCheckState,
    ModelFamily,
    ModelSizeClass,
    ProviderType,
    ReviewStatus,
)
from src.domain.environment import DemoEnvironment
from src.domain.experiment_run import ExperimentRun
from src.domain.golden_dataset import GoldenDataset
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.inference_engine import InferenceEngine
from src.domain.model_configuration import ModelConfiguration
from src.domain.orchestration_workflow import OrchestrationWorkflow
from src.domain.performance_workload import PerformanceWorkload
from src.domain.profile import CloudDeploymentProfile
from src.domain.result_report import ResultReport
from src.engines.base import PerformanceMetricsStream
from src.providers.base import DeploymentHandle


class NoopPersistenceSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def add(self, _obj) -> None:
        return None

    def commit(self) -> None:
        return None


class MemorySessionContext:
    def __init__(self, session: MemorySession) -> None:
        self._session = session

    def __enter__(self) -> MemorySession:
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return None


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class MemorySession:
    def __init__(self) -> None:
        self.environments: dict[str, DemoEnvironment] = {}
        self.profiles: dict[str, CloudDeploymentProfile] = {}
        self.catalog_entries: dict[str, ModelCatalogEntry] = {}
        self.engines: dict[str, InferenceEngine] = {}
        self.model_configurations: dict[str, ModelConfiguration] = {}
        self.inference_configurations: dict[str, InferenceConfiguration] = {}
        self.deployment_revisions: dict[str, DeploymentRevision] = {}
        self.golden_datasets: dict[str, GoldenDataset] = {}
        self.benchmark_definitions: dict[str, BenchmarkDefinition] = {}
        self.performance_workloads: dict[str, PerformanceWorkload] = {}
        self.experiment_runs: dict[str, ExperimentRun] = {}
        self.result_reports: dict[str, ResultReport] = {}
        self.comparisons: dict[str, Comparison] = {}
        self.orchestration_workflows: dict[str, OrchestrationWorkflow] = {}
        self.prompt_responses: dict[str, str] = {}
        self.prompt_errors: dict[str, str] = {}
        self.performance_stream: PerformanceMetricsStream | None = None
        self.performance_error: Exception | None = None

    def seed_defaults(self) -> None:
        self.profiles["azure-single-gpu-3b"] = CloudDeploymentProfile(
            profileId="azure-single-gpu-3b",
            provider=ProviderType.AZURE,
            modelSizeClass=ModelSizeClass.THREE_B,
            eligibleRegions=["eastus2", "westus3"],
            vmSku="Standard_NC16as_T4_v3",
            capacityAssumptions={"gpuCount": 1, "gpuMemoryGb": 16},
            configurableInputs={"profileSizeClass": "small"},
            knownLimitations=["Capacity is best-effort."],
            version=1,
        )
        self.profiles["local-ollama"] = CloudDeploymentProfile(
            profileId="local-ollama",
            provider=ProviderType.LOCAL,
            modelSizeClass=ModelSizeClass.THREE_B,
            eligibleRegions=[],
            vmSku="local-machine",
            capacityAssumptions={"hardwareProfile": "Commodity CPU or single consumer GPU"},
            configurableInputs={},
            knownLimitations=["Requires local Ollama."],
            version=1,
        )
        self.environments["env-demo"] = DemoEnvironment(
            environmentId="env-demo",
            profileId="azure-single-gpu-3b",
            provider=ProviderType.AZURE,
            region="eastus2",
            regionRecommendation=None,
            lifecycleState=DemoEnvironmentState.READY,
            activeDeploymentRevisionId=None,
            providerState={"inferenceApiUrl": "http://vllm.local"},
            createdBy="presenter@example.com",
            lastModifiedBy="presenter@example.com",
        )
        self.engines["vllm"] = InferenceEngine(
            engineId="vllm",
            adapterContractVersion="2026-08-19",
            capabilities={"metricsEndpoints": ["/health", "/metrics"]},
        )
        self.engines["ollama"] = InferenceEngine(
            engineId="ollama",
            adapterContractVersion="2026-08-19",
            capabilities={"metricsEndpoints": ["/api/tags", "/v1/chat/completions"]},
        )
        self.catalog_entries["qwen3-4b"] = ModelCatalogEntry(
            catalogEntryId="qwen3-4b",
            family=ModelFamily.CHINESE_ORIGIN,
            sizeClass=ModelSizeClass.THREE_B,
            huggingFaceRepoId="Qwen/Qwen3-4B",
            checkpointRef="main",
            isGated=False,
            license="Apache 2.0",
            compatibleProfileIds=["azure-single-gpu-3b", "local-ollama"],
            quantizationRequired=False,
            notes="Ungated demo model.",
        )
        self.catalog_entries["qwen2.5-0.5b-instruct"] = ModelCatalogEntry(
            catalogEntryId="qwen2.5-0.5b-instruct",
            family=ModelFamily.CHINESE_ORIGIN,
            sizeClass=ModelSizeClass.THREE_B,
            huggingFaceRepoId="Qwen/Qwen2.5-0.5B-Instruct",
            checkpointRef="qwen2.5:0.5b-instruct",
            isGated=False,
            license="Apache 2.0",
            compatibleProfileIds=["local-ollama"],
            quantizationRequired=False,
            notes="Small local demo model.",
        )
        self.catalog_entries["llama-3.2-3b-instruct"] = ModelCatalogEntry(
            catalogEntryId="llama-3.2-3b-instruct",
            family=ModelFamily.LLAMA,
            sizeClass=ModelSizeClass.THREE_B,
            huggingFaceRepoId="meta-llama/Llama-3.2-3B-Instruct",
            checkpointRef="main",
            isGated=True,
            license="Llama Community License",
            compatibleProfileIds=["azure-single-gpu-3b"],
            quantizationRequired=False,
            notes="Gated demo model.",
        )
        self.golden_datasets["golden-default"] = GoldenDataset(
            goldenDatasetId="golden-default",
            name="Default Golden Dataset",
            version=1,
            cases=[
                {
                    "caseId": "case-1",
                    "input": "alpha",
                    "evaluationRule": "exact-match",
                    "expectedOutput": "echo:alpha",
                }
            ],
            duplicateCheckState=DuplicateCheckState.CLEAN,
            provenance=DatasetProvenance.CURATED,
            reviewStatus=ReviewStatus.REVIEWED,
            generationContext=None,
        )
        self.benchmark_definitions["gsm8k"] = BenchmarkDefinition(
            benchmarkId="gsm8k",
            version="presentation-50-seed-42",
            presentationSubset={"task": "gsm8k", "metric": "exact_match,strict-match"},
            passFailThreshold={"baselineScore": 75.0, "regressionThresholdPoints": 5.0},
        )
        self.performance_workloads["workload-default"] = PerformanceWorkload(
            workloadId="workload-default",
            version=1,
            warmup={"requestCount": 2},
            inputProfile={
                "meanInputTokens": 128,
                "stddevInputTokens": 16,
                "meanOutputTokens": 64,
                "stddevOutputTokens": 8,
            },
            concurrency=2,
            durationOrRequestCount={"requestCount": 10},
            safetyLimits={"maxConcurrency": 8, "maxRequests": 20},
            completionCriteria={"targetCompletedRequests": 10},
        )

    def get(self, model, identifier):
        if model is DemoEnvironment:
            return self.environments.get(identifier)
        if model is CloudDeploymentProfile:
            return self.profiles.get(identifier)
        if model is ModelCatalogEntry:
            return self.catalog_entries.get(identifier)
        if model is InferenceEngine:
            return self.engines.get(identifier)
        if model is ModelConfiguration:
            return self.model_configurations.get(identifier)
        if model is InferenceConfiguration:
            return self.inference_configurations.get(identifier)
        if model is DeploymentRevision:
            return self.deployment_revisions.get(identifier)
        if model is GoldenDataset:
            return self.golden_datasets.get(identifier)
        if model is BenchmarkDefinition:
            return self.benchmark_definitions.get(identifier)
        if model is PerformanceWorkload:
            return self.performance_workloads.get(identifier)
        if model is ExperimentRun:
            return self.experiment_runs.get(identifier)
        if model is ResultReport:
            return self.result_reports.get(identifier)
        if model is Comparison:
            return self.comparisons.get(identifier)
        if model is OrchestrationWorkflow:
            return self.orchestration_workflows.get(identifier)
        return None

    def add(self, obj) -> None:
        now = datetime.now(UTC)
        if getattr(obj, "createdAt", None) is None and hasattr(obj, "createdAt"):
            obj.createdAt = now
        if getattr(obj, "updatedAt", None) is None and hasattr(obj, "updatedAt"):
            obj.updatedAt = now
        if getattr(obj, "startedAt", None) is None and hasattr(obj, "startedAt"):
            obj.startedAt = now
        if isinstance(obj, DemoEnvironment):
            self.environments[obj.environmentId] = obj
        elif isinstance(obj, CloudDeploymentProfile):
            self.profiles[obj.profileId] = obj
        elif isinstance(obj, ModelCatalogEntry):
            self.catalog_entries[obj.catalogEntryId] = obj
        elif isinstance(obj, InferenceEngine):
            self.engines[obj.engineId] = obj
        elif isinstance(obj, ModelConfiguration):
            self.model_configurations[obj.modelConfigId] = obj
        elif isinstance(obj, InferenceConfiguration):
            self.inference_configurations[obj.inferenceConfigId] = obj
        elif isinstance(obj, DeploymentRevision):
            self.deployment_revisions[obj.deploymentRevisionId] = obj
        elif isinstance(obj, GoldenDataset):
            self.golden_datasets[obj.goldenDatasetId] = obj
        elif isinstance(obj, BenchmarkDefinition):
            self.benchmark_definitions[obj.benchmarkId] = obj
        elif isinstance(obj, PerformanceWorkload):
            self.performance_workloads[obj.workloadId] = obj
        elif isinstance(obj, ExperimentRun):
            self.experiment_runs[obj.runId] = obj
        elif isinstance(obj, ResultReport):
            self.result_reports[obj.resultReportId] = obj
        elif isinstance(obj, Comparison):
            self.comparisons[obj.comparisonId] = obj
        elif isinstance(obj, OrchestrationWorkflow):
            self.orchestration_workflows[obj.workflowId] = obj

    def commit(self) -> None:
        return None

    def flush(self) -> None:
        return None

    def execute(self, statement):
        entity = (
            statement.column_descriptions[0].get("entity")
            if hasattr(statement, "column_descriptions")
            else None
        )
        if entity is DemoEnvironment:
            environment_id = _extract_equals_value(statement, "environment_id")
            item = (
                self.environments.get(environment_id)
                if environment_id
                else next(iter(self.environments.values()), None)
            )
            return SimpleNamespace(scalar_one_or_none=lambda: item)
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    def scalar(self, statement):
        text = str(statement)
        if "count(*)" in text and "model_configurations" in text:
            environment_id = _extract_equals_value(statement, "environment_id")
            return len(
                [
                    item
                    for item in self.model_configurations.values()
                    if environment_id is None or item.environmentId == environment_id
                ]
            )
        if "count(*)" in text and "inference_configurations" in text:
            environment_id = _extract_equals_value(statement, "environment_id")
            return len(
                [
                    item
                    for item in self.inference_configurations.values()
                    if environment_id is None or item.environmentId == environment_id
                ]
            )
        if "count(*)" in text and "deployment_revisions" in text:
            environment_id = _extract_equals_value(statement, "environment_id")
            return len(
                [
                    item
                    for item in self.deployment_revisions.values()
                    if environment_id is None or item.environmentId == environment_id
                ]
            )
        if "count(*)" in text and "experiment_runs" in text and "deployment_revisions" in text:
            # Joined query: count runs across every revision belonging to an
            # environment (used to allocate environment-wide-unique run IDs
            # across retune/redeploy cycles).
            environment_id = _extract_equals_value(statement, "environment_id")
            revision_ids_in_environment = {
                revision.deploymentRevisionId
                for revision in self.deployment_revisions.values()
                if environment_id is None or revision.environmentId == environment_id
            }
            return len(
                [
                    item
                    for item in self.experiment_runs.values()
                    if item.deploymentRevisionId in revision_ids_in_environment
                ]
            )
        if "count(*)" in text and "experiment_runs" in text:
            deployment_revision_id = _extract_equals_value(statement, "deployment_revision_id")
            return len(
                [
                    item
                    for item in self.experiment_runs.values()
                    if deployment_revision_id is None
                    or item.deploymentRevisionId == deployment_revision_id
                ]
            )
        if "max(model_configurations.version)" in text:
            return max(
                (
                    item.version
                    for item in self.model_configurations.values()
                    if item.environmentId == "env-demo"
                ),
                default=None,
            )
        if "max(inference_configurations.version)" in text:
            return max(
                (
                    item.version
                    for item in self.inference_configurations.values()
                    if item.environmentId == "env-demo"
                ),
                default=None,
            )
        return None

    def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is ModelConfiguration:
            items = sorted(
                self.model_configurations.values(),
                key=lambda item: (item.version, item.createdAt),
                reverse=True,
            )
            return FakeScalarResult(items)
        if entity is InferenceConfiguration:
            items = sorted(
                self.inference_configurations.values(),
                key=lambda item: (item.version, item.createdAt),
                reverse=True,
            )
            return FakeScalarResult(items)
        if entity is DeploymentRevision:
            items = [
                item
                for item in self.deployment_revisions.values()
                if _matches_where_criteria(item, statement)
            ]
            items = sorted(items, key=lambda item: item.createdAt, reverse=True)
            return FakeScalarResult(items)
        if entity is CloudDeploymentProfile:
            items = sorted(self.profiles.values(), key=lambda item: item.profileId)
            return FakeScalarResult(items)
        if entity is ResultReport:
            return FakeScalarResult(list(self.result_reports.values()))
        return FakeScalarResult([])


def _extract_equals_value(statement, column_name: str) -> str | None:
    criteria = getattr(statement, "_where_criteria", ())
    for criterion in criteria:
        left = getattr(criterion, "left", None)
        right = getattr(criterion, "right", None)
        if getattr(left, "name", None) != column_name:
            continue
        value = getattr(right, "value", None)
        if value is not None:
            return str(value)
    return None


# Maps DB column names (as seen on `BinaryExpression.left.name`) to the
# Python-side attribute name on the mapped domain object, for entities whose
# `select(...).where(...)` criteria need to be evaluated against in-memory
# fake rows (see `_matches_where_criteria`).
_COLUMN_TO_ATTRIBUTE = {
    "environment_id": "environmentId",
    "lifecycle_state": "lifecycleState",
    "deployment_revision_id": "deploymentRevisionId",
}


def _matches_where_criteria(item: Any, statement) -> bool:
    """Evaluates a `select(...).where(...)` statement's criteria against an
    in-memory item, so fakes like `MemorySession.scalars()` behave like a
    real filtered query instead of returning every row unfiltered.

    Only used for entities/criteria this fake test double actually needs to
    filter (currently just `DeploymentRevision`, for
    `WorkflowReconciliationService._reconcile_deploy`'s supersede-lookup).
    """
    criteria = getattr(statement, "_where_criteria", ())
    for criterion in criteria:
        left = getattr(criterion, "left", None)
        right = getattr(criterion, "right", None)
        operator_fn = getattr(criterion, "operator", None)
        column_name = getattr(left, "name", None)
        attribute_name = _COLUMN_TO_ATTRIBUTE.get(column_name, column_name)
        if attribute_name is None or operator_fn is None:
            continue
        actual = getattr(item, attribute_name, None)
        expected = getattr(right, "value", None)
        if not operator_fn(actual, expected):
            return False
    return True


@dataclass(slots=True)
class FakePromptResult:
    responseText: str
    timing: dict[str, float]


class FakeEngineAdapter:
    def __init__(self, session: MemorySession) -> None:
        self._session = session

    def getHealth(self, deployment_revision_id: str):
        return SimpleNamespace(
            deploymentRevisionId=deployment_revision_id,
            ready=True,
            details={"status": "healthy", "diagnostics": []},
        )

    def submitPromptWithParameters(self, deployment_revision_id: str, prompt: str, parameters):
        _ = parameters
        if prompt in self._session.prompt_errors:
            raise RuntimeError(self._session.prompt_errors[prompt])
        return FakePromptResult(
            responseText=self._session.prompt_responses.get(prompt, f"echo:{prompt}"),
            timing={"ttftMs": 10.0, "interTokenLatencyMsAvg": 2.5, "totalLatencyMs": 20.0},
        )

    def runPerformanceWorkload(
        self, deployment_revision_id: str, workload: dict
    ) -> PerformanceMetricsStream:
        _ = workload
        if self._session.performance_error is not None:
            raise self._session.performance_error
        if self._session.performance_stream is not None:
            return self._session.performance_stream
        return PerformanceMetricsStream(
            operationId=f"perf-{deployment_revision_id}",
            samples=[
                {
                    "runner": "llmperf",
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
                    "acceleratorUtilization": {
                        "available": False,
                        "details": None,
                    },
                }
            ],
            units={
                "timeToFirstTokenMs": "ms",
                "interTokenLatencyMs": "ms",
                "endToEndLatencyMs": "ms",
                "throughputTokensPerSec": "tokens/sec",
            },
            acceleratorUtilizationAvailable=False,
        )


class FakeProvider:
    def __init__(self, session: MemorySession, *, engine_adapter=None) -> None:
        self._session = session
        self._engine = engine_adapter or FakeEngineAdapter(session)

    def start_deployment(self, **kwargs) -> DeploymentHandle:
        revision = self._session.get(DeploymentRevision, kwargs["deployment_revision_id"])
        environment = self._session.get(DemoEnvironment, kwargs["environment_id"])
        assert revision is not None
        assert environment is not None

        for previous in self._session.deployment_revisions.values():
            if (
                previous.environmentId == environment.environmentId
                and previous.deploymentRevisionId != revision.deploymentRevisionId
                and previous.lifecycleState == DeploymentRevisionState.READY
            ):
                previous.lifecycleState = DeploymentRevisionState.SUPERSEDED
                previous.activePeriod = {
                    **dict(previous.activePeriod or {}),
                    "endedAt": datetime.now(UTC).isoformat(),
                }

        revision.lifecycleState = DeploymentRevisionState.READY
        revision.activePeriod = {"startedAt": datetime.now(UTC).isoformat(), "endedAt": None}
        revision.health = {"status": "healthy", "diagnostics": []}
        environment.activeDeploymentRevisionId = revision.deploymentRevisionId
        environment.activeOperationId = None
        environment.providerState = {
            **dict(environment.providerState or {}),
            "currentOperation": {
                "operationId": kwargs["operation_id"],
                "phase": "completed",
                "state": DeploymentRevisionState.READY.value,
                "updatedAt": datetime.now(UTC).isoformat(),
                "diagnostics": [],
            },
        }
        return DeploymentHandle(
            operationId=kwargs["operation_id"],
            deploymentRevisionId=revision.deploymentRevisionId,
            phase="accepted",
            state=DeploymentRevisionState.DEPLOYING.value,
        )

    def get_engine_adapter(self, engine_id: str) -> FakeEngineAdapter:
        assert engine_id == "vllm"
        return self._engine
