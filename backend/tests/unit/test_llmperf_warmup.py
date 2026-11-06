from __future__ import annotations

import json
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
import src.performance.llmperf_runner as runner_module
from src.performance.llmperf_runner import LlmPerfRunner, PerformanceRunOverloadError


def _workload(warmup_count: int, measured_count: int, concurrency: int) -> dict:
    return {
        "warmup": {"requestCount": warmup_count},
        "inputProfile": {
            "meanInputTokens": 128,
            "stddevInputTokens": 16,
            "meanOutputTokens": 64,
            "stddevOutputTokens": 8,
        },
        "durationOrRequestCount": {"requestCount": measured_count},
        "completionCriteria": {"targetCompletedRequests": measured_count},
        "concurrency": concurrency,
        "safetyLimits": {"timeoutSeconds": 60, "maxRequests": 80},
    }


def test_runner_remains_importable_as_the_only_packaged_source(tmp_path) -> None:
    runner = tmp_path / "llmperf_runner.py"
    shutil.copyfile(runner_module.__file__, runner)
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import importlib.util, sys; "
            "spec = importlib.util.spec_from_file_location('runner', sys.argv[1]); "
            "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)",
            str(runner),
        ],
        check=True,
        cwd=tmp_path,
    )


@pytest.mark.parametrize("warmup_count,measured_count,concurrency", [(3, 25, 1), (5, 50, 10)])
def test_real_tool_invocations_are_separate_and_ordered(
    tmp_path, monkeypatch, warmup_count, measured_count, concurrency
) -> None:
    # Execute a local fake of the upstream CLI, not an actual inference server.
    script = tmp_path / "token_benchmark_ray.py"
    script.write_text(
        """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
def value(flag):
    return args[args.index(flag) + 1]
path = Path(os.environ["TEST_INVOCATIONS"])
calls = json.loads(path.read_text()) if path.exists() else []
calls.append({"args": args, "base": os.environ["OPENAI_API_BASE"]})
path.write_text(json.dumps(calls))
count = int(value("--max-num-completed-requests"))
if len(calls) == 1:
    result = {"results_num_completed_requests": count,
              "results_num_requests_started": count, "results_number_errors": 0}
else:
    result = {"metrics": {"timeToFirstTokenMs": {"p50": 11, "p95": 12},
                          "interTokenLatencyMs": {"p50": 2, "p95": 3},
                          "endToEndLatencyMs": {"p50": 20, "p95": 25},
                          "throughputTokensPerSec": 30},
              "requestFailures": {"count": 1, "total": count}}
print(json.dumps(result))
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        sys.modules, "llmperf", SimpleNamespace(__file__=str(tmp_path / "__init__.py"))
    )
    log = tmp_path / "calls.json"
    monkeypatch.setenv("TEST_INVOCATIONS", str(log))
    monkeypatch.chdir(tmp_path)
    workload = _workload(warmup_count, measured_count, concurrency)

    result = LlmPerfRunner().run(
        base_url="http://inference:8000", workload=workload, model_id="model"
    )

    calls = json.loads(log.read_text())
    assert len(calls) == 2

    def value(args, flag):
        return args[args.index(flag) + 1]

    for call, count, parallelism in zip(
        calls, [warmup_count, measured_count], [1, concurrency], strict=True
    ):
        args = call["args"]
        assert call["base"] == "http://inference:8000/v1"
        assert value(args, "--model") == "model"
        assert value(args, "--max-num-completed-requests") == str(count)
        assert value(args, "--num-concurrent-requests") == str(parallelism)
        assert value(args, "--timeout") == "60"
        assert value(args, "--mean-input-tokens") == "128"
        assert value(args, "--stddev-input-tokens") == "16"
        assert value(args, "--mean-output-tokens") == "64"
        assert value(args, "--stddev-output-tokens") == "8"
        assert value(args, "--llm-api") == "openai"
        assert value(args, "--additional-sampling-params") == "{}"
    assert result["requestFailures"] == {
        "count": 1,
        "total": measured_count,
        "rate": round(1 / measured_count, 4),
    }
    assert result["metrics"]["timeToFirstTokenMs"] == {"p50": 11.0, "p95": 12.0}
    assert result["testConditions"]["warmup"] == {"requestCount": warmup_count}
    assert result["testConditions"]["warmupExecution"] == {
        "completedRequests": warmup_count,
        "failedRequests": 0,
    }


@pytest.mark.parametrize(
    "warmup",
    [
        {
            "results_num_completed_requests": 2,
            "results_num_requests_started": 3,
            "results_number_errors": 1,
        },
        {
            "results_num_completed_requests": 2,
            "results_num_requests_started": 2,
            "results_number_errors": 0,
        },
        {"results_num_completed_requests": 3, "results_num_requests_started": 3},
        {
            "results_num_completed_requests": 3,
            "results_num_requests_started": 3,
            "results_number_errors": 0,
            "status": "incomplete",
        },
    ],
)
def test_invalid_or_incomplete_warmup_never_starts_measurement(warmup) -> None:
    calls = []

    def evaluator(**kwargs):
        calls.append(kwargs)
        return warmup

    with pytest.raises(PerformanceRunOverloadError, match="warm-up") as exc:
        LlmPerfRunner(evaluator=evaluator).run(
            base_url="http://inference", workload=_workload(3, 25, 1), model_id="model"
        )
    assert exc.value.partial_result is None
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["timeout", "exit", "upstream-timeout"])
def test_subprocess_failure_during_warmup_is_not_a_measured_partial(
    tmp_path, monkeypatch, failure
) -> None:
    (tmp_path / "token_benchmark_ray.py").touch()
    monkeypatch.setitem(
        sys.modules, "llmperf", SimpleNamespace(__file__=str(tmp_path / "__init__.py"))
    )
    monkeypatch.chdir(tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if failure == "upstream-timeout":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Test timed out before all requests could be completed.",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="warmup error")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(PerformanceRunOverloadError, match="warm-up failed") as exc:
        LlmPerfRunner().run(
            base_url="http://inference", workload=_workload(3, 25, 1), model_id="model"
        )
    assert exc.value.partial_result is None
    assert len(calls) == 1


def test_measured_overload_preserves_partial_metrics_after_warmup() -> None:
    def evaluator(**kwargs):
        if kwargs["workload"].get("_warmupPhase"):
            return {
                "results_num_completed_requests": 3,
                "results_num_requests_started": 3,
                "results_number_errors": 0,
            }
        return {
            "status": "incomplete",
            "metrics": {
                "timeToFirstTokenMs": {"p50": 10, "p95": 20},
                "interTokenLatencyMs": {"p50": 1, "p95": 2},
                "endToEndLatencyMs": {"p50": 30, "p95": 40},
                "throughputTokensPerSec": 50,
            },
            "requestFailures": {"count": 1, "total": 10},
        }

    with pytest.raises(PerformanceRunOverloadError) as exc:
        LlmPerfRunner(evaluator=evaluator).run(
            base_url="http://inference", workload=_workload(3, 25, 1), model_id="model"
        )
    assert exc.value.partial_result["requestFailures"] == {"count": 1, "total": 10, "rate": 0.1}
    assert exc.value.partial_result["testConditions"]["warmupExecution"]["completedRequests"] == 3


@pytest.mark.parametrize(
    "configured_count, step_seconds, expected_warmups",
    [(0, 2, 1), (0, 3, 1), (3, 3, 3), (0, 1, 2), (4, 1, 4)],
)
def test_duration_warmup_executes_tool_until_both_minimums(
    tmp_path, monkeypatch, configured_count, step_seconds, expected_warmups
) -> None:
    script = tmp_path / "token_benchmark_ray.py"
    script.write_text(
        """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
def value(flag):
    return args[args.index(flag) + 1]
path = Path(os.environ["TEST_INVOCATIONS"])
calls = json.loads(path.read_text()) if path.exists() else []
calls.append({"args": args, "base": os.environ["OPENAI_API_BASE"]})
path.write_text(json.dumps(calls))
count = int(value("--max-num-completed-requests"))
if count == 1:
    result = {"results_num_completed_requests": 1,
              "results_num_requests_started": 1, "results_number_errors": 0}
else:
    result = {"metrics": {"timeToFirstTokenMs": {"p50": 11, "p95": 12},
                          "interTokenLatencyMs": {"p50": 2, "p95": 3},
                          "endToEndLatencyMs": {"p50": 20, "p95": 25},
                          "throughputTokensPerSec": 30},
              "requestFailures": {"count": 0, "total": count}}
print(json.dumps(result))
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        sys.modules, "llmperf", SimpleNamespace(__file__=str(tmp_path / "__init__.py"))
    )
    log = tmp_path / "calls.json"
    monkeypatch.setenv("TEST_INVOCATIONS", str(log))
    monkeypatch.chdir(tmp_path)
    clock = [0.0]
    monkeypatch.setattr(runner_module, "monotonic", lambda: clock[0])
    runner = LlmPerfRunner()

    def evaluator(**kwargs):
        result = runner._default_evaluator(**kwargs)
        if kwargs["workload"].get("_warmupPhase"):
            clock[0] += step_seconds
        return result

    runner._evaluator = evaluator
    workload = _workload(configured_count, 50, 10)
    workload["warmup"]["durationSeconds"] = 2
    result = runner.run(base_url="http://inference", workload=workload, model_id="model")

    calls = json.loads(log.read_text())
    assert len(calls) == expected_warmups + 1
    for call in calls:
        assert call["base"] == "http://inference/v1"
        args = call["args"]
        assert args[args.index("--model") + 1] == "model"
        assert args[args.index("--mean-input-tokens") + 1] == "128"
        assert args[args.index("--mean-output-tokens") + 1] == "64"
    for call in calls[:-1]:
        args = call["args"]
        assert args[args.index("--max-num-completed-requests") + 1] == "1"
        assert args[args.index("--num-concurrent-requests") + 1] == "1"
    args = calls[-1]["args"]
    assert args[args.index("--max-num-completed-requests") + 1] == "50"
    assert args[args.index("--num-concurrent-requests") + 1] == "10"
    assert result["testConditions"]["warmupExecution"] == {
        "completedRequests": expected_warmups,
        "failedRequests": 0,
        "elapsedSeconds": expected_warmups * step_seconds,
    }
    assert result["requestFailures"] == {"count": 0, "total": 50, "rate": 0}


