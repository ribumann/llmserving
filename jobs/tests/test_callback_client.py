from __future__ import annotations

from typing import Any

import httpx
import pytest
from common.callback_client import (
    CallbackClientError,
    WorkflowCallbackClient,
    job_input_from_env,
    required_env,
)


class _FakeToken:
    def __init__(self, token: str) -> None:
        self.token = token


class _FakeCredential:
    def get_token(self, *_scopes: str) -> _FakeToken:
        return _FakeToken("fake-token")


def _client_with_transport(handler) -> WorkflowCallbackClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return WorkflowCallbackClient(
        base_url="https://backend.example/internal/workflows",
        credential=_FakeCredential(),
        client=http_client,
    )


def test_report_progress_sends_patch_with_bearer_token() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = httpx.Request.read(request)
        return httpx.Response(200, json={"workflowId": "wf-1", "phase": "applying"})

    client = _client_with_transport(handler)
    result = client.report_progress("wf-1", phase="applying", diagnostics={"pct": 50})

    assert captured["method"] == "PATCH"
    assert captured["url"] == "https://backend.example/internal/workflows/wf-1"
    assert captured["authorization"] == "Bearer fake-token"
    assert result["phase"] == "applying"


def test_complete_workflow_sends_post() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://backend.example/internal/workflows/wf-1/complete"
        return httpx.Response(200, json={"workflowId": "wf-1", "status": "completed"})

    client = _client_with_transport(handler)
    result = client.complete_workflow("wf-1", status="completed", phase="completed")

    assert result["status"] == "completed"


def test_acknowledge_cancellation_sends_post() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://backend.example/internal/workflows/wf-1/cancel-ack"
        return httpx.Response(200, json={"workflowId": "wf-1"})

    client = _client_with_transport(handler)
    client.acknowledge_cancellation("wf-1")


def test_error_response_raises_callback_client_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, text="workflow already terminal")

    client = _client_with_transport(handler)
    with pytest.raises(CallbackClientError, match="409"):
        client.report_progress("wf-1", phase="applying")


def test_missing_base_url_raises() -> None:
    with pytest.raises(CallbackClientError):
        WorkflowCallbackClient(base_url=None, credential=_FakeCredential())


def test_job_input_from_env_requires_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOB_INPUT_JSON", raising=False)
    with pytest.raises(CallbackClientError):
        job_input_from_env()


def test_job_input_from_env_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOB_INPUT_JSON", '{"action": "apply"}')
    assert job_input_from_env() == {"action": "apply"}


def test_required_env_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOME_REQUIRED_VAR", raising=False)
    with pytest.raises(CallbackClientError):
        required_env("SOME_REQUIRED_VAR")
