from __future__ import annotations

from typing import Any

import pytest
from activities.activities import (
    acknowledge_cancellation,
    dispatch_job,
    poll_job_status,
    report_terminal_failure,
    stop_job,
)
from orchestration_lib.container_jobs import JobDispatchResult


@pytest.fixture(autouse=True)
def _resource_group_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTAINER_APPS_RESOURCE_GROUP", "rg-demo")


def test_dispatch_job_calls_container_jobs_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_dispatch(resource_group: str, job_name: str, env_overrides: dict[str, str]) -> Any:
        captured["resource_group"] = resource_group
        captured["job_name"] = job_name
        captured["env_overrides"] = env_overrides
        return JobDispatchResult(execution_name="exec-1")

    monkeypatch.setattr("activities.activities._dispatch_job", fake_dispatch)

    result = dispatch_job(
        {
            "jobName": "job-terraform-runner",
            "envOverrides": {"WORKFLOW_ID": "wf-1", "JOB_INPUT_JSON": "{}"},
        }
    )

    assert result == {"executionName": "exec-1"}
    assert captured["resource_group"] == "rg-demo"
    assert captured["job_name"] == "job-terraform-runner"
    assert captured["env_overrides"] == {"WORKFLOW_ID": "wf-1", "JOB_INPUT_JSON": "{}"}


def test_poll_job_status_calls_get_job_execution_status(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_status(resource_group: str, job_name: str, execution_name: str) -> str:
        captured["args"] = (resource_group, job_name, execution_name)
        return "Running"

    monkeypatch.setattr("activities.activities.get_job_execution_status", fake_status)

    status = poll_job_status({"jobName": "job-x", "executionName": "exec-1"})

    assert status == "Running"
    assert captured["args"] == ("rg-demo", "job-x", "exec-1")


def test_stop_job_calls_stop_job_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_stop(resource_group: str, job_name: str, execution_name: str) -> None:
        captured["args"] = (resource_group, job_name, execution_name)

    monkeypatch.setattr("activities.activities.stop_job_execution", fake_stop)

    stop_job({"jobName": "job-x", "executionName": "exec-1"})

    assert captured["args"] == ("rg-demo", "job-x", "exec-1")


class _FakeCallbackClient:
    def __init__(self) -> None:
        self.acknowledged: list[str] = []
        self.completed: list[dict[str, Any]] = []

    def __enter__(self) -> _FakeCallbackClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None

    def acknowledge_cancellation(self, workflow_id: str) -> None:
        self.acknowledged.append(workflow_id)

    def complete_workflow(
        self, workflow_id: str, *, status: str, diagnostics: dict[str, Any]
    ) -> None:
        self.completed.append(
            {"workflowId": workflow_id, "status": status, "diagnostics": diagnostics}
        )


def test_acknowledge_cancellation_calls_callback_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeCallbackClient()
    monkeypatch.setattr("activities.activities.WorkflowCallbackClient", lambda: fake_client)

    acknowledge_cancellation({"workflowId": "wf-1"})

    assert fake_client.acknowledged == ["wf-1"]


def test_report_terminal_failure_calls_callback_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeCallbackClient()
    monkeypatch.setattr("activities.activities.WorkflowCallbackClient", lambda: fake_client)

    report_terminal_failure({"workflowId": "wf-1", "reason": "orchestration_timeout"})

    assert fake_client.completed == [
        {
            "workflowId": "wf-1",
            "status": "failed",
            "diagnostics": {"reason": "orchestration_timeout"},
        }
    ]
