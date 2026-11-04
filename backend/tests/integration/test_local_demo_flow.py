from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.config import Settings
from src.domain.benchmark_definition import BenchmarkDefinition
from src.domain.enums import (
    DatasetProvenance,
    DuplicateCheckState,
    ReviewStatus,
)
from src.domain.golden_dataset import GoldenDataset
from src.engines.ollama.adapter import OllamaEngineAdapter
from src.evaluation.run_quality import QualityRunOrchestrator
from src.persistence.db import get_db_session
from src.providers.azure.adapter import AzureProviderAdapter
from src.providers.local.adapter import LocalProviderAdapter
from src.providers.registry import CompositeProviderAdapter
from tests.support.demo_backend import MemorySession, MemorySessionContext


class ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


@pytest.mark.integration
def test_local_demo_flow_end_to_end() -> None:
    session = MemorySession()
    session.seed_defaults()
    session.golden_datasets["golden-local"] = GoldenDataset(
        goldenDatasetId="golden-local",
        name="Local Golden",
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
    session.benchmark_definitions["gsm8k"] = BenchmarkDefinition(
        benchmarkId="gsm8k",
        version="presentation-50-seed-42",
        presentationSubset={"task": "gsm8k", "metric": "exact_match,strict-match"},
        passFailThreshold={"baselineScore": 75.0, "regressionThresholdPoints": 5.0},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "" or path == "/":
            return httpx.Response(200, text="Ollama is running")
        if path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        if path == "/api/pull":
            return httpx.Response(200, json={"status": "success"})
        if path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen2.5:0.5b-instruct"}]})
        if path == "/v1/chat/completions":
            prompt = json.loads(request.content.decode("utf-8"))["messages"][0]["content"]
            sse_events = [
                {"choices": [{"delta": {"content": f"echo:{prompt}"}}]},
                {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"completion_tokens": 4},
                },
            ]
            lines = "".join(f"data: {json.dumps(event)}\n\n" for event in sse_events)
            lines += "data: [DONE]\n\n"
            return httpx.Response(200, content=lines.encode("utf-8"))
        raise AssertionError(f"Unexpected path {path}")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = Settings(ollama_base_url="http://ollama.local")
    local_provider = LocalProviderAdapter(
        session_factory=lambda: MemorySessionContext(session),
        settings=settings,
        http_client=http_client,
        engine_adapter=OllamaEngineAdapter(
            settings=settings,
            http_client=http_client,
            session_factory=lambda: MemorySessionContext(session),
        ),
    )
    app = create_app(settings=settings)
    app.state.provider_adapter = CompositeProviderAdapter(
        azure=AzureProviderAdapter(
            session_factory=lambda: MemorySessionContext(session),
            settings=settings,
            telemetry=None,
        ),
        local=local_provider,
        session_factory=lambda: MemorySessionContext(session),
    )
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

    preview = client.post(
        "/environments/preview",
        headers=headers,
        json={"profileId": "local-ollama"},
    )
    assert preview.status_code == 200
    assert preview.json()["recommendedRegion"] == "local"

    create_env = client.post(
        "/environments",
        headers=headers,
        json={"profileId": "local-ollama"},
    )
    assert create_env.status_code == 202
    environment_id = create_env.json()["environmentId"]

    environment = client.get(f"/environments/{environment_id}", headers=headers)
    assert environment.status_code == 200
    assert environment.json()["lifecycleState"] == "ready"

    model = client.post(
        f"/environments/{environment_id}/model-configurations",
        headers=headers,
        json={
            "catalogEntryId": "qwen2.5-0.5b-instruct",
            "resolvedCheckpointRef": "qwen2.5:0.5b-instruct",
            "modelSettings": {"revisionLabel": "local"},
        },
    )
    inference = client.post(
        f"/environments/{environment_id}/inference-configurations",
        headers=headers,
        json={
            "engineId": "ollama",
            "servingSettings": {},
            "generationSettings": {"temperature": 0.2},
        },
    )
    assert model.status_code == 201
    assert inference.status_code == 201

    deploy = client.post(
        f"/environments/{environment_id}/deployments",
        headers=headers,
        json={
            "modelConfigId": model.json()["modelConfigId"],
            "inferenceConfigId": inference.json()["inferenceConfigId"],
        },
    )
    assert deploy.status_code == 202

    revision_id = deploy.json()["deploymentRevisionId"]
    deployment = client.get(
        f"/environments/{environment_id}/deployments/{revision_id}",
        headers=headers,
    )
    assert deployment.status_code == 200
    assert deployment.json()["lifecycleState"] == "ready"

    prompt = client.post(
        f"/environments/{environment_id}/prompts",
        headers=headers,
        json={"prompt": "hello", "parameters": {"temperature": 0.1}},
    )
    assert prompt.status_code == 200
    assert prompt.json()["responseText"] == "echo:hello"

    quality = client.post(
        f"/environments/{environment_id}/runs",
        headers=headers,
        json={"runType": "quality-golden", "testDefinitionRef": "golden-local"},
    )
    assert quality.status_code == 202
    quality_report = client.get(
        f"/environments/{environment_id}/runs/{quality.json()['runId']}/report",
        headers=headers,
    )
    assert quality_report.status_code == 200
    assert quality_report.json()["quality"]["aggregate"]["passRate"] == 1.0

    performance = client.post(
        f"/environments/{environment_id}/runs",
        headers=headers,
        json={"runType": "performance", "testDefinitionRef": "workload-default"},
    )
    assert performance.status_code == 202
    perf_report = client.get(
        f"/environments/{environment_id}/runs/{performance.json()['runId']}/report",
        headers=headers,
    )
    assert perf_report.status_code == 200
    assert perf_report.json()["performance"]["acceleratorUtilization"]["available"] is False
