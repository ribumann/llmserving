from __future__ import annotations

import pytest
from orchestration_lib.workflow_jobs import (
    UnknownWorkflowTypeError,
    job_env_var_for_workflow_type,
    resolve_job_name,
)


@pytest.mark.parametrize(
    ("workflow_type", "env_var"),
    [
        ("provision", "JOB_NAME_TERRAFORM_RUNNER"),
        ("teardown", "JOB_NAME_TERRAFORM_RUNNER"),
        ("deploy", "JOB_NAME_MODEL_DEPLOYMENT"),
        ("evaluate-golden", "JOB_NAME_EVALUATION_WORKER"),
        ("evaluate-benchmark", "JOB_NAME_EVALUATION_WORKER"),
        ("performance-test", "JOB_NAME_PERFORMANCE_WORKER"),
        ("export", "JOB_NAME_EXPORT_WORKER"),
    ],
)
def test_job_env_var_for_workflow_type(workflow_type: str, env_var: str) -> None:
    assert job_env_var_for_workflow_type(workflow_type) == env_var


def test_job_env_var_for_unknown_workflow_type_raises() -> None:
    with pytest.raises(UnknownWorkflowTypeError):
        job_env_var_for_workflow_type("not-a-real-type")


def test_resolve_job_name_reads_configured_env_var() -> None:
    env = {"JOB_NAME_MODEL_DEPLOYMENT": "job-model-deployment-abc"}
    assert resolve_job_name("deploy", env=env) == "job-model-deployment-abc"


def test_resolve_job_name_raises_when_env_var_unset() -> None:
    with pytest.raises(UnknownWorkflowTypeError, match="JOB_NAME_TERRAFORM_RUNNER"):
        resolve_job_name("provision", env={})
