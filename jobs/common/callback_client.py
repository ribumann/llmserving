"""Internal orchestration callback API client (contracts/api.md).

Every Container Apps Job worker reports progress and its terminal result back
to FastAPI through this client, authenticating with its own user-assigned
managed identity - no shared secret, no service principal credential
(FR-082/FR-083, FR-086).

Workers never create an `Orchestration Workflow` themselves: FastAPI's
`AzureProviderAdapter` creates the workflow record (and acquires the
environment's single-writer lock) before ever dispatching a job, and passes
the resulting `workflowId` to the worker as its invocation input. A worker's
job is only to report progress against that existing workflow and, on exit,
report its terminal outcome.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

# Deliberately Azure Resource Manager's well-known, always-available first-party
# audience rather than a dedicated Entra ID app registration - see
# infra/control/main.tf's `local.internal_api_audience` comment for why: creating
# an app registration/service principal requires the Application Administrator
# directory role, which is not available to the identity that deploys this
# stack. Every managed identity in the tenant can already acquire a token for
# this audience with zero additional Entra permissions.
ARM_SCOPE = "https://management.azure.com/.default"


class CallbackClientError(RuntimeError):
    """Raised when the internal callback API rejects a request or cannot be reached."""


class TokenCredential:
    """The subset of `azure.identity.DefaultAzureCredential` this module depends
    on, so tests can supply a fake credential instead of making a real call to
    Entra ID."""

    def get_token(self, *scopes: str) -> Any: ...  # pragma: no cover - Protocol-style stub


class WorkflowCallbackClient:
    """Reports `Orchestration Workflow` progress/completion to FastAPI's
    internal callback API (POST/PATCH /internal/workflows/...)."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        credential: TokenCredential | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        resolved_base_url = base_url or os.environ.get("BACKEND_INTERNAL_CALLBACK_URL")
        if not resolved_base_url:
            raise CallbackClientError(
                "BACKEND_INTERNAL_CALLBACK_URL is not set; cannot reach the internal callback API."
            )
        self._base_url = resolved_base_url.rstrip("/")
        self._credential = credential or self._default_credential()
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    @staticmethod
    def _default_credential() -> TokenCredential:
        # Imported lazily so unit tests that supply a fake credential never need
        # azure-identity installed, and so importing this module never makes a
        # network call.
        from azure.identity import DefaultAzureCredential

        return DefaultAzureCredential()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> WorkflowCallbackClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        token = self._credential.get_token(ARM_SCOPE)
        return {"Authorization": f"Bearer {token.token}"}

    def report_progress(
        self,
        workflow_id: str,
        *,
        phase: str | None = None,
        dispatched_job_ref: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """PATCH /internal/workflows/{workflow_id} (contracts/api.md)."""
        body: dict[str, Any] = {}
        if phase is not None:
            body["phase"] = phase
        if dispatched_job_ref is not None:
            body["dispatchedJobRef"] = dispatched_job_ref
        if diagnostics is not None:
            body["diagnostics"] = diagnostics
        response = self._client.patch(
            f"{self._base_url}/{workflow_id}", json=body, headers=self._headers()
        )
        return self._parse(response)

    def complete_workflow(
        self,
        workflow_id: str,
        *,
        status: str,
        phase: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /internal/workflows/{workflow_id}/complete (contracts/api.md).

        `status` must be one of completed/failed/cancelled (FR-055 terminal
        states) - the internal API rejects anything else with 400.
        """
        body: dict[str, Any] = {"status": status}
        if phase is not None:
            body["phase"] = phase
        if diagnostics is not None:
            body["diagnostics"] = diagnostics
        response = self._client.post(
            f"{self._base_url}/{workflow_id}/complete", json=body, headers=self._headers()
        )
        return self._parse(response)

    def acknowledge_cancellation(self, workflow_id: str) -> dict[str, Any]:
        """POST /internal/workflows/{workflow_id}/cancel-ack (contracts/api.md).

        Idempotent - repeat acknowledgements are no-ops accepted by FastAPI.
        """
        response = self._client.post(
            f"{self._base_url}/{workflow_id}/cancel-ack", json={}, headers=self._headers()
        )
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise CallbackClientError(
                f"Internal callback API returned {response.status_code}: {response.text}"
            )
        return dict(response.json())


def job_input_from_env() -> dict[str, Any]:
    """Decode the JSON-encoded per-invocation job input Functions' `dispatch_job`
    activity sets as the `JOB_INPUT_JSON` env var override at job-start time
    (never baked into the image - see each worker's Dockerfile)."""
    import json

    raw = os.environ.get("JOB_INPUT_JSON", "")
    if not raw:
        raise CallbackClientError("JOB_INPUT_JSON is not set; no invocation input was provided.")
    return dict(json.loads(raw))


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise CallbackClientError(f"Required environment variable '{name}' is not set.")
    return value
