from __future__ import annotations

import json
import subprocess
from contextlib import nullcontext
from unittest.mock import MagicMock

import httpx
import pytest
from azure.core.exceptions import ClientAuthenticationError

from conftest import load_worker_entrypoint

entrypoint = load_worker_entrypoint("terraform_runner")
STATE = b'{"version": 4, "resources": [], "outputs": {}}'


@pytest.fixture(autouse=True)
def isolated_host_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "TF_STATE_STORAGE_ACCOUNT",
        "TF_STATE_CONTAINER",
        "CONTAINER_APP_JOB_NAME",
        "CONTAINER_APP_NAME",
        "IDENTITY_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_STATE_STORAGE_ACCOUNT", "teststate")
    monkeypatch.setenv("TF_STATE_CONTAINER", "tfstate")
    monkeypatch.setattr(
        entrypoint, "_storage_bearer_headers", lambda: {"Authorization": "test"}
    )
    monkeypatch.setattr(entrypoint, "_ensure_azure_cli_auth", MagicMock())
    # Isolate transfer failures; lease protocol and guarded runs have their own tests.
    monkeypatch.setattr(
        entrypoint,
        "_remote_state_lock",
        lambda *_args: nullcontext(entrypoint._StateLock()),
    )


@pytest.mark.parametrize("variable", ["TF_STATE_STORAGE_ACCOUNT", "TF_STATE_CONTAINER"])
def test_partial_storage_configuration_is_not_local_mode(monkeypatch, variable) -> None:
    monkeypatch.delenv("TF_STATE_STORAGE_ACCOUNT", raising=False)
    monkeypatch.delenv("TF_STATE_CONTAINER", raising=False)
    monkeypatch.setenv(variable, "tfstate")
    with pytest.raises(entrypoint.TerraformRunError, match="Both"):
        entrypoint._blob_url("demo123.tfstate")


@pytest.mark.parametrize(
    "marker",
    [
        "CONTAINER_APP_JOB_NAME",
        "CONTAINER_APP_NAME",
        "IDENTITY_ENDPOINT",
    ],
)
def test_cloud_without_state_configuration_fails(monkeypatch, marker) -> None:
    monkeypatch.delenv("TF_STATE_STORAGE_ACCOUNT", raising=False)
    monkeypatch.delenv("TF_STATE_CONTAINER", raising=False)
    monkeypatch.setenv(marker, "present")
    with pytest.raises(
        entrypoint.TerraformRunError, match="requires configured remote state"
    ):
        entrypoint._blob_url("demo123.tfstate")


@pytest.mark.parametrize("status", [401, 403, 409, 429, 500, 503])
def test_download_failure_never_becomes_fresh_state(
    tmp_path, monkeypatch, remote, status
) -> None:
    monkeypatch.setattr(
        entrypoint.httpx, "get", lambda *_a, **_kw: httpx.Response(status)
    )
    with pytest.raises(entrypoint.TerraformRunError, match=f"HTTP {status}"):
        entrypoint._download_remote_state(tmp_path, "demo123")
    assert not (tmp_path / "terraform.tfstate").exists()


@pytest.mark.parametrize("operation", ["download", "upload"])
def test_network_failure_is_explicit(tmp_path, monkeypatch, remote, operation) -> None:
    (tmp_path / "terraform.tfstate").write_bytes(STATE)
    function = (
        entrypoint._download_remote_state
        if operation == "download"
        else entrypoint._upload_remote_state
    )
    monkeypatch.setattr(
        entrypoint.httpx,
        "get" if operation == "download" else "put",
        MagicMock(side_effect=httpx.ConnectError("do not expose endpoint details")),
    )
    with pytest.raises(entrypoint.TerraformRunError) as error:
        function(tmp_path, "demo123")
    assert "endpoint details" not in str(error.value)


def test_identity_denial_is_not_an_empty_state_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "azure.identity.DefaultAzureCredential",
        MagicMock(side_effect=ClientAuthenticationError("private identity details")),
    )
    with pytest.raises(
        entrypoint.TerraformRunError, match="authentication failed"
    ) as error:
        entrypoint._storage_bearer_headers()
    assert "private identity" not in str(error.value)


def test_only_missing_blob_permits_initial_apply(tmp_path, monkeypatch, remote) -> None:
    monkeypatch.setattr(
        entrypoint.httpx,
        "get",
        lambda *_a, **_kw: httpx.Response(
            404, headers={"x-ms-error-code": "BlobNotFound"}
        ),
    )
    entrypoint._download_remote_state(tmp_path, "demo123", allow_missing=True)
    assert not (tmp_path / "terraform.tfstate").exists()
    with pytest.raises(entrypoint.TerraformRunError, match="HTTP 404"):
        entrypoint._download_remote_state(tmp_path, "demo123", allow_missing=False)
    (tmp_path / "terraform.tfstate").write_bytes(STATE)
    with pytest.raises(entrypoint.TerraformRunError, match="refusing stale state"):
        entrypoint._download_remote_state(tmp_path, "demo123")


