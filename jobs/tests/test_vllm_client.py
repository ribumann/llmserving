from __future__ import annotations

import httpx
from common.vllm_client import check_health, submit_prompt


def _client_with_transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_submit_prompt_success_returns_text_and_latency() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/completions"
        return httpx.Response(200, json={"choices": [{"text": "hello world"}]})

    client = _client_with_transport(handler)
    result = submit_prompt("http://10.0.1.5:8000", "hi", client=client)

    assert result.ok
    assert result.text == "hello world"
    assert result.latency_seconds >= 0
    assert result.error is None


def test_submit_prompt_http_error_status_sets_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    client = _client_with_transport(handler)
    result = submit_prompt("http://10.0.1.5:8000", "hi", client=client)

    assert not result.ok
    assert "500" in (result.error or "")


def test_submit_prompt_transport_error_sets_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client_with_transport(handler)
    result = submit_prompt("http://10.0.1.5:8000", "hi", client=client)

    assert not result.ok
    assert "connection refused" in (result.error or "")


def test_check_health_true_on_200() -> None:
    client = _client_with_transport(lambda _r: httpx.Response(200))
    assert check_health("http://10.0.1.5:8000", client=client) is True


def test_check_health_false_on_non_200() -> None:
    client = _client_with_transport(lambda _r: httpx.Response(503))
    assert check_health("http://10.0.1.5:8000", client=client) is False


def test_check_health_false_on_transport_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client_with_transport(handler)
    assert check_health("http://10.0.1.5:8000", client=client) is False
