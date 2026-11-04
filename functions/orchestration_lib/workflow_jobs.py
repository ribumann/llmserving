"""Maps an Orchestration Workflow's `workflowType` (data-model.md) to the
Container Apps Job env var name that holds that job's resource name
(set on the Functions app in infra/control/main.tf's `app_settings` block:
JOB_NAME_TERRAFORM_RUNNER/JOB_NAME_MODEL_DEPLOYMENT/JOB_NAME_EVALUATION_WORKER/
JOB_NAME_PERFORMANCE_WORKER/JOB_NAME_EXPORT_WORKER).
"""

from __future__ import annotations

import os

# data-model.md's Orchestration Workflow `workflowType` enum: provision |
# deploy | evaluate-golden | evaluate-benchmark | performance-test | export |
# teardown - confirms the 5 job workers map 1:1 onto these 7 workflow types
# (provision/teardown share terraform_runner; evaluate-golden/
# evaluate-benchmark share evaluation_worker).
_JOB_ENV_VAR_BY_WORKFLOW_TYPE = {
    "provision": "JOB_NAME_TERRAFORM_RUNNER",
    "teardown": "JOB_NAME_TERRAFORM_RUNNER",
    "deploy": "JOB_NAME_MODEL_DEPLOYMENT",
    "evaluate-golden": "JOB_NAME_EVALUATION_WORKER",
    "evaluate-benchmark": "JOB_NAME_EVALUATION_WORKER",
    "performance-test": "JOB_NAME_PERFORMANCE_WORKER",
    "export": "JOB_NAME_EXPORT_WORKER",
}


class UnknownWorkflowTypeError(ValueError):
    """Raised for a `workflowType` outside data-model.md's enum, or one whose
    corresponding job-name env var isn't configured on this Functions app."""


def job_env_var_for_workflow_type(workflow_type: str) -> str:
    try:
        return _JOB_ENV_VAR_BY_WORKFLOW_TYPE[workflow_type]
    except KeyError:
        raise UnknownWorkflowTypeError(f"Unknown workflowType '{workflow_type}'.") from None


def resolve_job_name(workflow_type: str, *, env: dict[str, str] | None = None) -> str:
    """Resolve the Container Apps Job resource name to dispatch for
    `workflow_type`, reading the env var Terraform wires onto this Functions
    app (`env` is injectable for tests)."""
    source = env if env is not None else os.environ
    env_var = job_env_var_for_workflow_type(workflow_type)
    job_name = source.get(env_var)
    if not job_name:
        raise UnknownWorkflowTypeError(
            f"Environment variable '{env_var}' (job name for workflowType "
            f"'{workflow_type}') is not set."
        )
    return job_name
