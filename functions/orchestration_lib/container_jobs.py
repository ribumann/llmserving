"""Wrapper around azure-mgmt-appcontainers' Jobs/JobExecutions operations used
by the `dispatch_job`/`poll_job_status`/`stop_job` Durable Functions activities.

Method/model names below were verified directly against an installed
azure-mgmt-appcontainers==5.0.0 in this environment (there is no live Azure
Functions host here to integration-test against, so this was checked by
introspecting the actual SDK instead): `client.jobs.get`/`begin_start`/
`begin_stop_execution` and `client.jobs_executions.list`. `Job.template` and
`JobExecution.status` are top-level *flattened* properties - the SDK
flattens `.properties.X` onto the resource itself for these two models, so
there is no `.properties.template`/`.properties.status` indirection needed.

IMPORTANT: the Container Apps Jobs "start" REST API REPLACES the entire
container definition (including every `env` var) for that one execution - it
does not merge overrides with the job's own static `template.container.env`
(confirmed against the Container Apps Jobs REST API docs). `dispatch_job`
therefore always fetches the job's current definition first and resends
every existing env var plus the per-invocation overrides, so a
Functions-dispatched run never silently loses required static configuration
such as `BACKEND_INTERNAL_CALLBACK_URL` (infra/control/main.tf).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol


class JobsClient(Protocol):
    """The subset of `azure.mgmt.appcontainers.ContainerAppsAPIClient` this
    module depends on, so tests can supply a fake instead of the real SDK
    (which is not required to be installed to run unit tests)."""

    jobs: Any
    jobs_executions: Any


@dataclass
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


_TERMINAL_STATUSES = {"Succeeded", "Failed", "Stopped", "Degraded"}


def get_job_execution_status(
    resource_group: str,
    job_name: str,
    execution_name: str,
    *,
    client: JobsClient | None = None,
) -> str:
    """Return the execution's current `status` (Running/Processing/Stopped/
    Degraded/Failed/Succeeded/Unknown), or "NotFound" if it no longer appears
    in the job's execution list (e.g. purged)."""
    resolved_client = client or _default_client()
    for execution in resolved_client.jobs_executions.list(resource_group, job_name):
        if execution.name == execution_name:
            return execution.status or "Unknown"
    return "NotFound"


def is_terminal_status(status: str) -> bool:
    return status in _TERMINAL_STATUSES


def stop_job_execution(
    resource_group: str,
    job_name: str,
    execution_name: str,
    *,
    client: JobsClient | None = None,
) -> None:
    resolved_client = client or _default_client()
    poller = resolved_client.jobs.begin_stop_execution(resource_group, job_name, execution_name)
    poller.result()
