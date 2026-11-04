"""Unit tests for orchestrators/generic_orchestrator.py, hand-driving the
Durable Functions generator with a fake context via `send()`/`throw()` since
no Azurite/Functions Core Tools host is available in this environment to
integration-test the real generator against a live task hub.

`context.task_any([...])`'s real Durable Functions semantics (verified
against the installed azure-functions-durable SDK - see
DurableOrchestrationContext.task_any's docstring/source) is: it returns the
*winning Task instance itself* when the generator's `yield` is resolved, not
its `.result`. A plain `call_activity`/`create_timer` yield instead resolves
directly to that activity/timer's own result. FakeContext below mirrors this:
`task_any` returns a marker `FakeTask` whose `.input` holds the raced
candidate tasks, and each test manually picks a "winner" and sends it back
via `gen.send(winner)`, exactly like the real DF extension would after a
task actually completes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from orchestration_lib.orchestration_logic import ORCHESTRATION_TIMEOUT_SECONDS
from orchestrators.generic_orchestrator import generic_orchestrator


class FakeTask:
    def __init__(self, kind: str, *, name: str | None = None, input: Any = None) -> None:
        self.kind = kind
        self.name = name
        self.input = input
        self.result: Any = None
        self.is_completed = False
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeContext:
    def __init__(self, raw_input: dict[str, Any]) -> None:
        self._raw_input = raw_input
        self.custom_status: Any = None
        self.current_utc_datetime = datetime(2024, 1, 1, 0, 0, 0)

    def get_input(self) -> dict[str, Any]:
        return self._raw_input

    def set_custom_status(self, status: Any) -> None:
        self.custom_status = status

    def call_activity(self, name: str, input_: Any = None) -> FakeTask:
        return FakeTask("activity", name=name, input=input_)

    def create_timer(self, _fire_at: datetime) -> FakeTask:
        return FakeTask("timer")

    def wait_for_external_event(self, event_name: str) -> FakeTask:
        return FakeTask("external_event", name=event_name)

    def task_any(self, tasks: list[FakeTask]) -> FakeTask:
        return FakeTask("task_any", input=tasks)


_PROVISION_INPUT = {
    "workflowId": "wf-1",
    "workflowType": "provision",
    "jobName": "job-terraform-runner",
    "jobInput": {"action": "apply"},
}


def test_dispatches_job_then_polls_until_succeeded() -> None:
    context = FakeContext(_PROVISION_INPUT)
    gen = generic_orchestrator(context)

    dispatch_task = gen.send(None)
    assert dispatch_task.kind == "activity"
    assert dispatch_task.name == "dispatch_job"
    assert dispatch_task.input["jobName"] == "job-terraform-runner"

    task_any_call = gen.send({"executionName": "exec-1"})
    assert task_any_call.kind == "task_any"
    cancel_task, timer_task, status_task = task_any_call.input
    assert cancel_task.kind == "external_event" and cancel_task.name == "cancel"
    assert timer_task.kind == "timer"
    assert status_task.kind == "activity" and status_task.name == "poll_job_status"
    assert status_task.input == {"jobName": "job-terraform-runner", "executionName": "exec-1"}

    # Not yet terminal: orchestrator loops, creating a fresh timer/status pair
    # but reusing the SAME cancel_task (only ever waited for once).
    status_task.result = "Running"
    next_task_any_call = gen.send(status_task)
    assert next_task_any_call.kind == "task_any"
    cancel_task_2, _timer_task_2, status_task_2 = next_task_any_call.input
    assert cancel_task_2 is cancel_task

    status_task_2.result = "Succeeded"
    with pytest.raises(StopIteration) as exc_info:
        gen.send(status_task_2)
    assert exc_info.value.value == {"status": "completed"}


def test_failed_terminal_status_maps_to_failed_outcome() -> None:
    context = FakeContext(_PROVISION_INPUT)
    gen = generic_orchestrator(context)
    gen.send(None)
    task_any_call = gen.send({"executionName": "exec-1"})
    _cancel_task, _timer_task, status_task = task_any_call.input

    status_task.result = "Failed"
    with pytest.raises(StopIteration) as exc_info:
        gen.send(status_task)
    assert exc_info.value.value == {"status": "failed"}


def test_cancel_event_stops_job_and_acknowledges() -> None:
    context = FakeContext(_PROVISION_INPUT)
    gen = generic_orchestrator(context)
    gen.send(None)
    task_any_call = gen.send({"executionName": "exec-1"})
    cancel_task, timer_task, _status_task = task_any_call.input

    stop_job_task = gen.send(cancel_task)
    assert timer_task.cancelled is True
    assert stop_job_task.kind == "activity"
    assert stop_job_task.name == "stop_job"
    assert stop_job_task.input == {
        "jobName": "job-terraform-runner",
        "executionName": "exec-1",
        "workflowId": "wf-1",
    }

    ack_task = gen.send(None)
    assert ack_task.kind == "activity"
    assert ack_task.name == "acknowledge_cancellation"
    assert ack_task.input == {"workflowId": "wf-1"}

    with pytest.raises(StopIteration) as exc_info:
        gen.send(None)
    assert exc_info.value.value == {"status": "cancelled"}


def test_orchestration_timeout_reports_terminal_failure() -> None:
    context = FakeContext(_PROVISION_INPUT)
    gen = generic_orchestrator(context)
    gen.send(None)
    task_any_call = gen.send({"executionName": "exec-1"})
    _cancel_task, _timer_task, status_task = task_any_call.input

    status_task.result = "Running"
    # Advance the clock past the orchestration timeout before the next loop
    # iteration's deadline check runs.
    context.current_utc_datetime += timedelta(seconds=ORCHESTRATION_TIMEOUT_SECONDS + 1)

    report_failure_task = gen.send(status_task)
    assert report_failure_task.kind == "activity"
    assert report_failure_task.name == "report_terminal_failure"
    assert report_failure_task.input == {"workflowId": "wf-1", "reason": "orchestration_timeout"}

    with pytest.raises(StopIteration) as exc_info:
        gen.send(None)
    assert exc_info.value.value == {"status": "failed", "reason": "orchestration_timeout"}


def test_pre_dispatched_execution_skips_dispatch_activity() -> None:
    """The `deploy` workflow type: FastAPI already started the job execution
    itself (with the real HF credential, never touching Durable Functions
    history - see orchestration_lib/orchestration_logic.py's
    `OrchestrationInput` docstring) - this orchestrator only monitors it."""
    context = FakeContext(
        {
            "workflowId": "wf-2",
            "workflowType": "deploy",
            "jobName": "job-model-deployment",
            "preDispatchedExecutionName": "exec-pre-1",
        }
    )
    gen = generic_orchestrator(context)

    task_any_call = gen.send(None)
    assert task_any_call.kind == "task_any"
    _cancel_task, _timer_task, status_task = task_any_call.input
    assert status_task.input == {"jobName": "job-model-deployment", "executionName": "exec-pre-1"}

    status_task.result = "Succeeded"
    with pytest.raises(StopIteration) as exc_info:
        gen.send(status_task)
    assert exc_info.value.value == {"status": "completed"}
