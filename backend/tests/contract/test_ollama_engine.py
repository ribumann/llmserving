from __future__ import annotations

import json

import httpx
from src.config import Settings
from src.engines.base import InferenceEngineAdapter
from src.engines.ollama.adapter import OllamaEngineAdapter


def test_ollama_engine_satisfies_contract() -> None:
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen2.5:0.5b-instruct"}]})
        if request.url.path == "/v1/chat/completions":
            payloads.append(json.loads(request.content))
            sse_events = [
                {"choices": [{"delta": {"content": "echo:hello"}}]},
                {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"completion_tokens": 3},
                },
            ]
            lines = "".join(f"data: {json.dumps(event)}\n\n" for event in sse_events)
            lines += "data: [DONE]\n\n"
            return httpx.Response(200, content=lines.encode("utf-8"))
        raise AssertionError(f"Unexpected path {request.url.path}")

    adapter = OllamaEngineAdapter(
        settings=Settings(ollama_base_url="http://ollama.local"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        deployment_locator=lambda revision_id: {
            "deploymentRevisionId": revision_id,
            "resolvedCheckpointRef": "qwen2.5:0.5b-instruct",
            "huggingFaceRepoId": "Qwen/Qwen2.5-0.5B-Instruct",
            "providerState": {"inferenceApiUrl": "http://ollama.local"},
        },
    )
    assert isinstance(adapter, InferenceEngineAdapter)

    prompt = adapter.submitPrompt("rev-1", "hello")
    assert prompt.responseText == "echo:hello"
    assert prompt.ttftMs >= 0.0
    assert payloads[-1]["model"] == "qwen2.5:0.5b-instruct"
    adapter.submitPromptWithParameters("rev-1", "hello", {"num_predict": 8, "temperature": 0.0})
    assert payloads[-1]["max_tokens"] == 8
    assert payloads[-1]["temperature"] == 0.0
    assert "options" not in payloads[-1]

    performance = adapter.runPerformanceWorkload(
        "rev-1",
        {
            "concurrency": 1,
            "warmup": {"requestCount": 1},
            "durationOrRequestCount": {"requestCount": 2},
            "inputProfile": {"meanOutputTokens": 8},
        },
    )
    assert performance.acceleratorUtilizationAvailable is False
    assert all(payload["max_tokens"] == 8 for payload in payloads[-2:])
    assert len(payloads) == 5  # Two prompts, one warmup, two measured requests.
    assert performance.samples[0]["requestFailures"]["total"] == 2
