from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from unittest.mock import MagicMock

import httpx
import pytest

from conftest import load_worker_entrypoint

entrypoint = load_worker_entrypoint("terraform_runner")
STATE = b'{"version":4,"resources":[],"outputs":{}}'


def test_storage_authorization_includes_current_utc_request_date(monkeypatch):
    credential = MagicMock()
    credential.get_token.return_value.token = "test-token"
    monkeypatch.setattr(
        "azure.identity.DefaultAzureCredential", MagicMock(return_value=credential)
    )
    headers = entrypoint._storage_bearer_headers()
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["x-ms-version"] == "2023-11-03"
    elapsed = datetime.now(UTC) - parsedate_to_datetime(headers["x-ms-date"])
    assert 0 <= elapsed.total_seconds() < 5
    credential.get_token.assert_called_once_with("https://storage.azure.com/.default")


class Storage:
    def __init__(self) -> None:
        self.owner = None
        self.metadata = None
        self.actions = []
        self.uploaded = None
        self.upload_status = 201
        self.release_status = 200

    def get(self, url, **_kwargs):
        if "/locks/" not in url:
            assert self.owner is not None
            return httpx.Response(200, content=STATE)
        if self.metadata is None:
            return httpx.Response(404, headers={"x-ms-error-code": "BlobNotFound"})
        return httpx.Response(200, json=self.metadata)

    def put(self, url, *, headers, content, **_kwargs):
        action = headers.get("x-ms-lease-action")
        if action:
            self.actions.append(action)
            if action == "acquire":
                assert headers["x-ms-lease-duration"] == "-1"
                if self.owner:
                    return httpx.Response(
                        409, headers={"x-ms-error-code": "LeaseAlreadyPresent"}
                    )
                self.owner = headers["x-ms-proposed-lease-id"]
                return httpx.Response(201, headers={"x-ms-lease-id": self.owner})
            assert action == "release"
            assert headers["x-ms-lease-id"] == self.owner
            if self.release_status == 200:
                self.owner = None
            return httpx.Response(self.release_status)
        if "/locks/" in url:
            if headers.get("If-None-Match") == "*":
                assert self.metadata is None
            else:
                assert headers["x-ms-lease-id"] == self.owner
            self.metadata = json.loads(content)
        else:
            assert self.owner is not None
            self.uploaded = content
        return httpx.Response(self.upload_status if "/locks/" not in url else 201)


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setenv("TF_STATE_STORAGE_ACCOUNT", "teststate")
    monkeypatch.setenv("TF_STATE_CONTAINER", "tfstate")
    monkeypatch.setattr(
        entrypoint, "_storage_bearer_headers", lambda: {"Authorization": "test"}
    )
    monkeypatch.setattr(entrypoint, "_ensure_azure_cli_auth", MagicMock())
    store = Storage()
    monkeypatch.setattr(entrypoint.httpx, "get", store.get)
    monkeypatch.setattr(entrypoint.httpx, "put", store.put)
    return store


def invoke(tmp_path, callback=None, workflow_id="wf-1"):
    entrypoint.run(
        workflow_id=workflow_id,
        environment_id="demo123",
        action="apply",
        terraform_variables={"environment_id": "demo123"},
        working_dir=tmp_path,
        callback=callback or MagicMock(),
    )


def test_competing_worker_cannot_download_or_mutate(tmp_path, monkeypatch, storage):
    command = MagicMock()
    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    with entrypoint._remote_state_lock("demo123", "wf-first"):
        original_owner = storage.owner
        with pytest.raises(entrypoint.TerraformRunError, match="acquisition"):
            invoke(tmp_path, workflow_id="wf-second")
        assert storage.owner == original_owner
        assert storage.metadata["workflowId"] == "wf-first"
        command.assert_not_called()
    assert storage.owner is None
    assert storage.actions == ["acquire", "acquire", "release"]
    with entrypoint._remote_state_lock("demo123", "wf-second"):
        assert storage.metadata["workflowId"] == "wf-second"


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "upload", "output"])
def test_failed_mutation_keeps_lock_and_persists_partial_state(
    tmp_path, monkeypatch, storage, failure, caplog
):
    def command(args, *, cwd):
        if args[0] == "init":
            return subprocess.CompletedProcess(args, 0)
        if args[0] == "output":
            return subprocess.CompletedProcess(
                args, 1, stdout="", stderr="invalid outputs"
            )
        state = json.loads(STATE)
        state["resources"] = [{"name": "partially-created-test-resource"}]
        (cwd / "terraform.tfstate").write_text(json.dumps(state))
        if failure == "timeout":
            raise subprocess.TimeoutExpired("terraform", 1)
        if failure == "upload":
            storage.upload_status = 503
        return subprocess.CompletedProcess(
            args, 1 if failure == "nonzero" else 0, stdout="", stderr="failure"
        )

    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    callback = MagicMock()
    expected = (
        subprocess.TimeoutExpired
        if failure == "timeout"
        else entrypoint.TerraformRunError
    )
    with pytest.raises(expected):
        invoke(tmp_path, callback)
    assert storage.owner is not None
    assert b"partially-created-test-resource" in storage.uploaded
    assert storage.actions == ["acquire"]
    assert "lock retained" in caplog.text
    callback.complete_workflow.assert_not_called()
    command = MagicMock()
    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    with pytest.raises(entrypoint.TerraformRunError, match="acquisition"):
        invoke(tmp_path, workflow_id="wf-retry")
    command.assert_not_called()


