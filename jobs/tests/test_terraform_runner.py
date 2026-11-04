from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from conftest import load_worker_entrypoint

entrypoint = load_worker_entrypoint("terraform_runner")
TerraformRunError = entrypoint.TerraformRunError
run = entrypoint.run


def _completed(returncode: int, *, stdout: str = "", stderr: str = "") -> Any:
    return subprocess.CompletedProcess(
        args=["terraform"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_apply_success_reports_progress_and_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path) -> Any:
        calls.append(args)
        if args[:1] == ["init"]:
            return _completed(0)
        if args[:1] == ["apply"]:
            return _completed(0)
        if args[:1] == ["output"]:
            return _completed(0, stdout='{"backend_fqdn": {"value": "demo.example"}}')
        raise AssertionError(f"unexpected terraform invocation: {args}")

    monkeypatch.setattr(entrypoint, "_run_terraform", fake_run)

    callback = MagicMock()
    run(
        workflow_id="wf-1",
        environment_id="demo123",
        action="apply",
        terraform_variables={"environment_id": "demo123"},
        working_dir=tmp_path,
        callback=callback,
    )

    tfvars_path = tmp_path / "terraform.tfvars.json"
    assert tfvars_path.exists()
    assert '"environment_id"' in tfvars_path.read_text(encoding="utf-8")

    assert calls[0][0] == "init"
    assert calls[1][0] == "apply"
    assert calls[2][0] == "output"

    callback.report_progress.assert_any_call("wf-1", phase="initializing")
    callback.complete_workflow.assert_called_once_with(
        "wf-1",
        status="completed",
        phase="completed",
        diagnostics={
            "action": "apply",
            "outputs": {"backend_fqdn": {"value": "demo.example"}},
        },
    )


def test_destroy_success_skips_output_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], *, cwd: Path) -> Any:
        if args[:1] in (["init"], ["destroy"]):
            return _completed(0)
        raise AssertionError(f"unexpected terraform invocation: {args}")

    monkeypatch.setattr(entrypoint, "_run_terraform", fake_run)

    callback = MagicMock()
    run(
        workflow_id="wf-2",
        environment_id="demo123",
        action="destroy",
        terraform_variables={"environment_id": "demo123"},
        working_dir=tmp_path,
        callback=callback,
    )

    callback.complete_workflow.assert_called_once_with(
        "wf-2",
        status="completed",
        phase="completed",
        diagnostics={"action": "destroy", "outputs": {}},
    )


def test_apply_failure_raises_terraform_run_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(args: list[str], *, cwd: Path) -> Any:
        if args[:1] == ["init"]:
            return _completed(0)
        if args[:1] == ["apply"]:
            return _completed(1, stderr="boom")
        raise AssertionError(f"unexpected terraform invocation: {args}")

    monkeypatch.setattr(entrypoint, "_run_terraform", fake_run)

    callback = MagicMock()
    with pytest.raises(TerraformRunError):
        run(
            workflow_id="wf-3",
            environment_id="demo123",
            action="apply",
            terraform_variables={},
            working_dir=tmp_path,
            callback=callback,
        )
    callback.complete_workflow.assert_not_called()


def test_init_failure_raises_before_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], *, cwd: Path) -> Any:
        assert args[:1] == ["init"]
        return _completed(1, stderr="init boom")

    monkeypatch.setattr(entrypoint, "_run_terraform", fake_run)

    callback = MagicMock()
    with pytest.raises(TerraformRunError, match="init"):
        run(
            workflow_id="wf-4",
            environment_id="demo123",
            action="apply",
            terraform_variables={},
            working_dir=tmp_path,
            callback=callback,
        )


def test_main_reports_failure_and_exits_nonzero_on_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrypoint_module = entrypoint

    monkeypatch.setenv("WORKFLOW_ID", "wf-5")
    monkeypatch.setenv("JOB_INPUT_JSON", '{"action": "apply", "terraformVariables": {}}')

    callback = MagicMock()
    callback.__enter__ = MagicMock(return_value=callback)
    callback.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        entrypoint_module, "WorkflowCallbackClient", MagicMock(return_value=callback)
    )
    monkeypatch.setattr(
        entrypoint_module,
        "run",
        MagicMock(side_effect=RuntimeError("something blew up")),
    )

    exit_code = entrypoint_module.main()

    assert exit_code == 1
    callback.complete_workflow.assert_called_once_with(
        "wf-5",
        status="failed",
        phase="failed",
        diagnostics={"action": "apply", "error": "something blew up"},
    )


def test_blob_url_none_when_env_vars_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TF_STATE_STORAGE_ACCOUNT", raising=False)
    monkeypatch.delenv("TF_STATE_CONTAINER", raising=False)
    assert entrypoint._blob_url("demo123.tfstate") is None


