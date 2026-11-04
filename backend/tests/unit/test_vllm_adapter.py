from __future__ import annotations

import json
from typing import Any

import httpx
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DeploymentRevisionState
from src.domain.model_configuration import ModelConfiguration
from src.engines.vllm.adapter import VllmEngineAdapter
from src.engines.vllm.prompt import VllmPromptClient, build_locator_from_session_factory
from tests.support.demo_backend import MemorySession, MemorySessionContext


def test_vllm_describe_settings_surfaces_defaults() -> None:
    adapter = VllmEngineAdapter(
        http_client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    )
    settings = adapter.describeSettings()
    assert settings.defaults["temperature"] == 0.1
    assert "gpu_memory_utilization" in settings.servingSettings
    assert "max_tokens" in settings.generationSettings


def test_vllm_health_and_deploy_use_http_endpoints() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, text="ok")
        if request.url.path == "/metrics":
            return httpx.Response(200, text="vllm_requests_total 1")
        raise AssertionError(f"Unexpected path: {request.url.path}")

    adapter = VllmEngineAdapter(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        deployment_locator=lambda revision_id: {
            "deploymentRevisionId": revision_id,
            "baseUrl": "http://demo.local",
            "providerState": {"inferenceApiUrl": "http://demo.local"},
        },
    )

    health = adapter.getHealth("rev-1")
    assert health.ready is True
    handle = adapter.deploy(
        {"resolvedCheckpointRef": "Qwen/Qwen3-4B@main"},
        {"servingSettings": {"dtype": "auto"}},
        {
            "deploymentRevisionId": "rev-1",
            "operationId": "op-1",
            "providerState": {"inferenceApiUrl": "http://demo.local"},
        },
    )
    assert handle.state == "ready"


def test_vllm_prompt_client_streams_real_ttft_and_inter_token_latency() -> None:
    # Regression test: TTFT and inter-token latency must reflect the actual
    # arrival timing of streamed content chunks, not a header-sniffed or
    # aggregate-latency estimate (the bug reported from the Exercise page).
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["stream"] is True
        sse_events = [
            {"choices": [{"delta": {"content": "hello"}}]},
            {"choices": [{"delta": {"content": " there"}}]},
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 2},
            },
        ]
        lines = "".join(f"data: {json.dumps(event)}\n\n" for event in sse_events)
        lines += "data: [DONE]\n\n"
        return httpx.Response(200, content=lines.encode("utf-8"))

    client = VllmPromptClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        deployment_locator=lambda revision_id: {
            "deploymentRevisionId": revision_id,
            "resolvedCheckpointRef": "Qwen/Qwen3-4B@main",
            "providerState": {"inferenceApiUrl": "http://demo.local"},
        },
    )

    result = client.submitPrompt("rev-1", "hello", {"temperature": 0.1})
    assert result.responseText == "hello there"
    assert result.timing["ttftMs"] >= 0.0
    assert result.timing["totalLatencyMs"] >= result.timing["ttftMs"]
    # Two content chunks were streamed, so there should be exactly one
    # measured inter-chunk gap (not an estimate derived from token count).
    assert len(result.interTokenLatencyMs) == 1
    assert not result.diagnostics


def test_vllm_prompt_client_prefers_hugging_face_repo_id_over_resolved_checkpoint_ref() -> None:
    """Regression test for the production bug: vLLM's OpenAI-compatible API
    rejects a "model" value that doesn't match the repo id the server was
    started with (`--model`). `resolvedCheckpointRef` is only a revision
    within that repo (often "main") and must never be sent alone when a real
    `huggingFaceRepoId` is available.
    """
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, content=b'data: [DONE]\n\n')

    client = VllmPromptClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        deployment_locator=lambda revision_id: {
            "deploymentRevisionId": revision_id,
            "huggingFaceRepoId": "Qwen/Qwen3-4B",
            "resolvedCheckpointRef": "main",
            "providerState": {"inferenceApiUrl": "http://demo.local"},
        },
    )

    client.submitPrompt("rev-1", "hello", {})

    assert captured["model"] == "Qwen/Qwen3-4B"


def test_vllm_perf_workload_prefers_hugging_face_repo_id_for_model_id() -> None:
    """Regression test: `runPerformanceWorkload` must send the real Hugging
    Face repo id as the vLLM `model_id`, never the bare `resolvedCheckpointRef`
    revision (e.g. "main"), or the performance run's own inference calls would
    fail the same way real deployments did.
    """

    class FakePerformanceRunner:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def run(self, *, base_url: str, workload: Any, model_id: str, operation_id: str) -> Any:
            self.calls.append({"base_url": base_url, "model_id": model_id})
            return object()

    runner = FakePerformanceRunner()
    adapter = VllmEngineAdapter(
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        ),
        deployment_locator=lambda revision_id: {
            "deploymentRevisionId": revision_id,
            "huggingFaceRepoId": "Qwen/Qwen3-4B",
            "resolvedCheckpointRef": "main",
            "providerState": {"inferenceApiUrl": "http://demo.local"},
        },
        performance_runner=runner,
    )

    adapter.runPerformanceWorkload("rev-1", {"concurrency": 1})

    assert runner.calls[0]["model_id"] == "Qwen/Qwen3-4B"


def test_vllm_prompt_client_falls_back_when_no_content_chunks_stream() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        lines = 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'
        lines += "data: [DONE]\n\n"
        return httpx.Response(200, content=lines.encode("utf-8"))

    client = VllmPromptClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        deployment_locator=lambda revision_id: {
            "deploymentRevisionId": revision_id,
            "resolvedCheckpointRef": "Qwen/Qwen3-4B@main",
            "providerState": {"inferenceApiUrl": "http://demo.local"},
        },
    )

    result = client.submitPrompt("rev-1", "hello", {})
    assert result.responseText == ""
    assert result.timing["ttftMs"] == result.timing["totalLatencyMs"]
    assert result.interTokenLatencyMs == []
    assert any("No streamed content chunks" in message for message in result.diagnostics)


def test_locator_resolves_hugging_face_repo_id_via_catalog_entry() -> None:
    """Regression test: the session-backed locator must resolve the model
    configuration's catalog entry to surface `huggingFaceRepoId` alongside
    `resolvedCheckpointRef`, since neither `submitPrompt` nor
    `runPerformanceWorkload` can send a working vLLM "model" value without it.
    """
    session = MemorySession()
    session.seed_defaults()
    session.add(
        ModelConfiguration(
            modelConfigId="model-config-1",
            environmentId="env-demo",
            catalogEntryId="qwen3-4b",
            resolvedCheckpointRef="main",
            modelSettings={},
        )
    )
    session.add(
        DeploymentRevision(
            deploymentRevisionId="revision-1",
            environmentId="env-demo",
            modelConfigId="model-config-1",
            inferenceConfigId="inference-config-1",
            engineId="vllm",
            lifecycleState=DeploymentRevisionState.READY,
            health={"status": "ready", "diagnostics": []},
            activePeriod={},
        )
    )

    locator = build_locator_from_session_factory(lambda: MemorySessionContext(session))
    deployment = locator("revision-1")

    assert deployment["huggingFaceRepoId"] == "Qwen/Qwen3-4B"
    assert deployment["resolvedCheckpointRef"] == "main"
