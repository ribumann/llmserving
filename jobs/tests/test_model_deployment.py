from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from conftest import load_worker_entrypoint

entrypoint = load_worker_entrypoint("model_deployment")


def test_build_script_lines_never_includes_hf_token_as_separate_diagnostic() -> None:
    lines = entrypoint._build_script_lines(
        "meta-llama/Llama-3-8B", "hf_secret123", ["--max-model-len", "4096"]
    )
    assert len(lines) == 1
    assert "hf_secret123" in lines[0]  # present in the command sent to the VM...
    assert lines[0].startswith("/opt/llmserving/run-vllm.sh")


def test_build_script_lines_forwards_revision_flag_after_extra_args() -> None:
    """Regression test: `model_repo` (the real Hugging Face repo id) and
    `revision` (a git ref *within* that repo, default "main") must both reach
    vLLM as separate CLI flags (`--model`, `--revision`) - passing only a
    revision as the model id (the production bug) makes vLLM try to load a
    model literally named e.g. "main", which always fails.
    """
    lines = entrypoint._build_script_lines(
        "meta-llama/Llama-3-8B",
        "hf_secret123",
        ["--max-model-len", "4096"],
        revision="refs/pr/12/head",
    )
    assert len(lines) == 1
    assert lines[0] == (
        "/opt/llmserving/run-vllm.sh meta-llama/Llama-3-8B hf_secret123 "
        "--max-model-len 4096 --revision refs/pr/12/head"
    )


def test_build_script_lines_defaults_revision_to_main() -> None:
    lines = entrypoint._build_script_lines("meta-llama/Llama-3-8B", "hf_secret123", [])
    assert lines[0] == (
        "/opt/llmserving/run-vllm.sh meta-llama/Llama-3-8B hf_secret123 --revision main"
    )


def test_run_success_ensures_vm_running_then_dispatches_and_polls_health() -> None:
    callback = MagicMock()
    dispatch = MagicMock()
    ensure_running = MagicMock(return_value="PowerState/deallocated")
    resolve_ip = MagicMock(return_value="10.0.1.5")
    is_healthy = MagicMock(side_effect=[False, True])
    sleep = MagicMock()

    entrypoint.run(
        workflow_id="wf-1",
        subscription_id="sub-1",
        environment_id="demo123",
        model_repo="meta-llama/Llama-3-8B",
        hf_token="hf_secret",
        name_prefix="llm",
        extra_args=[],
        health_check_attempts=5,
        health_check_interval_seconds=0,
        callback=callback,
        resolve_ip=resolve_ip,
        dispatch_run_command=dispatch,
        ensure_running=ensure_running,
        is_healthy=is_healthy,
        sleep=sleep,
    )

    ensure_running.assert_called_once_with("sub-1", "demo123", name_prefix="llm")
    dispatch.assert_called_once()
    assert is_healthy.call_count == 2
    sleep.assert_called_once_with(0)
    callback.complete_workflow.assert_called_once_with(
        "wf-1",
        status="completed",
        phase="completed",
        diagnostics={"vllmBaseUrl": "http://10.0.1.5:8000", "modelRepo": "meta-llama/Llama-3-8B"},
    )


def test_run_reports_periodic_progress_during_a_long_health_check_wait() -> None:
    """`docker run -d` (infra/demo/cloud-init.tftpl) returns as soon as the
    container starts, before vLLM finishes downloading/loading model weights -
    a cold-start 7B+ download can take well beyond the old 5-minute budget.
    Progress must be reported periodically during the wait, not only once at
    the start, so a long-but-healthy wait is distinguishable from a stuck one.
    """
    callback = MagicMock()
    is_healthy = MagicMock(side_effect=[False] * 19 + [True])

    entrypoint.run(
        workflow_id="wf-4",
        subscription_id="sub-1",
        environment_id="demo123",
        model_repo="repo",
        hf_token="token",
        name_prefix="llm",
        extra_args=[],
        health_check_attempts=20,
        health_check_interval_seconds=0,
        callback=callback,
        resolve_ip=MagicMock(return_value="10.0.1.5"),
        dispatch_run_command=MagicMock(),
        ensure_running=MagicMock(return_value="PowerState/running"),
        is_healthy=is_healthy,
        sleep=MagicMock(),
    )

    progress_calls = [
        call
        for call in callback.report_progress.call_args_list
        if call.kwargs.get("phase") == "waiting-for-vllm-health" and call.kwargs.get("diagnostics")
    ]
    assert len(progress_calls) >= 1
    assert progress_calls[0].kwargs["diagnostics"] == {"attempt": 2, "maxAttempts": 20}


def test_run_raises_when_health_check_never_succeeds() -> None:
    callback = MagicMock()

    with pytest.raises(RuntimeError, match="did not become healthy"):
        entrypoint.run(
            workflow_id="wf-2",
            subscription_id="sub-1",
            environment_id="demo123",
            model_repo="repo",
            hf_token="token",
            name_prefix="llm",
            extra_args=[],
            health_check_attempts=2,
            health_check_interval_seconds=0,
            callback=callback,
            resolve_ip=MagicMock(return_value="10.0.1.5"),
            dispatch_run_command=MagicMock(),
            ensure_running=MagicMock(return_value="PowerState/running"),
            is_healthy=MagicMock(return_value=False),
            sleep=MagicMock(),
        )
    callback.complete_workflow.assert_not_called()


def test_main_never_leaks_hf_token_into_failure_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKFLOW_ID", "wf-3")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-1")
    monkeypatch.setenv(
        "JOB_INPUT_JSON",
        '{"environmentId": "demo123", "modelRepo": "repo", "hfToken": "super-secret-token"}',
    )

    callback = MagicMock()
    callback.__enter__ = MagicMock(return_value=callback)
    callback.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(entrypoint, "WorkflowCallbackClient", MagicMock(return_value=callback))
    monkeypatch.setattr(
        entrypoint, "run", MagicMock(side_effect=RuntimeError("vLLM never came up"))
    )

    exit_code = entrypoint.main()

    assert exit_code == 1
    diagnostics = callback.complete_workflow.call_args.kwargs["diagnostics"]
    assert "super-secret-token" not in str(diagnostics)
    assert diagnostics == {"error": "vLLM never came up"}
