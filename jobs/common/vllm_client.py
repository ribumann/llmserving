"""Thin client for vLLM's native OpenAI-compatible endpoints
(contracts/engine-interface.md), used by `evaluation_worker`/`performance_worker`
to submit prompts directly against the demo VM's private IP:8000.

Per contracts/engine-interface.md's Azure Implementation Notes, `deploy()` and
`runPerformanceWorkload()` (and, by extension, the golden/benchmark quality
runs implemented here) execute inside these isolated Container Apps Jobs, not
inside FastAPI - never through the backend.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


@dataclass
class PromptResult:
    text: str
    latency_seconds: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def submit_prompt(
    base_url: str,
    prompt: str,
    *,
    model: str = "default",
    max_tokens: int = 256,
    temperature: float = 0.0,
    client: httpx.Client | None = None,
    timeout_seconds: float = 120.0,
) -> PromptResult:
    """POST {base_url}/v1/completions - vLLM's OpenAI-compatible completions
    endpoint. Never raises: transport/HTTP errors are captured on the returned
    `PromptResult.error` so a single failing case doesn't abort a whole run
    (Result Report's per-case status distinguishes pass/fail/errored, FR-024)."""
    owns_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds)
    started = time.monotonic()
    try:
        response = http_client.post(
            f"{base_url.rstrip('/')}/v1/completions",
            json={
                "model": model,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        latency = time.monotonic() - started
        if response.status_code >= 400:
            return PromptResult(
                text="",
                latency_seconds=latency,
                error=f"HTTP {response.status_code}: {response.text}",
            )
        payload = response.json()
        choices = payload.get("choices") or [{}]
        return PromptResult(text=str(choices[0].get("text", "")), latency_seconds=latency)
    except httpx.HTTPError as exc:
        return PromptResult(text="", latency_seconds=time.monotonic() - started, error=str(exc))
    finally:
        if owns_client:
            http_client.close()


def check_health(
    base_url: str, *, client: httpx.Client | None = None, timeout_seconds: float = 5.0
) -> bool:
    """GET {base_url}/health - vLLM's native health endpoint."""
    owns_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds)
    try:
        response = http_client.get(f"{base_url.rstrip('/')}/health")
        return response.status_code == 200
    except httpx.HTTPError:
        return False
    finally:
        if owns_client:
            http_client.close()
