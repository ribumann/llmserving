"""Client for the Durable Functions orchestration app's HTTP starter (T140,
functions/function_app.py's `http_start`/`raise_cancel_event`).

`AzureProviderAdapter` calls this to start (and cancel) Orchestration Workflows
instead of running Terraform/the vLLM engine adapter directly in-process (see
provision.py/deploy.py). Every workflow type is started the same way; the one
credential-carrying exception (`deploy`) is handled entirely by the caller,
which pre-dispatches the Container Apps Job itself (container_jobs.py) and
passes only the resulting `preDispatchedExecutionName` here - this client
never sees or forwards a Hugging Face token (FR-082/FR-083, research.md
"Secret handling").

Auth: the Functions app's HTTP endpoints require a function key
(`AuthLevel.FUNCTION`, functions/function_app.py) rather than an Entra ID app
registration. Retained-group deployments use Website Contributor at the exact
Functions site; legacy deployments retain subscription-level Contributor.
Both grant `Microsoft.Web/sites/host/listkeys/action`, so the default function key
is fetched at call time via the ARM control plane
(`POST {functionAppResourceId}/host/default/listkeys`) using the backend's
ordinary ARM-audience managed-identity token - no key is ever stored in Key
Vault or as a plain env var, and no new app registration is needed.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Protocol

import httpx

from src.api.correlation import workflow_correlation

ARM_SCOPE = "https://management.azure.com/.default"
ARM_API_VERSION = "2022-03-01"
# The fetched function key is cached for this long before being re-fetched, so a
# key rotation is picked up within one demo session without re-fetching on every
# single orchestration start.
_KEY_CACHE_SECONDS = 900.0

LOGGER = logging.getLogger(__name__)


class TokenCredential(Protocol):
    """The subset of `azure.identity.DefaultAzureCredential` this module depends
    on, so tests can supply a fake credential instead of making a real call to
    Entra ID."""

    def get_token(self, *scopes: str) -> Any: ...


class FunctionsClientError(RuntimeError):
    """Raised when the Functions app rejects a request or cannot be reached."""


class OrchestrationFunctionsClient:
    """Starts/cancels Orchestration Workflows on the Durable Functions app."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        function_app_resource_id: str | None = None,
        credential: TokenCredential | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
        clock: Any = time.monotonic,
    ) -> None:
        resolved_base_url = base_url or os.environ.get("ORCHESTRATION_FUNCTIONS_URL")
        resolved_resource_id = function_app_resource_id or os.environ.get(
            "ORCHESTRATION_FUNCTIONS_RESOURCE_ID"
        )
        if not resolved_base_url or not resolved_resource_id:
            raise FunctionsClientError(
                "ORCHESTRATION_FUNCTIONS_URL and ORCHESTRATION_FUNCTIONS_RESOURCE_ID must both "
                "be set to reach the Durable Functions orchestration app."
            )
        self._base_url = resolved_base_url.rstrip("/")
        self._resource_id = resolved_resource_id
        self._credential = credential or self._default_credential()
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self._clock = clock
        self._cached_key: str | None = None
        self._cached_key_at: float = float("-inf")

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

    def __enter__(self) -> OrchestrationFunctionsClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def _arm_headers(self) -> dict[str, str]:
        token = self._credential.get_token(ARM_SCOPE)
        return {"Authorization": f"Bearer {token.token}"}

    def _function_key(self) -> str:
        now = self._clock()
        if self._cached_key is not None and now - self._cached_key_at < _KEY_CACHE_SECONDS:
            return self._cached_key

        response = self._client.post(
            f"https://management.azure.com{self._resource_id}/host/default/listkeys",
            params={"api-version": ARM_API_VERSION},
            headers=self._arm_headers(),
        )
        if response.status_code >= 400:
            raise FunctionsClientError(
                f"Failed to list the Functions app's host keys ({response.status_code}): "
                f"{response.text}"
            )
        payload = response.json()
        key = payload.get("functionKeys", {}).get("default") or payload.get("masterKey")
        if not key:
            raise FunctionsClientError(
                "The Functions app's listkeys response did not include a usable key."
            )
        self._cached_key = str(key)
        self._cached_key_at = now
        return self._cached_key

    def start_orchestration(
        self,
        *,
        workflow_id: str,
        workflow_type: str,
        job_input: dict[str, Any] | None = None,
        pre_dispatched_execution_name: str | None = None,
    ) -> str:
        """POST /api/orchestrations - returns the Durable Functions instance ID.

        Exactly one of `job_input`/`pre_dispatched_execution_name` is meaningful
        per orchestration_lib/orchestration_logic.py's `OrchestrationInput`
        docstring: `deploy` always sets `pre_dispatched_execution_name` (the
        credential-carrying job was already started by the caller, see this
        module's docstring); every other workflow type sets `job_input` instead.
        """
        body: dict[str, Any] = {"workflowId": workflow_id, "workflowType": workflow_type}
        if job_input is not None:
            body["jobInput"] = job_input
        if pre_dispatched_execution_name is not None:
            body["preDispatchedExecutionName"] = pre_dispatched_execution_name

        with workflow_correlation(workflow_id):
            response = self._client.post(
                f"{self._base_url}/orchestrations",
                json=body,
                params={"code": self._function_key()},
            )
            if response.status_code >= 400:
                raise FunctionsClientError(
                    f"Failed to start orchestration for workflow '{workflow_id}' "
                    f"({response.status_code}): {response.text}"
                )
            payload = response.json()
            instance_id = payload.get("id") or payload.get("instanceId")
            if not instance_id:
                raise FunctionsClientError(
                    "The Functions app's start-orchestration response did not include "
                    "an instance id."
                )
            LOGGER.info(
                "Started orchestration instanceId=%s workflowType=%s", instance_id, workflow_type
            )
            return str(instance_id)

    def cancel_orchestration(self, instance_id: str, *, workflow_id: str | None = None) -> None:
        """POST /api/orchestrations/{instance_id}/cancel - relays the `cancel`
        external event the generic orchestrator waits on."""
        with workflow_correlation(workflow_id):
            response = self._client.post(
                f"{self._base_url}/orchestrations/{instance_id}/cancel",
                params={"code": self._function_key()},
            )
            if response.status_code >= 400:
                raise FunctionsClientError(
                    f"Failed to cancel orchestration '{instance_id}' ({response.status_code}): "
                    f"{response.text}"
                )
            LOGGER.info("Cancelled orchestration instanceId=%s", instance_id)
