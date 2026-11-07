from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.api.app import create_app
from src.api.auth import AuthenticatedUser
from src.api.errors import ApiError
from src.config import Settings
from src.domain.comparison import Comparison
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    ComparisonStatus,
    CompletenessIndicator,
    DeploymentRevisionState,
    ExperimentRunStatus,
    ExperimentRunType,
    RetentionClass,
)
from src.domain.experiment_run import ExperimentRun
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.domain.result_report import ResultReport
from src.persistence.db import Base
from tests.support.demo_backend import MemorySession

PRIVATE = "PRIVATE_SENTINEL https://private.invalid/10.0.0.1 owner@private.invalid"
BAD_FIELDS = {
    "createdBy",
    "lastModifiedBy",
    "ownerId",
    "tenantId",
    "subscriptionId",
    "principalId",
    "resourceId",
    "token",
    "secret",
    "input",
    "output",
    "observedOutcome",
    "evaluationRule",
    "generationContext",
    "args",
    "vllmExtraArgs",
    "cancellationRequests",
}
PUBLIC_PATHS = [
    "/public/providers",
    "/public/profiles",
    "/public/catalog",
    "/public/environments",
    "/public/environments/env-demo",
    "/public/environments/env-demo/model-configurations",
    "/public/environments/env-demo/inference-configurations",
    "/public/environments/env-demo/deployments/revision-1",
    "/public/environments/env-demo/runs",
    "/public/environments/env-demo/runs/run-1/report",
    "/public/golden-datasets",
    "/public/benchmark-definitions",
    "/public/performance-workloads",
    "/public/comparisons",
    "/public/comparisons/comparison-1",
]


class NoLiveProvider:
    def __getattr__(self, name):
        raise AssertionError(f"Public reads must not call provider.{name}")


