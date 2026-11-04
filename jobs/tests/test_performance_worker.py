from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from conftest import load_worker_entrypoint

entrypoint = load_worker_entrypoint("performance_worker")


def _fake_result(latency: float, error: str | None = None):
    class R:
        def __init__(self) -> None:
            self.latency_seconds = latency
            self.error = error
            self.ok = error is None

    return R()


def test_run_computes_percentiles_and_throughput(monkeypatch) -> None:
    ticks = iter([100.0, 102.0])
    monkeypatch.setattr(entrypoint, "perf_counter", lambda: next(ticks))
    callback = MagicMock()
    latencies = [0.1, 0.2, 0.3, 0.4, 0.5]
    responses = iter(_fake_result(lat) for lat in latencies)
    submit = MagicMock(side_effect=lambda *_a, **_kw: next(responses))

    entrypoint.run(
        workflow_id="wf-1",
        subscription_id="sub-1",
        environment_id="demo123",
        run_id="run-1",
        prompt="hi",
        concurrency=1,
        request_count=5,
        name_prefix="llm",
        callback=callback,
        resolve_ip=MagicMock(return_value="10.0.1.5"),
        submit=submit,
    )

    diagnostics = callback.complete_workflow.call_args.kwargs["diagnostics"]
    perf = diagnostics["performance"]
    assert perf["failures"]["count"] == 0
    assert perf["failures"]["total"] == 5
    assert perf["endToEndLatencySeconds"]["p50"] == 0.3
    assert perf["throughput"] == {"value": 2.5, "unit": "requests_per_second"}
    assert perf["timeToFirstToken"] == {"available": False}
    assert perf["acceleratorUtilization"] == {"available": False}
    assert diagnostics["completenessIndicator"] == "complete"


def test_run_reports_partial_when_failures_occur() -> None:
    callback = MagicMock()
    responses = iter([_fake_result(0.1), _fake_result(0.0, error="timeout")])
    submit = MagicMock(side_effect=lambda *_a, **_kw: next(responses))

    entrypoint.run(
        workflow_id="wf-2",
        subscription_id="sub-1",
        environment_id="demo123",
        run_id="run-2",
        prompt="hi",
        concurrency=1,
        request_count=2,
        name_prefix="llm",
        callback=callback,
        resolve_ip=MagicMock(return_value="10.0.1.5"),
        submit=submit,
    )

    diagnostics = callback.complete_workflow.call_args.kwargs["diagnostics"]
    assert diagnostics["performance"]["failures"]["count"] == 1
    assert diagnostics["completenessIndicator"] == "partial"


def test_run_clamps_concurrency_and_request_count_to_hard_limits() -> None:
    callback = MagicMock()
    submit = MagicMock(return_value=_fake_result(0.1))

    entrypoint.run(
        workflow_id="wf-3",
        subscription_id="sub-1",
        environment_id="demo123",
        run_id="run-3",
        prompt="hi",
        concurrency=10_000,
        request_count=entrypoint.HARD_MAX_REQUESTS + 500,
        name_prefix="llm",
        callback=callback,
        resolve_ip=MagicMock(return_value="10.0.1.5"),
        submit=submit,
    )

    assert submit.call_count == entrypoint.HARD_MAX_REQUESTS


def test_run_raises_when_request_count_not_positive() -> None:
    callback = MagicMock()
    with pytest.raises(entrypoint.CallbackClientError):
        entrypoint.run(
            workflow_id="wf-4",
            subscription_id="sub-1",
            environment_id="demo123",
            run_id="run-4",
            prompt="hi",
            concurrency=1,
            request_count=0,
            name_prefix="llm",
            callback=callback,
        )
    callback.complete_workflow.assert_not_called()
