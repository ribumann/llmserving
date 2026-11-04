"""Start-only wrapper around azure-mgmt-appcontainers' Jobs operations, used by
`AzureDeployer` to pre-dispatch the `model_deployment` Container Apps Job
directly with a one-off Hugging Face credential override (T140/FR-082/FR-083).

This is a backend-side counterpart of `functions/orchestration_lib/
container_jobs.py`'s `dispatch_job` - duplicated rather than shared because
the Functions app and the backend are separate deployable units with no
shared package layout. Only the start operation is needed here: every other
workflow type is started via the Durable Functions orchestration app's own
`dispatch_job` activity (functions_client.py), and `deploy` is the one
workflow type FastAPI dispatches itself so the credential-carrying job-start
call never has to pass through, or be logged by, the Functions app (see
functions_client.py's module docstring). Polling/stopping the execution is
the generic orchestrator's job once it takes over via
`preDispatchedExecutionName` - the backend never polls it.

IMPORTANT: the Container Apps Jobs "start" REST API REPLACES the entire
container definition (including every `env` var) for that one execution - it
does not merge overrides with the job's own static `template.container.env`
(confirmed against the Container Apps Jobs REST API docs, and against
functions/orchestration_lib/container_jobs.py's own module docstring).
`dispatch_job` therefore always fetches the job's current definition first and
resends every existing env var plus the per-invocation overrides, so a
backend-dispatched run never silently loses required static configuration
such as `BACKEND_INTERNAL_CALLBACK_URL` (infra/control/main.tf).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol


class JobsClient(Protocol):
    """The subset of `azure.mgmt.appcontainers.ContainerAppsAPIClient` this
    module depends on, so tests can supply a fake instead of the real SDK."""

    jobs: Any


@dataclass(slots=True, frozen=True)
class JobDispatchResult:
    execution_name: str


def _default_client() -> JobsClient:
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.appcontainers import ContainerAppsAPIClient

    subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
    return ContainerAppsAPIClient(
        credential=DefaultAzureCredential(), subscription_id=subscription_id
    )


def _existing_env(container: Any) -> dict[str, str]:
    merged: dict[str, str] = {}
    for entry in container.env or []:
        name = entry.name if not isinstance(entry, dict) else entry.get("name")
        value = entry.value if not isinstance(entry, dict) else entry.get("value")
        if name:
            merged[name] = value or ""
    return merged


def dispatch_job(
    resource_group: str,
    job_name: str,
    env_overrides: dict[str, str],
    *,
    client: JobsClient | None = None,
) -> JobDispatchResult:
    """Start a new execution of `job_name`, overriding/adding `env_overrides`
    on top of every env var already defined on the job (never dropping the
    job's own static configuration - see module docstring)."""
    resolved_client = client or _default_client()

    job = resolved_client.jobs.get(resource_group, job_name)
    container = job.template.containers[0]

    merged_env = _existing_env(container)
    merged_env.update(env_overrides)

    if client is None:
        # Real SDK: build the typed model classes.
        from azure.mgmt.appcontainers.models import (
            EnvironmentVar,
            JobExecutionContainer,
            JobExecutionTemplate,
        )

        env_list: Any = [EnvironmentVar(name=k, value=v) for k, v in merged_env.items()]
        template: Any = JobExecutionTemplate(
            containers=[
                JobExecutionContainer(
                    name=container.name,
                    image=container.image,
                    command=container.command,
                    args=container.args,
                    env=env_list,
                    resources=container.resources,
                )
            ]
        )
    else:
        # Fake client in tests: plain dicts, avoiding a hard dependency on
        # azure-mgmt-appcontainers being installed just to run unit tests.
        template = {
            "containers": [
                {
                    "name": container.name,
                    "image": container.image,
                    "command": container.command,
                    "args": container.args,
                    "env": [{"name": k, "value": v} for k, v in merged_env.items()],
                    "resources": container.resources,
                }
            ]
        }

    poller = resolved_client.jobs.begin_start(resource_group, job_name, template=template)
    result = poller.result()
    return JobDispatchResult(execution_name=result.name)