@pytest.fixture()
def public_client():
    # Exercise real SQL filtering/joins and persisted JSON, not serializer-only mocks.
    changed = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, (JSONB, ARRAY)):
                changed.append((column, column.type))
                column.type = column.type.with_variant(JSON(), "sqlite")
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    seeds = MemorySession()
    seeds.seed_defaults()
    with factory() as session:
        for collection in (
            seeds.profiles,
            seeds.catalog_entries,
            seeds.engines,
            seeds.environments,
            seeds.golden_datasets,
            seeds.benchmark_definitions,
            seeds.performance_workloads,
        ):
            session.add_all(collection.values())
        env = seeds.environments["env-demo"]
        env.providerState = {
            key: PRIVATE
            for key in (
                "tenantId",
                "subscriptionId",
                "principalId",
                "resourceId",
                "privateIp",
                "inferenceApiUrl",
                "token",
                "diagnostics",
            )
        }
        env.createdBy = env.lastModifiedBy = PRIVATE
        env.regionRecommendation = {"diagnostics": PRIVATE}
        profile = seeds.profiles["azure-single-gpu-3b"]
        profile.capacityAssumptions = {"gpuCount": 1, "gpuMemoryGb": 16, "token": PRIVATE}
        profile.configurableInputs = {"vllmExtraArgs": [PRIVATE], "principalId": PRIVATE}
        profile.knownLimitations = [PRIVATE]
        seeds.catalog_entries["qwen3-4b"].notes = PRIVATE
        seeds.catalog_entries["qwen3-4b"].checkpointRef = PRIVATE
        seeds.catalog_entries["qwen3-4b"].huggingFaceRepoId = PRIVATE
        dataset = seeds.golden_datasets["golden-default"]
        dataset.name = PRIVATE
        dataset.cases = [{"input": PRIVATE, "output": PRIVATE}]
        dataset.generationContext = {"token": PRIVATE}
        seeds.benchmark_definitions["gsm8k"].presentationSubset = {"cases": [PRIVATE]}
        workload = seeds.performance_workloads["workload-default"]
        workload.inputProfile.update({"cases": [PRIVATE], "prompt": PRIVATE})
        workload.warmup.update({"args": PRIVATE})
        model = ModelConfiguration(
            modelConfigId="model-1",
            environmentId="env-demo",
            catalogEntryId="qwen3-4b",
            resolvedCheckpointRef=PRIVATE,
            createdBy=PRIVATE,
            version=1,
            modelSettings={"dtype": "float16", "quantization": PRIVATE, "args": [PRIVATE]},
        )
        inference = InferenceConfiguration(
            inferenceConfigId="inference-1",
            environmentId="env-demo",
            engineId="vllm",
            createdBy=PRIVATE,
            version=1,
            servingSettings={
                "maxModelLen": 2048,
                "tensorParallelSize": {"token": PRIVATE},
                "vllmExtraArgs": [PRIVATE],
            },
            generationSettings={
                "temperature": 0.2,
                "topP": PRIVATE,
                "stop": [PRIVATE],
                "secret": PRIVATE,
            },
        )
        revision = DeploymentRevision(
            deploymentRevisionId="revision-1",
            environmentId="env-demo",
            modelConfigId="model-1",
            inferenceConfigId="inference-1",
            engineId="vllm",
            lifecycleState=DeploymentRevisionState.READY,
            createdBy=PRIVATE,
            health={"status": "healthy", "diagnostics": [PRIVATE], "privateUrl": PRIVATE},
            activePeriod={"startedAt": PRIVATE, "resourceId": PRIVATE},
        )
        env.activeDeploymentRevisionId = "revision-1"
        snapshot = {
            "environmentId": "env-demo",
            "providerState": env.providerState,
            "createdBy": PRIVATE,
            "testDefinition": {"cases": [{"input": PRIVATE}]},
            "deploymentRevision": {"deploymentRevisionId": "revision-1", "engineId": "vllm"},
            "modelConfiguration": {
                "catalogEntryId": "qwen3-4b",
                "resolvedCheckpointRef": PRIVATE,
                "modelSettings": model.modelSettings,
            },
            "inferenceConfiguration": {
                "servingSettings": inference.servingSettings,
                "generationSettings": inference.generationSettings,
            },
        }
        run = ExperimentRun(
            runId="run-1",
            deploymentRevisionId="revision-1",
            runType=ExperimentRunType.QUALITY_GOLDEN,
            testDefinitionRef="golden-default",
            status=ExperimentRunStatus.COMPLETED,
            environmentContextSnapshot=snapshot,
            startedAt=datetime.now(UTC),
            retentionClass=RetentionClass.PERSISTED,
            diagnostics=[{"message": PRIVATE}],
            cancellationRequests=[{"requestedBy": PRIVATE}],
        )
        ephemeral = ExperimentRun(
            runId="ephemeral",
            deploymentRevisionId="revision-1",
            runType=ExperimentRunType.INTERACTIVE_PROMPT,
            status=ExperimentRunStatus.COMPLETED,
            environmentContextSnapshot={"prompt": PRIVATE},
            startedAt=datetime.now(UTC),
            retentionClass=RetentionClass.SESSION_EPHEMERAL,
        )
        report = ResultReport(
            resultReportId="report-1",
            runId="run-1",
            completenessIndicator=CompletenessIndicator.COMPLETE,
            referenceExecutionProfileRef=PRIVATE,
            quality={
                "cases": [{"input": PRIVATE, "observedOutcome": PRIVATE}],
                "aggregate": {
                    "totalCases": 3,
                    "passed": 2,
                    "failed": 1,
                    "passRate": 2 / 3,
                    "token": PRIVATE,
                    "errored": [PRIVATE],
                },
                "benchmarks": [
                    {
                        "score": 70,
                        "baseline": 65,
                        "delta": 5,
                        "passFail": "pass",
                        "benchmarkId": PRIVATE,
                        "version": PRIVATE,
                        "diagnostics": PRIVATE,
                    }
                ],
            },
            performance={
                "metrics": {
                    "throughputTokensPerSec": 42,
                    "timeToFirstTokenMs": {"p50": 10, "p95": 20, "token": PRIVATE},
                    "endToEndLatencyMs": PRIVATE,
                    "args": [PRIVATE],
                },
                "requestFailures": {"count": 1, "total": 8, "errors": [PRIVATE]},
                "testConditions": {
                    "concurrency": 2,
                    "warmup": {"requestCount": 2, "prompt": PRIVATE},
                    "inputProfile": {"meanInputTokens": 128, "cases": [PRIVATE]},
                    "durationOrRequestCount": {"requestCount": 8, "url": PRIVATE},
                    "completionCriteria": {"targetCompletedRequests": 8, "args": [PRIVATE]},
                    "token": PRIVATE,
                },
                "acceleratorUtilization": {"available": True, "details": PRIVATE},
                "raw": {"outputs": [PRIVATE]},
                "diagnostics": [PRIVATE],
            },
        )
        comparison = Comparison(
            comparisonId="comparison-1",
            resultReportIds=["report-1", "deleted-report"],
            comparabilityStatus=ComparisonStatus.NOT_DIRECTLY_COMPARABLE,
            comparabilityReasons=[PRIVATE],
            configurationDiff={
                "rows": [
                    {
                        "reportId": "report-1",
                        "checkpoint": PRIVATE,
                        "servingSettings": inference.servingSettings,
                        "generationSettings": inference.generationSettings,
                        "region": PRIVATE,
                    },
                ]
            },
            qualityDiff={
                "rows": [{"reportId": "report-1", "passed": 2, "failed": 1, "case": PRIVATE}]
            },
            performanceDiff={
                "rows": [
                    {
                        "reportId": "report-1",
                        "throughputTokensPerSec": 42,
                        "timeToFirstTokenMs": {"p50": 10, "error": PRIVATE},
                    }
                ]
            },
            failureDiff={
                "rows": [{"reportId": "report-1", "qualityFailed": 1, "diagnostics": PRIVATE}]
            },
            utilizationDiff={"rows": [{"reportId": "report-1", "details": PRIVATE}]},
        )
        session.add_all([model, inference, revision, run, ephemeral, report, comparison])
        session.commit()
    app = create_app(
        Settings(
            auth_mode="entra-jwt", azure_tenant_id=None, auth_tenant_id=None, auth_audience=None
        )
    )
    app.state.session_factory = factory
    app.state.telemetry = None
    app.state.provider_adapter = NoLiveProvider()
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        engine.dispose()
        for column, original in changed:
            column.type = original


