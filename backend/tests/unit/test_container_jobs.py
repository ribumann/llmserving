"""Unit tests for `dispatch_job` (backend/src/providers/azure/container_jobs.py),
which `AzureDeployer` uses to pre-dispatch the `model_deployment` Container
Apps Job with a one-off Hugging Face credential override (T140/FR-082/FR-083).
"""

from __future__ import annotations

from types import SimpleNamespace

from src.providers.azure.container_jobs import dispatch_job


class FakePoller:
    def __init__(self, result: object) -> None:
        self._result = result

    def result(self) -> object:
        return self._result


class FakeJobsOperations:
    """Fake `ContainerAppsAPIClient.jobs` - records the exact template passed
    to `begin_start` so tests can assert the env-merge behavior without the
    real azure-mgmt-appcontainers SDK installed."""

    def __init__(self, *, existing_env: list[dict[str, str]]) -> None:
        self._existing_env = existing_env
        self.begin_start_calls: list[tuple[str, str, dict]] = []

    def get(self, resource_group: str, job_name: str) -> object:
        container = SimpleNamespace(
            name="model-deployment",
            image="acr.example.com/model-deployment:latest",
            command=["python", "entrypoint.py"],
            args=[],
            env=self._existing_env,
            resources=SimpleNamespace(cpu=2.0, memory="4Gi"),
        )
        return SimpleNamespace(template=SimpleNamespace(containers=[container]))

    def begin_start(self, resource_group: str, job_name: str, *, template: dict) -> FakePoller:
        self.begin_start_calls.append((resource_group, job_name, template))
        return FakePoller(SimpleNamespace(name="model-deployment-exec-1"))


def test_dispatch_job_merges_overrides_onto_existing_env_without_dropping_static_vars() -> None:
    jobs = FakeJobsOperations(
        existing_env=[
            {"name": "BACKEND_INTERNAL_CALLBACK_URL", "value": "https://backend.internal"},
            {"name": "WORKFLOW_ID", "value": "stale-workflow-id"},
        ]
    )
    client = SimpleNamespace(jobs=jobs)

    result = dispatch_job(
        "rg-container-apps",
        "model-deployment",
        {"WORKFLOW_ID": "workflow-123", "JOB_INPUT_JSON": "{}"},
        client=client,
    )

    assert result.execution_name == "model-deployment-exec-1"
    assert len(jobs.begin_start_calls) == 1
    resource_group, job_name, template = jobs.begin_start_calls[0]
    assert resource_group == "rg-container-apps"
    assert job_name == "model-deployment"

    env_by_name = {entry["name"]: entry["value"] for entry in template["containers"][0]["env"]}
    # The pre-existing static env var must survive the start call (the
    # Container Apps Jobs "start" API replaces the whole env list, so
    # dispatch_job must resend it rather than only sending the overrides).
    assert env_by_name["BACKEND_INTERNAL_CALLBACK_URL"] == "https://backend.internal"
    # The override must win over whatever value was already set.
    assert env_by_name["WORKFLOW_ID"] == "workflow-123"
    assert env_by_name["JOB_INPUT_JSON"] == "{}"


def test_dispatch_job_handles_dict_shaped_existing_env_entries() -> None:
    """`_existing_env()` must accept both SDK model objects (`.name`/`.value`
    attributes) and plain dicts, since fake clients in tests use dicts."""
    jobs = FakeJobsOperations(existing_env=[{"name": "EXISTING_VAR", "value": "existing-value"}])
    client = SimpleNamespace(jobs=jobs)

    dispatch_job("rg-container-apps", "model-deployment", {"NEW_VAR": "new-value"}, client=client)

    _, _, template = jobs.begin_start_calls[0]
    env_by_name = {entry["name"]: entry["value"] for entry in template["containers"][0]["env"]}
    assert env_by_name["EXISTING_VAR"] == "existing-value"
    assert env_by_name["NEW_VAR"] == "new-value"
