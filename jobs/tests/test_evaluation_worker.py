from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from conftest import load_worker_entrypoint

entrypoint = load_worker_entrypoint("evaluation_worker")


def _fake_result(text: str = "", error: str | None = None):
    class R:
        def __init__(self) -> None:
            self.text = text
            self.error = error
            self.latency_seconds = 0.1
            self.ok = error is None

    return R()


def test_run_aggregates_pass_fail_and_errored_cases() -> None:
    callback = MagicMock()
    cases = [
        {"caseId": "c1", "prompt": "2+2?", "deterministicCheck": "4"},
        {"caseId": "c2", "prompt": "3+3?", "deterministicCheck": "6"},
        {"caseId": "c3", "prompt": "unchecked"},
        {"caseId": "c4", "prompt": "fails"},
    ]
    responses = iter(
        [
            _fake_result(text="the answer is 4"),
            _fake_result(text="wrong answer"),
            _fake_result(text="anything"),
            _fake_result(error="timeout"),
        ]
    )
    submit = MagicMock(side_effect=lambda *_a, **_kw: next(responses))

    entrypoint.run(
        workflow_id="wf-1",
        subscription_id="sub-1",
        environment_id="demo123",
        run_id="run-1",
        cases=cases,
        name_prefix="llm",
        callback=callback,
        resolve_ip=MagicMock(return_value="10.0.1.5"),
        submit=submit,
    )

    diagnostics = callback.complete_workflow.call_args.kwargs["diagnostics"]
    aggregate = diagnostics["quality"]["aggregate"]
    assert aggregate["passCount"] == 1
    assert aggregate["failCount"] == 1
    assert aggregate["skippedCount"] == 1
    assert aggregate["erroredCount"] == 1
    assert aggregate["totalCount"] == 4
    assert diagnostics["completenessIndicator"] == "partial"
    assert diagnostics["runId"] == "run-1"


def test_run_reports_complete_when_no_errors() -> None:
    callback = MagicMock()
    cases = [{"caseId": "c1", "prompt": "hi", "deterministicCheck": "hello"}]
    submit = MagicMock(return_value=_fake_result(text="hello there"))

    entrypoint.run(
        workflow_id="wf-2",
        subscription_id="sub-1",
        environment_id="demo123",
        run_id="run-2",
        cases=cases,
        name_prefix="llm",
        callback=callback,
        resolve_ip=MagicMock(return_value="10.0.1.5"),
        submit=submit,
    )

    diagnostics = callback.complete_workflow.call_args.kwargs["diagnostics"]
    assert diagnostics["completenessIndicator"] == "complete"
    callback.complete_workflow.assert_called_once_with(
        "wf-2", status="completed", phase="completed", diagnostics=diagnostics
    )


def test_run_raises_when_cases_empty() -> None:
    callback = MagicMock()
    try:
        entrypoint.run(
            workflow_id="wf-3",
            subscription_id="sub-1",
            environment_id="demo123",
            run_id="run-3",
            cases=[],
            name_prefix="llm",
            callback=callback,
        )
        raise AssertionError("expected CallbackClientError")
    except entrypoint.CallbackClientError:
        pass
    callback.complete_workflow.assert_not_called()


@pytest.mark.parametrize(
    "case,text,expected",
    [
        (
            {"input": "2+2", "evaluationRule": "exact-match", "expectedOutput": "4"},
            "24",
            "fail",
        ),
        (
            {"input": "2+2", "evaluationRule": "exact-match", "expectedOutput": "4"},
            "<think>checking</think>4",
            "pass",
        ),
        (
            {
                "input": "river",
                "evaluationRule": "contains",
                "expectedSubstring": "Nile",
            },
            "<think>Nile</think>Amazon",
            "fail",
        ),
        ({"input": "capital", "evaluationRule": "regex:(?i)^paris$"}, "Paris", "pass"),
        ({"input": "symbol", "evaluationRule": "regex:^Au$"}, "Au", "pass"),
        ({"input": "symbol", "evaluationRule": "regex:^Au$"}, "au", "fail"),
        (
            {
                "input": "river",
                "evaluationRule": "contains",
                "expectedSubstring": "Nile",
            },
            "<think>Nile</think>",
            "fail",
        ),
        ({"input": "bad rule", "evaluationRule": "unknown"}, "answer", "errored"),
        ({"input": "bad pattern", "evaluationRule": "regex:["}, "answer", "errored"),
        ({"input": "missing rule"}, "answer", "errored"),
        ({"input": "null rule", "evaluationRule": None}, "answer", "errored"),
        ({"input": "empty rule", "evaluationRule": ""}, "answer", "errored"),
    ],
)
def test_worker_uses_backend_golden_scoring(case, text, expected) -> None:
    submit = MagicMock(return_value=_fake_result(text))
    result = entrypoint._evaluate_case("http://runtime", {"caseId": "c1", **case}, submit)
    assert result["status"] == expected
    submit.assert_called_once_with("http://runtime", case["input"])
    if expected == "errored":
        assert result["error"]


def test_legacy_substring_check_also_grades_only_the_final_answer() -> None:
    result = entrypoint._evaluate_case(
        "http://runtime",
        {"caseId": "c1", "prompt": "river", "deterministicCheck": "Nile"},
        MagicMock(return_value=_fake_result("<think>Nile</think>Amazon")),
    )
    assert result["status"] == "fail"


def test_invalid_canonical_rules_make_the_report_partial() -> None:
    callback = MagicMock()
    entrypoint.run(
        workflow_id="wf-invalid",
        subscription_id="sub-1",
        environment_id="demo123",
        run_id="run-invalid",
        cases=[{"caseId": "c1", "input": "missing rule"}],
        name_prefix="llm",
        callback=callback,
        resolve_ip=MagicMock(return_value="10.0.1.5"),
        submit=MagicMock(return_value=_fake_result("answer")),
    )
    diagnostics = callback.complete_workflow.call_args.kwargs["diagnostics"]
    assert diagnostics["completenessIndicator"] == "partial"
    assert diagnostics["quality"]["aggregate"]["erroredCount"] == 1
    assert diagnostics["quality"]["aggregate"]["skippedCount"] == 0
