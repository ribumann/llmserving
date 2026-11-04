"""Internal orchestration callback API client (contracts/api.md), trimmed to
only what the Functions app itself ever needs.

Ordinary progress reporting is done by the Container Apps Job worker process
itself (jobs/common/callback_client.py), not by this orchestrator - this
client exists purely so the orchestrator's crash-safety-net activities
(`report_terminal_failure`, `acknowledge_cancellation`) can still notify
FastAPI when a job never got the chance to report its own outcome (its
container was killed outright) or when a cancellation needs acknowledging.

Deliberately a separate module from jobs/common/callback_client.py rather
than a shared import: `functions/` is a zip/Functions-Core-Tools deployment
(plain importable packages under the app root), not a Docker image like each
jobs/* worker, so there is no natural shared-package boundary to import
across - each deployable unit bundles its own copy, matching how every
jobs/*/Dockerfile already bundles its own copy of jobs/common/.
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
    """Reports an `Orchestration Workflow`'s terminal outcome/cancellation
    acknowledgement to FastAPI's internal callback API."""

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


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise CallbackClientError(f"Required environment variable '{name}' is not set.")
    return value
