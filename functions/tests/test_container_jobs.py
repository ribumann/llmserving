from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from orchestration_lib.container_jobs import (
    JobDispatchResult,
    dispatch_job,
    get_job_execution_status,
    is_terminal_status,
    stop_job_execution,
)


class _FakeEnvVar:
    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value


def _fake_container(env: list[_FakeEnvVar]) -> SimpleNamespace:
    return SimpleNamespace(
        name="main",
        image="acr.example/model-deployment:latest",
        command=["python"],
        args=["entrypoint.py"],
        env=env,
        resources=SimpleNamespace(cpu=2.0, memory="4Gi"),
    )


class _FakeJobsOperations:
    def __init__(self, container: SimpleNamespace) -> None:
        self._container = container
        self.start_calls: list[dict[str, Any]] = []
        self.stop_calls: list[dict[str, Any]] = []

    def get(self, resource_group: str, job_name: str) -> SimpleNamespace:
        return SimpleNamespace(template=SimpleNamespace(containers=[self._container]))

    def begin_start(self, resource_group: str, job_name: str, *, template: Any) -> Any:
        self.start_calls.append(
            {"resource_group": resource_group, "job_name": job_name, "template": template}
        )
        return SimpleNamespace(result=lambda: SimpleNamespace(name="exec-new-1"))

    def begin_stop_execution(
        self, resource_group: str, job_name: str, job_execution_name: str
    ) -> Any:
        self.stop_calls.append(
            {
                "resource_group": resource_group,
                "job_name": job_name,
                "job_execution_name": job_execution_name,
            }
        )
        return SimpleNamespace(result=lambda: None)


class _FakeJobsExecutionsOperations:
    def __init__(self, executions: list[SimpleNamespace]) -> None:
        self._executions = executions

    def list(self, resource_group: str, job_name: str, *, filter: str | None = None) -> Any:
        return list(self._executions)


class _FakeClient:
    def __init__(
        self, container: SimpleNamespace, executions: list[SimpleNamespace] | None = None
    ) -> None:
        self.jobs = _FakeJobsOperations(container)
        self.jobs_executions = _FakeJobsExecutionsOperations(executions or [])


def test_dispatch_job_preserves_existing_env_and_adds_overrides() -> None:
    container = _fake_container(
        env=[
            _FakeEnvVar("BACKEND_INTERNAL_CALLBACK_URL", "https://backend.example/internal"),
            _FakeEnvVar("TF_STATE_STORAGE_ACCOUNT", "tfstateacct"),
        ]
    )
    client = _FakeClient(container)

    result = dispatch_job(
        "rg-demo",
        "job-terraform-runner",
        {"WORKFLOW_ID": "wf-1", "JOB_INPUT_JSON": '{"action": "apply"}'},
        client=client,
    )

    assert result == JobDispatchResult(execution_name="exec-new-1")
    assert len(client.jobs.start_calls) == 1
    sent_env = {
        e["name"]: e["value"]
        for e in client.jobs.start_calls[0]["template"]["containers"][0]["env"]
    }
    assert sent_env["BACKEND_INTERNAL_CALLBACK_URL"] == "https://backend.example/internal"
    assert sent_env["TF_STATE_STORAGE_ACCOUNT"] == "tfstateacct"
    assert sent_env["WORKFLOW_ID"] == "wf-1"
    assert sent_env["JOB_INPUT_JSON"] == '{"action": "apply"}'


def test_dispatch_job_overrides_take_precedence_over_existing_env() -> None:
    container = _fake_container(env=[_FakeEnvVar("WORKFLOW_ID", "stale-value")])
    client = _FakeClient(container)

    dispatch_job("rg-demo", "job-x", {"WORKFLOW_ID": "wf-fresh"}, client=client)

    sent_env = {
        e["name"]: e["value"]
        for e in client.jobs.start_calls[0]["template"]["containers"][0]["env"]
    }
    assert sent_env["WORKFLOW_ID"] == "wf-fresh"


def test_get_job_execution_status_finds_matching_execution() -> None:
    executions = [
        SimpleNamespace(name="exec-1", status="Succeeded"),
        SimpleNamespace(name="exec-2", status="Running"),
    ]
    client = _FakeClient(_fake_container(env=[]), executions)

    assert get_job_execution_status("rg-demo", "job-x", "exec-2", client=client) == "Running"


def test_get_job_execution_status_returns_not_found_when_missing() -> None:
    client = _FakeClient(_fake_container(env=[]), [])

    assert get_job_execution_status("rg-demo", "job-x", "exec-missing", client=client) == "NotFound"


def test_is_terminal_status() -> None:
    assert is_terminal_status("Succeeded") is True
    assert is_terminal_status("Failed") is True
    assert is_terminal_status("Running") is False


def test_stop_job_execution_calls_begin_stop_execution() -> None:
    client = _FakeClient(_fake_container(env=[]))

    stop_job_execution("rg-demo", "job-x", "exec-1", client=client)

    assert client.jobs.stop_calls == [
        {"resource_group": "rg-demo", "job_name": "job-x", "job_execution_name": "exec-1"}
    ]
