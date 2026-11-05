from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import httpx
import pytest
from activities.activities import finalize_workflow
from orchestration_lib.callback_client import CallbackClientError, WorkflowAlreadyTerminal
from orchestration_lib.orchestration_logic import ORCHESTRATION_TIMEOUT_SECONDS
from orchestrators.generic_orchestrator import generic_orchestrator_v2
from test_callback_client import _client_with_transport
from test_generic_orchestrator import _PROVISION_INPUT, FakeContext


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_callback_parses_only_authoritative_terminal_conflict(status) -> None:
    client = _client_with_transport(
        lambda _request: httpx.Response(
            409,
            json={
                "error": {
                    "code": "workflow_not_running",
                    "details": {"workflowId": "wf-1", "status": status},
                }
            },
        )
    )
    with pytest.raises(WorkflowAlreadyTerminal) as exc:
        client.complete_workflow("wf-1", status="failed")
    assert exc.value.workflow_id == "wf-1"
    assert exc.value.status == status


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"error": []},
        {"error": {"code": "environment_locked", "details": {"status": "completed"}}},
        {"error": {"code": "workflow_not_running", "details": {}}},
        {
            "error": {
                "code": "workflow_not_running",
                "details": {"workflowId": "wf-1", "status": "running"},
            }
        },
        {
            "error": {
                "code": "workflow_not_running",
                "details": {"workflowId": "wf-1", "status": []},
            }
        },
    ],
)
def test_other_conflicts_are_not_treated_as_completion(payload) -> None:
    client = _client_with_transport(lambda _request: httpx.Response(409, json=payload))
    with pytest.raises(CallbackClientError) as exc:
        client.complete_workflow("wf-1", status="failed")
    assert not isinstance(exc.value, WorkflowAlreadyTerminal)


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_finalization_reports_owned_failure_or_cancellation(monkeypatch, status) -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    client.complete_workflow.return_value = {"workflowId": "wf-1", "status": status}
    monkeypatch.setattr("activities.activities.WorkflowCallbackClient", lambda: client)

    assert finalize_workflow(
        {"workflowId": "wf-1", "status": status, "reason": "test", "jobStatus": "Failed"}
    ) == {"status": status}
    client.complete_workflow.assert_called_once_with(
        "wf-1", status=status, diagnostics={"reason": "test", "jobStatus": "Failed"}
    )


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_finalization_preserves_worker_outcome_on_duplicate(monkeypatch, status, caplog) -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    client.complete_workflow.side_effect = WorkflowAlreadyTerminal("wf-1", status)
    monkeypatch.setattr("activities.activities.WorkflowCallbackClient", lambda: client)

    assert finalize_workflow(
        {"workflowId": "wf-1", "status": "failed", "reason": "job_terminal_without_callback"}
    ) == {"status": status}
    assert "Finalized workflow" not in caplog.text


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 500])
def test_finalization_does_not_ignore_other_callback_failures(monkeypatch, status_code) -> None:
    client = _client_with_transport(
        lambda _request: httpx.Response(
            status_code, json={"error": {"code": "environment_locked", "details": {}}}
        )
    )
    monkeypatch.setattr("activities.activities.WorkflowCallbackClient", lambda: client)
    with pytest.raises(CallbackClientError):
        finalize_workflow(
            {"workflowId": "wf-1", "status": "failed", "reason": "job_terminal_without_callback"}
        )


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"workflowId": "wrong", "status": "failed"},
        {"workflowId": "wf-1", "status": "completed"},
    ],
)
def test_finalization_rejects_mismatched_success_response(monkeypatch, result) -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    client.complete_workflow.return_value = result
    monkeypatch.setattr("activities.activities.WorkflowCallbackClient", lambda: client)
    with pytest.raises(CallbackClientError):
        finalize_workflow({"workflowId": "wf-1", "status": "failed", "reason": "test"})


def test_finalization_does_not_infer_completed_from_job_exit() -> None:
    with pytest.raises(ValueError):
        finalize_workflow({"workflowId": "wf-1", "status": "completed", "reason": "test"})


@pytest.mark.parametrize("job_status", ["Succeeded", "Failed", "Stopped", "Degraded"])
@pytest.mark.parametrize("workflow_status", ["completed", "failed", "cancelled"])
def test_v2_terminal_job_always_resolves_authoritative_callback(
    job_status, workflow_status
) -> None:
    context = FakeContext(_PROVISION_INPUT)
    gen = generic_orchestrator_v2(context)
    assert gen.send(None).name == "dispatch_job"
    race = gen.send({"executionName": "exec-1"})
    _cancel, timer, status = race.input
    status.result = job_status

    finalize = gen.send(status)

    assert timer.cancelled
    assert finalize.name == "finalize_workflow"
    assert finalize.input == {
        "workflowId": "wf-1",
        "status": "failed",
        "reason": "job_terminal_without_callback",
        "jobStatus": job_status,
    }
    with pytest.raises(StopIteration) as done:
        gen.send({"status": workflow_status})
    assert done.value.value == {"status": workflow_status}


@pytest.mark.parametrize("workflow_status", ["completed", "failed", "cancelled"])
def test_v2_cancellation_stops_before_finalize_and_ack(workflow_status) -> None:
    gen = generic_orchestrator_v2(FakeContext(_PROVISION_INPUT))
    gen.send(None)
    race = gen.send({"executionName": "exec-1"})
    cancel, timer, _status = race.input
    stop = gen.send(cancel)
    assert stop.name == "stop_job"
    assert timer.cancelled
    finalize = gen.send(None)
    assert finalize.name == "finalize_workflow"
    assert finalize.input["status"] == "cancelled"
    ack = gen.send({"status": workflow_status})
    assert ack.name == "acknowledge_cancellation"
    with pytest.raises(StopIteration) as done:
        gen.send(None)
    assert done.value.value == {"status": workflow_status}


@pytest.mark.parametrize("workflow_status", ["completed", "failed", "cancelled"])
def test_v2_timeout_stops_before_finalization(workflow_status) -> None:
    context = FakeContext(_PROVISION_INPUT)
    gen = generic_orchestrator_v2(context)
    gen.send(None)
    race = gen.send({"executionName": "exec-1"})
    _cancel, _timer, status = race.input
    status.result = "Running"
    context.current_utc_datetime += timedelta(seconds=ORCHESTRATION_TIMEOUT_SECONDS + 1)

    stop = gen.send(status)
    assert stop.name == "stop_job"
    finalize = gen.send(None)
    assert finalize.name == "finalize_workflow"
    assert finalize.input["reason"] == "orchestration_timeout"
    with pytest.raises(StopIteration) as done:
        gen.send({"status": workflow_status})
    assert done.value.value == {"status": workflow_status, "reason": "orchestration_timeout"}


@pytest.mark.parametrize("timeout", [False, True])
def test_v2_stop_failure_does_not_finalize_or_ack(timeout) -> None:
    context = FakeContext(_PROVISION_INPUT)
    gen = generic_orchestrator_v2(context)
    gen.send(None)
    race = gen.send({"executionName": "exec-1"})
    cancel, _timer, status = race.input
    status.result = "Running"
    if timeout:
        context.current_utc_datetime += timedelta(seconds=ORCHESTRATION_TIMEOUT_SECONDS + 1)
    assert gen.send(status if timeout else cancel).name == "stop_job"
    with pytest.raises(RuntimeError, match="stop failed"):
        gen.throw(RuntimeError("stop failed"))
