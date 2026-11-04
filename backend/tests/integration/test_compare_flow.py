from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.enums import DatasetProvenance, DuplicateCheckState, ReviewStatus
from src.domain.golden_dataset import GoldenDataset
from src.evaluation.run_quality import QualityRunOrchestrator
from src.persistence.db import get_db_session
from tests.support.demo_backend import FakeProvider, MemorySession, MemorySessionContext


class ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


@pytest.mark.integration
def test_retune_redeploy_rerun_compare_flow_keeps_original_results_immutable() -> None:
    """Covers FR-019/020: retune -> redeploy -> rerun -> compare, asserting the
    original deployment revision and its result report remain immutable and that
    the comparison correctly surfaces the retuned checkpoint difference."""
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
        executor=ImmediateExecutor(),
    )

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    client = TestClient(app)
    headers = {"X-Demo-User": "presenter@example.com"}

    session.prompt_responses["alpha"] = "gold:alpha"
    session.golden_datasets["golden-compare"] = GoldenDataset(
        goldenDatasetId="golden-compare",
        name="Golden Compare",
        version=1,
        cases=[
            {
                "caseId": "case-pass",
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

    # --- Deploy v1 ---
    model_v1 = client.post(
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
    deploy_v1 = client.post(
        "/environments/env-demo/deployments",
        headers=headers,
        json={
            "modelConfigId": model_v1["modelConfigId"],
            "inferenceConfigId": inference["inferenceConfigId"],
        },
    ).json()
    assert deploy_v1["deploymentRevisionId"] == "env-demo-deployment-1"

    run_v1 = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "quality-golden", "testDefinitionRef": "golden-compare"},
    ).json()
    report_v1_before = client.get(
        f"/environments/env-demo/runs/{run_v1['runId']}/report",
        headers=headers,
    ).json()
    assert report_v1_before["quality"]["aggregate"]["passed"] == 1

    # Snapshot the original run + its environment context before retuning, so we
    # can assert nothing about it changes after redeploy/rerun (FR-019/020).
    original_run_snapshot = copy.deepcopy(session.experiment_runs[run_v1["runId"]])
    original_revision_snapshot = copy.deepcopy(
        session.deployment_revisions[deploy_v1["deploymentRevisionId"]]
    )

    # --- Retune: new model configuration, then redeploy ---
    model_v2 = client.post(
        "/environments/env-demo/model-configurations",
        headers=headers,
        json={
            "catalogEntryId": "qwen3-4b",
            "resolvedCheckpointRef": "Qwen/Qwen3-4B@retuned",
            "modelSettings": {"revisionLabel": "v2-retuned"},
        },
    ).json()
    deploy_v2 = client.post(
        "/environments/env-demo/deployments",
        headers=headers,
        json={
            "modelConfigId": model_v2["modelConfigId"],
            "inferenceConfigId": inference["inferenceConfigId"],
        },
    ).json()
    assert deploy_v2["deploymentRevisionId"] == "env-demo-deployment-2"

    # --- Rerun quality against the retuned deployment ---
    run_v2 = client.post(
        "/environments/env-demo/runs",
        headers=headers,
        json={"runType": "quality-golden", "testDefinitionRef": "golden-compare"},
    ).json()
    report_v2 = client.get(
        f"/environments/env-demo/runs/{run_v2['runId']}/report",
        headers=headers,
    ).json()
    assert report_v2["quality"]["aggregate"]["passed"] == 1

    # --- Immutability assertions: the original revision + run are untouched ---
    assert (
        session.deployment_revisions[deploy_v1["deploymentRevisionId"]].lifecycleState.value
        == "superseded"
    )
    current_run_v1 = session.experiment_runs[run_v1["runId"]]
    assert (
        current_run_v1.environmentContextSnapshot
        == original_run_snapshot.environmentContextSnapshot
    )
    assert current_run_v1.status == original_run_snapshot.status
    # The original revision's own identifying fields (everything but lifecycle
    # state, which legitimately transitions to "superseded" on redeploy) are
    # unchanged.
    assert (
        session.deployment_revisions[deploy_v1["deploymentRevisionId"]].modelConfigId
        == original_revision_snapshot.modelConfigId
    )
    assert (
        session.deployment_revisions[deploy_v1["deploymentRevisionId"]].inferenceConfigId
        == original_revision_snapshot.inferenceConfigId
    )
    report_v1_after = client.get(
        f"/environments/env-demo/runs/{run_v1['runId']}/report",
        headers=headers,
    ).json()
    # `requestId` is a per-request trace id, not persisted report data, so it
    # legitimately differs between the two GETs.
    assert {k: v for k, v in report_v1_after.items() if k != "requestId"} == {
        k: v for k, v in report_v1_before.items() if k != "requestId"
    }

    # --- Compare: the retuned run used a different checkpoint, so the
    # comparison must flag it as not directly comparable (FR-059) while still
    # returning full diff sections for both reports.
    comparison = client.post(
        "/comparisons",
        headers=headers,
        json={"reportIds": [report_v1_before["resultReportId"], report_v2["resultReportId"]]},
    ).json()
    assert comparison["comparabilityStatus"] == "not-directly-comparable"
    assert any("checkpoint" in reason.lower() for reason in comparison["reasons"])
    assert {report["reportId"] for report in comparison["reports"]} == {
        report_v1_before["resultReportId"],
        report_v2["resultReportId"],
    }

    fetched = client.get(f"/comparisons/{comparison['comparisonId']}", headers=headers).json()
    assert fetched["comparisonId"] == comparison["comparisonId"]
    assert fetched["comparabilityStatus"] == "not-directly-comparable"
