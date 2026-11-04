from __future__ import annotations

import json

import pytest
from orchestration_lib.orchestration_logic import (
    OrchestrationInput,
    build_dispatch_job_input,
    is_terminal_job_status,
    job_status_to_workflow_outcome,
)


def test_from_raw_requires_workflow_id_type_and_job_name() -> None:
    with pytest.raises(ValueError):
        OrchestrationInput.from_raw({"workflowType": "provision", "jobName": "job-1"})
    with pytest.raises(ValueError):
        OrchestrationInput.from_raw({"workflowId": "wf-1", "jobName": "job-1"})
    with pytest.raises(ValueError):
        OrchestrationInput.from_raw({"workflowId": "wf-1", "workflowType": "provision"})
    with pytest.raises(ValueError):
        OrchestrationInput.from_raw(None)


def test_from_raw_parses_a_normal_dispatch_request() -> None:
    raw = {
        "workflowId": "wf-1",
        "workflowType": "provision",
        "jobName": "job-terraform-runner",
        "jobInput": {"action": "apply"},
    }
    parsed = OrchestrationInput.from_raw(raw)

    assert parsed.workflow_id == "wf-1"
    assert parsed.workflow_type == "provision"
    assert parsed.job_name == "job-terraform-runner"
    assert parsed.job_input == {"action": "apply"}
    assert parsed.pre_dispatched_execution_name is None


def test_from_raw_parses_a_pre_dispatched_deploy_request() -> None:
    """The `deploy` workflow type never carries a real `jobInput` through
    Durable Functions - FastAPI dispatches the credential-bearing job itself
    and only hands this orchestrator the resulting execution name to watch
    (research.md's Secret handling decision; provider-interface.md)."""
    raw = {
        "workflowId": "wf-2",
        "workflowType": "deploy",
        "jobName": "job-model-deployment",
        "preDispatchedExecutionName": "job-model-deployment-abc123",
    }
    parsed = OrchestrationInput.from_raw(raw)

    assert parsed.job_input == {}
    assert parsed.pre_dispatched_execution_name == "job-model-deployment-abc123"


def test_build_dispatch_job_input_encodes_workflow_id_and_job_input() -> None:
    orchestration_input = OrchestrationInput.from_raw(
        {
            "workflowId": "wf-1",
            "workflowType": "provision",
            "jobName": "job-terraform-runner",
            "jobInput": {"action": "apply"},
        }
    )

    dispatch_input = build_dispatch_job_input(orchestration_input)

    assert dispatch_input["jobName"] == "job-terraform-runner"
    assert dispatch_input["envOverrides"]["WORKFLOW_ID"] == "wf-1"
    assert json.loads(dispatch_input["envOverrides"]["JOB_INPUT_JSON"]) == {"action": "apply"}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Succeeded", True),
        ("Failed", True),
        ("Stopped", True),
        ("Degraded", True),
        ("Running", False),
        ("Processing", False),
        ("Unknown", False),
        ("NotFound", False),
    ],
)
def test_is_terminal_job_status(status: str, expected: bool) -> None:
    assert is_terminal_job_status(status) is expected


def test_job_status_to_workflow_outcome_succeeded_maps_to_completed() -> None:
    assert job_status_to_workflow_outcome("Succeeded") == "completed"


@pytest.mark.parametrize("status", ["Failed", "Stopped", "Degraded"])
def test_job_status_to_workflow_outcome_other_terminal_statuses_map_to_failed(
    status: str,
) -> None:
    assert job_status_to_workflow_outcome(status) == "failed"