@pytest.mark.parametrize("release_status", [200, 403, 500])
def test_success_requires_persistence_and_owned_release(
    tmp_path, monkeypatch, storage, release_status
):
    storage.release_status = release_status

    def command(args, *, cwd):
        assert storage.owner is not None
        if args[0] == "apply":
            (cwd / "terraform.tfstate").write_bytes(STATE)
        return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    callback = MagicMock()
    if release_status == 200:
        invoke(tmp_path, callback)
        assert storage.owner is None
        callback.complete_workflow.assert_called_once()
    else:
        with pytest.raises(entrypoint.TerraformRunError, match="release"):
            invoke(tmp_path, callback)
        assert storage.owner is not None
        callback.complete_workflow.assert_not_called()
    assert storage.uploaded == STATE
    assert storage.actions == ["acquire", "release"]


def test_init_failure_releases_without_mutation(tmp_path, monkeypatch, storage):
    command = MagicMock(
        return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="init")
    )
    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    with pytest.raises(entrypoint.TerraformRunError, match="init"):
        invoke(tmp_path)
    assert storage.owner is None
    assert storage.uploaded is None
    assert storage.actions == ["acquire", "release"]
    command.assert_called_once()


@pytest.mark.parametrize("status", [401, 403, 404, 409, 429, 500])
def test_lock_read_error_is_not_missing_state(tmp_path, monkeypatch, storage, status):
    monkeypatch.setattr(
        entrypoint.httpx, "get", lambda *_a, **_kw: httpx.Response(status)
    )
    command = MagicMock()
    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    with pytest.raises(entrypoint.TerraformRunError, match=f"HTTP {status}"):
        invoke(tmp_path)
    assert storage.actions == []
    command.assert_not_called()


@pytest.mark.parametrize(
    "owner", [[], {}, {"environmentId": "other", "workflowId": "wf"}]
)
def test_unrecognized_lock_owner_is_not_adopted(tmp_path, monkeypatch, storage, owner):
    storage.metadata = owner
    command = MagicMock()
    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    with pytest.raises(entrypoint.TerraformRunError, match="ownership"):
        invoke(tmp_path)
    assert storage.actions == []
    command.assert_not_called()


def test_request_error_does_not_expose_endpoint_or_token(
    tmp_path, monkeypatch, storage
):
    monkeypatch.setattr(
        entrypoint.httpx,
        "put",
        MagicMock(side_effect=httpx.ConnectError("private endpoint and token")),
    )
    with pytest.raises(entrypoint.TerraformRunError) as error:
        invoke(tmp_path)
    assert "private endpoint" not in str(error.value)
    assert "token" not in str(error.value)
    assert storage.owner is None


def test_local_execution_never_contacts_storage(monkeypatch):
    monkeypatch.delenv("TF_STATE_STORAGE_ACCOUNT", raising=False)
    monkeypatch.delenv("TF_STATE_CONTAINER", raising=False)
    for marker in ("CONTAINER_APP_JOB_NAME", "CONTAINER_APP_NAME", "IDENTITY_ENDPOINT"):
        monkeypatch.delenv(marker, raising=False)
    request = MagicMock()
    monkeypatch.setattr(entrypoint.httpx, "get", request)
    monkeypatch.setattr(entrypoint.httpx, "put", request)
    with entrypoint._remote_state_lock("demo123", "wf") as marker:
        marker.mutation_started = True
    request.assert_not_called()