def assert_safe(value):
    if isinstance(value, dict):
        assert not BAD_FIELDS.intersection(value)
        for item in value.values():
            assert_safe(item)
    elif isinstance(value, list):
        for item in value:
            assert_safe(item)
    elif isinstance(value, str):
        assert "PRIVATE_SENTINEL" not in value
        assert "private.invalid" not in value


@pytest.mark.parametrize("path", PUBLIC_PATHS)
def test_anonymous_reads_persisted_safe_projections_even_without_sso(public_client, path):
    client, _ = public_client
    response = client.get(path, headers={"Authorization": "Bearer broken"})
    assert response.status_code == 200, response.text
    assert_safe(response.json())


def test_public_report_and_saved_comparison_have_real_aggregates_and_lineage(public_client):
    client, _ = public_client
    report = client.get("/public/environments/env-demo/runs/run-1/report").json()
    assert report["quality"]["cases"] == []
    assert report["quality"]["aggregate"]["passed"] == 2
    assert report["performance"]["metrics"]["throughputTokensPerSec"] == 42
    assert report["performance"]["metrics"]["timeToFirstTokenMs"] == {"p50": 10, "p95": 20}
    assert report["configuration"]["servingSettings"] == {"maxModelLen": 2048}
    assert report["configuration"]["generationSettings"] == {"temperature": 0.2}
    assert report["quality"]["benchmarks"] == [
        {
            "score": 70,
            "baseline": 65,
            "delta": 5,
            "passFail": "pass",
            "benchmarkId": "golden-default",
        },
    ]
    assert report["performance"]["testConditions"]["completionCriteria"] == {
        "targetCompletedRequests": 8,
    }
    comparisons = client.get("/public/comparisons").json()["comparisons"]
    assert len(comparisons) == 1
    assert comparisons[0]["reports"] == [
        {"reportId": "report-1", "revisionId": "revision-1", "environmentId": "env-demo"},
        {"reportId": "deleted-report", "revisionId": None, "environmentId": None},
    ]
    detail = client.get("/public/comparisons/comparison-1").json()
    assert detail["sections"][1]["items"] == [{"reportId": "report-1", "passed": 2, "failed": 1}]
    assert detail["reasons"] == []
    assert (
        client.get("/public/performance-workloads").json()["performanceWorkloads"][0][
            "inputProfile"
        ]["meanInputTokens"]
        == 128
    )
    assert client.get("/public/golden-datasets").json()["goldenDatasets"][0]["caseCount"] == 1