@pytest.mark.parametrize("failure", ["error", "incomplete", "timeout", "deadline"])
@pytest.mark.parametrize("failure_call", [1, 2])
def test_duration_warmup_failure_never_starts_measurement(
    monkeypatch, failure, failure_call
) -> None:
    clock = [0.0]
    monkeypatch.setattr(runner_module, "monotonic", lambda: clock[0])
    calls = []

    def evaluator(**kwargs):
        calls.append(kwargs)
        assert kwargs["workload"].get("_warmupPhase")
        if len(calls) == failure_call:
            if failure == "timeout":
                raise PerformanceRunOverloadError("timed out")
            if failure == "deadline":
                clock[0] = 121
            if failure == "error":
                return {
                    "results_num_completed_requests": 0,
                    "results_num_requests_started": 1,
                    "results_number_errors": 1,
                }
            if failure == "incomplete":
                return {
                    "results_num_completed_requests": 0,
                    "results_num_requests_started": 0,
                    "results_number_errors": 0,
                }
        return {
            "results_num_completed_requests": 1,
            "results_num_requests_started": 1,
            "results_number_errors": 0,
        }

    workload = _workload(0, 25, 1)
    workload["warmup"] = {"durationSeconds": 2}
    with pytest.raises(PerformanceRunOverloadError, match="warm-up") as exc:
        LlmPerfRunner(evaluator=evaluator).run(
            base_url="http://inference", workload=workload, model_id="model"
        )
    assert exc.value.partial_result is None
    assert len(calls) == failure_call


def test_duration_batch_subprocess_timeout_is_clamped_to_remaining_deadline(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "token_benchmark_ray.py").touch()
    monkeypatch.setitem(
        sys.modules, "llmperf", SimpleNamespace(__file__=str(tmp_path / "__init__.py"))
    )
    monkeypatch.chdir(tmp_path)
    clock = [0.0]
    monkeypatch.setattr(runner_module, "monotonic", lambda: clock[0])
    timeouts = []

    def run(command, **kwargs):
        timeouts.append(kwargs["timeout"])
        if len(timeouts) == 1:
            clock[0] = 100
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "results_num_completed_requests": 1,
                        "results_num_requests_started": 1,
                        "results_number_errors": 0,
                    }
                ),
                stderr="",
            )
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)
    workload = _workload(0, 25, 1)
    workload["warmup"] = {"durationSeconds": 110}
    with pytest.raises(PerformanceRunOverloadError, match="warm-up failed"):
        LlmPerfRunner().run(base_url="http://inference", workload=workload, model_id="model")
    assert timeouts == [120, 20]