def test_missing_container_is_not_a_new_environment(
    tmp_path, monkeypatch, remote
) -> None:
    monkeypatch.setattr(
        entrypoint.httpx,
        "get",
        lambda *_a, **_kw: httpx.Response(
            404, headers={"x-ms-error-code": "ContainerNotFound"}
        ),
    )
    with pytest.raises(entrypoint.TerraformRunError, match="HTTP 404"):
        entrypoint._download_remote_state(tmp_path, "demo123")


def test_missing_shared_state_stops_before_terraform(
    tmp_path, monkeypatch, remote
) -> None:
    monkeypatch.setattr(
        entrypoint.httpx,
        "get",
        lambda *_a, **_kw: httpx.Response(
            404, headers={"x-ms-error-code": "BlobNotFound"}
        ),
    )
    command = MagicMock()
    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    with pytest.raises(entrypoint.TerraformRunError, match="HTTP 404"):
        entrypoint.run(
            workflow_id="wf",
            environment_id="demo123",
            action="apply",
            terraform_variables={},
            working_dir=tmp_path,
            callback=MagicMock(),
        )
    command.assert_not_called()


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not json",
        b"[]",
        b"{}",
        b'{"version":4,"resources":{}}',
    ],
)
def test_invalid_download_is_not_written(
    tmp_path, monkeypatch, remote, content
) -> None:
    monkeypatch.setattr(
        entrypoint.httpx,
        "get",
        lambda *_a, **_kw: httpx.Response(200, content=content),
    )
    with pytest.raises(entrypoint.TerraformRunError):
        entrypoint._download_remote_state(tmp_path, "demo123")
    assert not (tmp_path / "terraform.tfstate").exists()


@pytest.mark.parametrize("status", [400, 401, 403, 409, 412, 429, 500, 503])
def test_upload_error_is_not_success(tmp_path, monkeypatch, remote, status) -> None:
    (tmp_path / "terraform.tfstate").write_bytes(STATE)
    monkeypatch.setattr(
        entrypoint.httpx, "put", lambda *_a, **_kw: httpx.Response(status)
    )
    with pytest.raises(entrypoint.TerraformRunError, match=f"HTTP {status}"):
        entrypoint._upload_remote_state(tmp_path, "demo123")


@pytest.mark.parametrize("failure", ["nonzero", "timeout"])
def test_partial_state_is_persisted_after_failed_mutations(
    tmp_path, monkeypatch, remote, failure
) -> None:
    monkeypatch.setattr(
        entrypoint.httpx, "get", lambda *_a, **_kw: httpx.Response(200, content=STATE)
    )
    upload = MagicMock(return_value=httpx.Response(201))
    monkeypatch.setattr(entrypoint.httpx, "put", upload)

    def command(args, *, cwd):
        if args[0] == "init":
            return subprocess.CompletedProcess(args, 0)
        assert args[0] == "apply"
        state = json.loads(STATE)
        state["resources"] = [{"name": "partially-created-test-resource"}]
        (cwd / "terraform.tfstate").write_text(json.dumps(state))
        if failure == "timeout":
            raise subprocess.TimeoutExpired("terraform", 1)
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="failure")

    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    callback = MagicMock()
    error_type = (
        subprocess.TimeoutExpired
        if failure == "timeout"
        else entrypoint.TerraformRunError
    )
    with pytest.raises(error_type):
        entrypoint.run(
            workflow_id="wf",
            environment_id="demo123",
            action="apply",
            terraform_variables={},
            working_dir=tmp_path,
            callback=callback,
        )
    upload.assert_called_once()
    assert b"partially-created-test-resource" in upload.call_args.kwargs["content"]
    callback.complete_workflow.assert_not_called()


@pytest.mark.parametrize("output", ["failure", "invalid-json", "non-object"])
def test_output_failure_never_reports_completed(tmp_path, monkeypatch, output) -> None:
    monkeypatch.delenv("TF_STATE_STORAGE_ACCOUNT", raising=False)
    monkeypatch.delenv("TF_STATE_CONTAINER", raising=False)
    monkeypatch.setattr(entrypoint, "_ensure_azure_cli_auth", MagicMock())

    def command(args, *, cwd):
        if args[0] != "output":
            return subprocess.CompletedProcess(args, 0)
        return subprocess.CompletedProcess(
            args,
            1 if output == "failure" else 0,
            stdout="[]" if output == "non-object" else "not json",
            stderr="failed output",
        )

    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    callback = MagicMock()
    with pytest.raises(entrypoint.TerraformRunError, match="output"):
        entrypoint.run(
            workflow_id="wf",
            environment_id="demo123",
            action="apply",
            terraform_variables={},
            working_dir=tmp_path,
            callback=callback,
        )
    callback.complete_workflow.assert_not_called()