def test_public_reads_are_scoped_and_session_ephemeral_runs_are_not_published(public_client):
    client, _ = public_client
    assert [
        run["runId"] for run in client.get("/public/environments/env-demo/runs").json()["runs"]
    ] == ["run-1"]
    for path in (
        "/public/environments/env-demo/runs/ephemeral/report",
        "/public/environments/other/runs/run-1/report",
        "/public/environments/other/deployments/revision-1",
        "/public/environments/missing",
        "/public/comparisons/missing",
    ):
        assert client.get(path).status_code == 404


def test_public_reads_do_not_touch_an_unavailable_identity_service(public_client):
    client, _ = public_client

    def unavailable(_token):
        raise AssertionError("Public summaries must not consult operator identity services")

    client.app.state.operator_token_validator = SimpleNamespace(validate=unavailable)
    for path in PUBLIC_PATHS:
        assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 200


def test_public_prefix_configuration_does_not_bypass_the_exact_route_boundary(public_client):
    client, _ = public_client
    client.app.state.settings.auth_bypass_paths.append("/public")
    assert client.get("/public/providers").status_code == 200
    assert client.get("/public/providers/unknown").status_code == 503
    assert client.post("/public/comparisons", json={}).status_code == 503


def test_all_public_mutation_methods_remain_protected_with_configured_sso(public_client):
    client, _ = public_client
    client.app.state.operator_token_validator = SimpleNamespace(
        validate=lambda _: AuthenticatedUser(
            "operator", "operator@example.com", "Operator", "entra-jwt"
        )
    )
    for path in PUBLIC_PATHS:
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD"):
            assert client.request(method, path).status_code == 401