def test_blob_url_built_from_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_STATE_STORAGE_ACCOUNT", "exampletfstate")
    monkeypatch.setenv("TF_STATE_CONTAINER", "tfstate")
    assert entrypoint._blob_url("demo123.tfstate") == (
        "https://exampletfstate.blob.core.windows.net/tfstate/demo123.tfstate"
    )


def test_download_remote_state_writes_file_on_200(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TF_STATE_STORAGE_ACCOUNT", "acct")
    monkeypatch.setenv("TF_STATE_CONTAINER", "tfstate")
    monkeypatch.setattr(entrypoint, "_storage_bearer_headers", lambda: {"Authorization": "x"})

    response = MagicMock(status_code=200, content=b'{"resources": []}')
    monkeypatch.setattr(entrypoint.httpx, "get", MagicMock(return_value=response))

    entrypoint._download_remote_state(tmp_path, "demo123")

    assert (tmp_path / "terraform.tfstate").read_bytes() == b'{"resources": []}'


def test_download_remote_state_noop_without_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TF_STATE_STORAGE_ACCOUNT", raising=False)
    monkeypatch.delenv("TF_STATE_CONTAINER", raising=False)

    entrypoint._download_remote_state(tmp_path, "demo123")

    assert not (tmp_path / "terraform.tfstate").exists()


def test_upload_remote_state_puts_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TF_STATE_STORAGE_ACCOUNT", "acct")
    monkeypatch.setenv("TF_STATE_CONTAINER", "tfstate")
    monkeypatch.setattr(entrypoint, "_storage_bearer_headers", lambda: {"Authorization": "x"})
    (tmp_path / "terraform.tfstate").write_bytes(b'{"resources": []}')

    put_mock = MagicMock(return_value=MagicMock(status_code=201))
    monkeypatch.setattr(entrypoint.httpx, "put", put_mock)

    entrypoint._upload_remote_state(tmp_path, "demo123")

    put_mock.assert_called_once()
    assert put_mock.call_args.kwargs["content"] == b'{"resources": []}'


def test_upload_remote_state_noop_when_state_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TF_STATE_STORAGE_ACCOUNT", "acct")
    monkeypatch.setenv("TF_STATE_CONTAINER", "tfstate")
    put_mock = MagicMock()
    monkeypatch.setattr(entrypoint.httpx, "put", put_mock)

    entrypoint._upload_remote_state(tmp_path, "demo123")

    put_mock.assert_not_called()


def test_apply_downloads_and_uploads_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(args: list[str], *, cwd: Path) -> Any:
        if args[:1] == ["init"]:
            return _completed(0)
        if args[:1] == ["apply"]:
            return _completed(0)
        if args[:1] == ["output"]:
            return _completed(0, stdout="{}")
        raise AssertionError(f"unexpected terraform invocation: {args}")

    monkeypatch.setattr(entrypoint, "_run_terraform", fake_run)
    download_shared_mock = MagicMock()
    download_mock = MagicMock()
    upload_mock = MagicMock()
    monkeypatch.setattr(entrypoint, "_download_shared_state", download_shared_mock)
    monkeypatch.setattr(entrypoint, "_download_remote_state", download_mock)
    monkeypatch.setattr(entrypoint, "_upload_remote_state", upload_mock)

    callback = MagicMock()
    run(
        workflow_id="wf-6",
        environment_id="demo123",
        action="apply",
        terraform_variables={},
        working_dir=tmp_path,
        callback=callback,
    )

    download_shared_mock.assert_called_once_with(tmp_path)
    download_mock.assert_called_once_with(tmp_path, "demo123")
    upload_mock.assert_called_once_with(tmp_path, "demo123")


def test_download_shared_state_writes_sibling_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TF_STATE_STORAGE_ACCOUNT", "acct")
    monkeypatch.setenv("TF_STATE_CONTAINER", "tfstate")
    monkeypatch.setattr(entrypoint, "_storage_bearer_headers", lambda: {"Authorization": "x"})

    response = MagicMock(status_code=200, content=b'{"outputs": {}}')
    get_mock = MagicMock(return_value=response)
    monkeypatch.setattr(entrypoint.httpx, "get", get_mock)

    working_dir = tmp_path / "infra" / "demo"
    working_dir.mkdir(parents=True)
    entrypoint._download_shared_state(working_dir)

    get_mock.assert_called_once()
    assert get_mock.call_args.args[0] == (
        "https://acct.blob.core.windows.net/tfstate/infra-shared.tfstate"
    )
    assert (tmp_path / "infra" / "shared" / "terraform.tfstate").read_bytes() == (
        b'{"outputs": {}}'
    )


def test_download_shared_state_noop_without_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TF_STATE_STORAGE_ACCOUNT", raising=False)
    monkeypatch.delenv("TF_STATE_CONTAINER", raising=False)

    working_dir = tmp_path / "infra" / "demo"
    working_dir.mkdir(parents=True)
    entrypoint._download_shared_state(working_dir)

    assert not (tmp_path / "infra" / "shared").exists()