@pytest.mark.parametrize("environment", ["../other", "demo123?other", "", "A123"])
def test_invalid_state_owner_stops_before_auth(
    tmp_path, monkeypatch, environment
) -> None:
    auth = MagicMock()
    monkeypatch.setattr(entrypoint, "_ensure_azure_cli_auth", auth)
    with pytest.raises(entrypoint.CallbackClientError, match="environmentId"):
        entrypoint.run(
            workflow_id="wf",
            environment_id=environment,
            action="apply",
            terraform_variables={},
            working_dir=tmp_path,
            callback=MagicMock(),
        )
    auth.assert_not_called()


def test_terraform_variables_cannot_select_a_different_state_owner(
    tmp_path, monkeypatch
) -> None:
    auth = MagicMock()
    monkeypatch.setattr(entrypoint, "_ensure_azure_cli_auth", auth)
    with pytest.raises(entrypoint.CallbackClientError, match="state owner"):
        entrypoint.run(
            workflow_id="wf",
            environment_id="demo123",
            action="apply",
            terraform_variables={"environment_id": "other123"},
            working_dir=tmp_path,
            callback=MagicMock(),
        )
    auth.assert_not_called()


def test_persistence_failure_prevents_completed_callback(
    tmp_path, monkeypatch, remote
) -> None:
    monkeypatch.setattr(
        entrypoint.httpx,
        "get",
        lambda *_a, **_kw: httpx.Response(200, content=STATE),
    )
    monkeypatch.setattr(entrypoint.httpx, "put", lambda *_a, **_kw: httpx.Response(403))
    commands = []

    def command(args, *, cwd):
        commands.append(args[0])
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    callback = MagicMock()
    with pytest.raises(
        entrypoint.TerraformRunError, match="persistence returned HTTP 403"
    ):
        entrypoint.run(
            workflow_id="wf",
            environment_id="demo123",
            action="apply",
            terraform_variables={},
            working_dir=tmp_path,
            callback=callback,
        )
    assert commands == ["init", "apply"]
    assert (tmp_path / "terraform.tfstate").read_bytes() == STATE
    callback.complete_workflow.assert_not_called()


def test_destroy_without_persisted_state_stops_before_init(
    tmp_path, monkeypatch, remote
) -> None:
    def get(url, **_kwargs):
        if url.endswith("infra-shared.tfstate"):
            return httpx.Response(200, content=STATE)
        return httpx.Response(404, headers={"x-ms-error-code": "BlobNotFound"})

    monkeypatch.setattr(entrypoint.httpx, "get", get)
    command = MagicMock()
    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    callback = MagicMock()
    with pytest.raises(entrypoint.TerraformRunError, match="HTTP 404"):
        entrypoint.run(
            workflow_id="wf",
            environment_id="demo123",
            action="destroy",
            terraform_variables={},
            working_dir=tmp_path,
            callback=callback,
        )
    command.assert_not_called()
    callback.complete_workflow.assert_not_called()


def test_initial_apply_can_create_and_persist_its_first_state(
    tmp_path, monkeypatch, remote
) -> None:
    def get(url, **_kwargs):
        if url.endswith("infra-shared.tfstate"):
            return httpx.Response(200, content=STATE)
        return httpx.Response(404, headers={"x-ms-error-code": "BlobNotFound"})

    monkeypatch.setattr(entrypoint.httpx, "get", get)
    upload = MagicMock(return_value=httpx.Response(201))
    monkeypatch.setattr(entrypoint.httpx, "put", upload)

    def command(args, *, cwd):
        if args[0] == "apply":
            (cwd / "terraform.tfstate").write_bytes(STATE)
        return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    callback = MagicMock()
    entrypoint.run(
        workflow_id="wf",
        environment_id="demo123",
        action="apply",
        terraform_variables={},
        working_dir=tmp_path,
        callback=callback,
    )
    upload.assert_called_once()
    callback.complete_workflow.assert_called_once()


@pytest.mark.parametrize(
    "name,value",
    [
        ("TF_STATE_STORAGE_ACCOUNT", "wrong-host.example"),
        ("TF_STATE_STORAGE_ACCOUNT", "abc/other"),
        ("TF_STATE_CONTAINER", "tfstate?other"),
        ("TF_STATE_CONTAINER", "invalid--container"),
    ],
)
def test_storage_names_cannot_change_the_request_target(
    monkeypatch, remote, name, value
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(
        entrypoint.TerraformRunError, match="Invalid remote state storage"
    ):
        entrypoint._blob_url("demo123.tfstate")