def test_malformed_nested_snapshot_and_report_fields_are_not_disclosed(public_client):
    client, factory = public_client
    with factory() as session:
        run = session.get(ExperimentRun, "run-1")
        run.environmentContextSnapshot = {
            "deploymentRevision": {
                "deploymentRevisionId": {"secret": PRIVATE},
                "engineId": {"token": PRIVATE},
            },
            "modelConfiguration": {"catalogEntryId": {"resourceId": PRIVATE}},
            "inferenceConfiguration": {"servingSettings": {"dtype": {"secret": PRIVATE}}},
        }
        report = session.get(ResultReport, "report-1")
        report.quality = {
            "aggregate": {"passed": True, "failed": {"secret": PRIVATE}},
            "benchmarks": [{"score": 12, "passFail": {"secret": PRIVATE}}],
        }
        revision = session.get(DeploymentRevision, "revision-1")
        revision.health = {"status": {"token": PRIVATE}}
        session.commit()
    report = client.get("/public/environments/env-demo/runs/run-1/report")
    assert report.status_code == 200
    assert_safe(report.json())
    assert report.json()["configuration"]["deploymentRevisionId"] == "revision-1"
    assert report.json()["configuration"]["engineId"] is None
    assert report.json()["quality"]["aggregate"] == {}
    assert (
        client.get("/public/environments/env-demo/deployments/revision-1").json()["health"][
            "status"
        ]
        == "unknown"
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/session"),
        ("GET", "/environments"),
        ("GET", "/catalog"),
        ("GET", "/public"),
        ("GET", "/public/unknown"),
        ("GET", "/public/providers/"),
        ("GET", "/public/providers/extra"),
        ("GET", "/public/session"),
        ("HEAD", "/public/providers"),
        ("POST", "/environments"),
        ("POST", "/environments/preview"),
        ("POST", "/environments/env-demo/model-configurations"),
        ("POST", "/environments/env-demo/inference-configurations"),
        ("POST", "/environments/env-demo/deployments"),
        ("POST", "/environments/env-demo/prompts"),
        ("POST", "/environments/env-demo/runs"),
        ("POST", "/environments/env-demo/runs/run-1/cancel"),
        ("POST", "/environments/env-demo/teardown"),
        ("POST", "/comparisons"),
        ("DELETE", "/environments/env-demo/model-configurations/model-1"),
        ("DELETE", "/environments/env-demo/inference-configurations/inference-1"),
        ("POST", "/public/comparisons"),
        ("PUT", "/public/environments/env-demo"),
        ("PATCH", "/public/environments/env-demo"),
        ("DELETE", "/public/environments/env-demo"),
    ],
)
def test_unapproved_public_paths_and_operator_actions_fail_closed(public_client, method, path):
    client, _ = public_client
    response = client.request(method, path)
    assert response.status_code == 503  # Deliberately unconfigured operator identity service.
    if method != "HEAD":
        assert response.json()["error"]["code"] == "operator_auth_unconfigured"


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/internal/workflows"),
        ("PATCH", "/internal/workflows/workflow-1"),
        ("POST", "/internal/workflows/workflow-1/complete"),
        ("POST", "/internal/workflows/workflow-1/cancel-ack"),
    ],
)
def test_internal_callbacks_still_require_their_separate_identity(public_client, method, path):
    client, _ = public_client
    response = client.request(method, path, json={})
    assert response.status_code in {401, 503}
    assert response.json()["error"]["code"] in {
        "internal_auth_unconfigured",
        "internal_auth_required",
        "authentication_required",
    }


def test_authenticated_operator_write_shapes_remain_unchanged(public_client):
    client, factory = public_client

    def validate(token):
        if token != "operator":
            raise ApiError(status_code=401, code="authentication_required", message="Invalid token")
        return AuthenticatedUser("operator-id", "operator@example.com", "Operator", "entra-jwt")

    client.app.state.operator_token_validator = SimpleNamespace(validate=validate)
    assert client.get("/session").status_code == 401
    headers = {"Authorization": "Bearer operator"}
    assert client.get("/session", headers=headers).json()["authenticated"] is True
    response = client.post(
        "/environments/env-demo/model-configurations",
        headers=headers,
        json={
            "catalogEntryId": "qwen3-4b",
            "resolvedCheckpointRef": PRIVATE,
            "modelSettings": {"dtype": "float16", "args": [PRIVATE]},
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["resolvedCheckpointRef"] == PRIVATE
    assert body["modelSettings"]["args"] == [PRIVATE]
    with factory() as session:
        assert (
            session.get(ModelConfiguration, body["modelConfigId"]).createdBy
            == "operator@example.com"
        )
    response = client.post(
        "/environments/env-demo/inference-configurations",
        headers=headers,
        json={
            "engineId": "vllm",
            "servingSettings": {"maxModelLen": 8192, "args": [PRIVATE]},
            "generationSettings": {"temperature": 0.5},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["servingSettings"]["args"] == [PRIVATE]
    with factory() as session:
        assert session.scalars(select(InferenceConfiguration)).all()
    assert_safe(client.get("/public/environments/env-demo/model-configurations").json())
    assert_safe(client.get("/public/environments/env-demo/inference-configurations").json())
