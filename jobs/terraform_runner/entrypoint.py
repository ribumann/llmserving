"""terraform_runner Container Apps Job (T136): runs Terraform against
`infra/demo` in isolation from FastAPI's request thread (T140 replaces the old
in-process `AzureProvisioner`/`ThreadPoolExecutor` apply with this job).

Invocation contract (env vars set by the Durable Functions `dispatch_job`
activity as a job-start template override, never baked into the image):

- `WORKFLOW_ID`            - the Orchestration Workflow this run reports against.
- `JOB_INPUT_JSON`         - JSON object: {"action": "apply" | "destroy",
                              "environmentId": str, "terraformVariables": dict}.
                              `terraformVariables` must match infra/demo's
                              actual variable schema (infra/demo/variables.tf):
                              subscription_id, environment_id, name_prefix,
                              profile_size_class, vm_size, admin_username,
                              admin_ssh_public_key, vllm_image, tags.

Any Hugging Face credential is deliberately never part of this job's input -
Terraform never provisions the model itself (FR-082/FR-083); that flows only
through the model_deployment job's own invocation input.

Remote state persistence: `infra/demo` declares no Terraform backend block at
all (a fresh local `terraform.tfstate` every run - see infra/control/main.tf's
`azurerm_role_assignment.terraform_runner_tfstate_blob` comment for why an
azurerm backend block doesn't work in this hosting context), so each
Container Apps Job execution downloads this environment's state blob (if any)
into its ephemeral working directory before `init`/`apply`/`destroy`, and
re-uploads it after `apply`/`destroy`, including partial state on failure.
Otherwise every run would start from empty state and never see resources a prior `apply`
created (breaking `destroy` entirely, and causing `apply` to try to recreate
already-existing resources). Auth uses this job's own user-assigned managed
identity via `DefaultAzureCredential` (storage-audience token), the same
pattern `common/callback_client.py` uses for the ARM-audience callback API.
`TF_STATE_STORAGE_ACCOUNT`/`TF_STATE_CONTAINER` are static env vars on this
job (infra/control/main.tf). Missing/partial cloud configuration, identity or
storage failures stop execution instead of falling back to empty state. Only
an explicit BlobNotFound permits a new apply; destroy requires existing state.
Outside Azure hosting, both unset variables retain local dev/test execution.
Persistence failure prevents a successful callback; do not retry mutations
until partial resource/state ownership has been recovered independently.

infra/demo also reads infra/shared's outputs (VNet/subnet, location) via a
`terraform_remote_state` "local" backend at a relative path
(`var.shared_state_path`, default `../shared/terraform.tfstate` -
infra/demo/main.tf). Unlike the Terraform CLI invocations an operator runs
directly from this repo checkout (infra/control, infra/shared themselves),
this job's container only ever has `infra/demo` baked into its image (this
Dockerfile) - there is no sibling `infra/shared` checkout for that relative
path to resolve against. The one-time-applied infra/shared state is therefore
also persisted to the same blob container under a fixed, non-environment-
specific blob name (`_SHARED_STATE_BLOB_NAME`) and downloaded into a sibling
`../shared/terraform.tfstate` working directory before every run, exactly
mirroring the per-environment state download above (never re-uploaded by this
job - infra/shared is only ever applied by an operator, not by this job).
An environment-specific blob lease serializes cooperating workers across
download, mutation and persistence. This remains manual state transfer, not
a full remote backend or cloud bootstrap certification.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from azure.core.exceptions import AzureError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.callback_client import (  # noqa: E402
    CallbackClientError,
    WorkflowCallbackClient,
    job_input_from_env,
    required_env,
)
from common.telemetry import configure_job_telemetry  # noqa: E402

INFRA_DEMO_DIR = Path(__file__).resolve().parent / "infra" / "demo"
APPLY_TIMEOUT_SECONDS = 3600
_ALLOWED_ACTIONS = {"apply", "destroy"}
_STATE_FILE_NAME = "terraform.tfstate"
# Fixed blob name for infra/shared's one-time-applied state - see module docstring.
_SHARED_STATE_BLOB_NAME = "infra-shared.tfstate"


def _blob_url(blob_name: str) -> str | None:
    account = os.environ.get("TF_STATE_STORAGE_ACCOUNT")
    container = os.environ.get("TF_STATE_CONTAINER")
    if not account and not container:
        if any(
            os.environ.get(name)
            for name in (
                "CONTAINER_APP_JOB_NAME",
                "CONTAINER_APP_NAME",
                "IDENTITY_ENDPOINT",
            )
        ):
            raise TerraformRunError(
                "Cloud Terraform execution requires configured remote state.",
                stdout="",
                stderr="",
            )
        return None
    if not account or not container:
        raise TerraformRunError(
            "Both TF_STATE_STORAGE_ACCOUNT and TF_STATE_CONTAINER are required.",
            stdout="",
            stderr="",
        )
    if (
        not re.fullmatch(r"[a-z0-9]{3,24}", account)
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])", container)
        or "--" in container
    ):
        raise TerraformRunError(
            "Invalid remote state storage name.", stdout="", stderr=""
        )
    return f"https://{account}.blob.core.windows.net/{container}/{blob_name}"


def _storage_bearer_headers() -> dict[str, str]:
    try:
        from azure.identity import DefaultAzureCredential

        token = (
            DefaultAzureCredential()
            .get_token("https://storage.azure.com/.default")
            .token
        )
        return {
            "Authorization": f"Bearer {token}",
            "x-ms-version": "2023-11-03",
            "x-ms-date": format_datetime(datetime.now(UTC), usegmt=True),
        }
    except AzureError as exc:
        raise TerraformRunError(
            "Remote state identity authentication failed.", stdout="", stderr=""
        ) from exc


def _validate_state(content: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TerraformRunError(
            "Terraform state is not valid JSON.", stdout="", stderr=""
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 4
        or not isinstance(payload.get("resources"), list)
        or not isinstance(payload.get("outputs"), dict)
    ):
        raise TerraformRunError(
            "Terraform state has invalid structure.", stdout="", stderr=""
        )
    return payload


def _validate_group_ownership(
    working_dir: Path, environment_id: str, variables: dict[str, Any]
) -> None:
    existing = variables.get("existing_resource_group_name")
    if existing is not None and (
        not isinstance(existing, str)
        or not re.fullmatch(r"[A-Za-z0-9._()-]{1,90}", existing)
        or existing.endswith(".")
    ):
        raise TerraformRunError(
            "Invalid retained resource group name.", stdout="", stderr=""
        )
    state_file = working_dir / _STATE_FILE_NAME
    if not state_file.exists():
        return
    state = _validate_state(state_file.read_bytes())
    expected = existing or f"rg-llm-demo-{environment_id}"
    for resource in state["resources"]:
        if not isinstance(resource, dict):
            raise TerraformRunError("Invalid resource state.", stdout="", stderr="")
        resource_type = resource.get("type")
        mode = resource.get("mode", "managed")
        if not isinstance(resource_type, str) or not isinstance(mode, str):
            raise TerraformRunError(
                "Invalid resource type or ownership mode.", stdout="", stderr=""
            )
        if mode not in {"managed", "data"} or (
            mode == "managed"
            and resource_type
            not in {
                "azurerm_resource_group",
                "azurerm_network_interface",
                "azurerm_linux_virtual_machine",
                "azurerm_virtual_machine_extension",
            }
        ):
            raise TerraformRunError(
                "Unexpected managed resource or ownership mode in demo state.",
                stdout="",
                stderr="",
            )
        if (
            resource_type
            in {
                "azurerm_network_interface",
                "azurerm_linux_virtual_machine",
                "azurerm_virtual_machine_extension",
            }
            and mode == "managed"
        ):
            instances = resource.get("instances")
            if not isinstance(instances, list):
                raise TerraformRunError(
                    "Invalid environment resource state.", stdout="", stderr=""
                )
            for instance in instances:
                attributes = (
                    instance.get("attributes") if isinstance(instance, dict) else None
                )
                tags = attributes.get("tags") if isinstance(attributes, dict) else None
                if (
                    not isinstance(tags, dict)
                    or tags.get("environmentId") != environment_id
                ):
                    raise TerraformRunError(
                        "Terraform resource does not match the environment owner.",
                        stdout="",
                        stderr="",
                    )
                if resource_type != "azurerm_virtual_machine_extension":
                    name = attributes.get("resource_group_name")
                    if not isinstance(name, str) or name.lower() != expected.lower():
                        raise TerraformRunError(
                            "Terraform resource group does not match the environment owner.",
                            stdout="",
                            stderr="",
                        )
        if resource_type != "azurerm_resource_group":
            continue
        instances = resource.get("instances")
        if mode not in {"managed", "data"} or not isinstance(instances, list):
            raise TerraformRunError(
                "Invalid resource group state.", stdout="", stderr=""
            )
        for instance in instances:
            attributes = (
                instance.get("attributes") if isinstance(instance, dict) else None
            )
            name = attributes.get("name") if isinstance(attributes, dict) else None
            if not isinstance(name, str):
                raise TerraformRunError(
                    "Invalid resource group state.", stdout="", stderr=""
                )
            if (mode == "managed" and existing is not None) or (
                mode == "data" and existing is None
            ):
                raise TerraformRunError(
                    "Resource group ownership mode cannot change; use fresh environment state.",
                    stdout="",
                    stderr="",
                )
            if name.lower() != expected.lower():
                raise TerraformRunError(
                    "Terraform state resource group does not match the environment owner.",
                    stdout="",
                    stderr="",
                )


def _download_state(url: str, destination: Path, *, allow_missing: bool) -> bool:
    headers = _storage_bearer_headers()
    if not headers:
        raise TerraformRunError(
            "Remote state identity unavailable.", stdout="", stderr=""
        )
    try:
        response = httpx.get(url, headers=headers, timeout=30.0)
    except httpx.RequestError as exc:
        raise TerraformRunError(
            "Remote state download failed.", stdout="", stderr=""
        ) from exc
    if (
        response.status_code == 404
        and response.headers.get("x-ms-error-code") == "BlobNotFound"
        and allow_missing
    ):
        if destination.exists():
            raise TerraformRunError(
                "Remote state absent but local state exists; refusing stale state.",
                stdout="",
                stderr="",
            )
        return False
    if response.status_code != 200:
        raise TerraformRunError(
            f"Remote state download returned HTTP {response.status_code}.",
            stdout="",
            stderr="",
        )
    _validate_state(response.content)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return True


def _download_remote_state(
    working_dir: Path, environment_id: str, *, allow_missing: bool = True
) -> None:
    url = _blob_url(f"{environment_id}.tfstate")
    if url:
        _download_state(
            url, working_dir / _STATE_FILE_NAME, allow_missing=allow_missing
        )


def _upload_remote_state(
    working_dir: Path, environment_id: str, *, required: bool = True
) -> None:
    """Persist state, including partial mutations, or explicitly fail the run."""
    state_file = working_dir / _STATE_FILE_NAME
    url = _blob_url(f"{environment_id}.tfstate")
    if not url:
        return
    if not state_file.exists():
        if required:
            raise TerraformRunError(
                "Terraform did not produce the required remote state file.",
                stdout="",
                stderr="",
            )
        return
    headers = _storage_bearer_headers()
    if not headers:
        raise TerraformRunError(
            "Remote state identity unavailable.", stdout="", stderr=""
        )
    headers = {
        **headers,
        "x-ms-blob-type": "BlockBlob",
        "Content-Type": "application/json",
    }
    content = state_file.read_bytes()
    _validate_state(content)
    try:
        response = httpx.put(url, headers=headers, content=content, timeout=30.0)
    except httpx.RequestError as exc:
        raise TerraformRunError(
            "Remote state persistence failed; recover partial resources before retry.",
            stdout="",
            stderr="",
        ) from exc
    if response.status_code != 201:
        raise TerraformRunError(
            f"Remote state persistence returned HTTP {response.status_code}; "
            "recover partial resources before retry.",
            stdout="",
            stderr="",
        )


def _download_shared_state(working_dir: Path) -> None:
    """Require readable shared state whenever cloud persistence is configured."""
    url = _blob_url(_SHARED_STATE_BLOB_NAME)
    if not url:
        return
    _download_state(
        url, working_dir.parent / "shared" / _STATE_FILE_NAME, allow_missing=False
    )


@dataclass
class _StateLock:
    mutation_started: bool = False


def _lock_put(
    url: str, headers: dict[str, str], content: bytes = b""
) -> httpx.Response:
    try:
        return httpx.put(
            url,
            headers={**_storage_bearer_headers(), **headers},
            content=content,
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        raise TerraformRunError(
            "Remote state lock request failed; verify ownership before retry.",
            stdout="",
            stderr="",
        ) from exc


@contextmanager
def _remote_state_lock(environment_id: str, workflow_id: str) -> Iterator[_StateLock]:
    marker = _StateLock()
    url = _blob_url(f"locks/{environment_id}.json")
    if not url:
        yield marker
        return
    lease_id = str(uuid4())
    recovery_blob = f"locks/{environment_id}/attempts/{uuid4()}.json"
    ownership = {
        "environmentId": environment_id,
        "workflowId": workflow_id,
        "recoveryBlob": recovery_blob,
    }
    owner = json.dumps(ownership).encode("utf-8")
    try:
        existing = httpx.get(url, headers=_storage_bearer_headers(), timeout=30.0)
    except httpx.RequestError as exc:
        raise TerraformRunError(
            "Remote state lock read failed.", stdout="", stderr=""
        ) from exc
    if (
        existing.status_code == 404
        and existing.headers.get("x-ms-error-code") == "BlobNotFound"
    ):
        created = _lock_put(
            url,
            {
                "If-None-Match": "*",
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": "application/json",
            },
            owner,
        )
        if created.status_code != 201 and not (
            created.status_code == 412
            and created.headers.get("x-ms-error-code") == "ConditionNotMet"
        ):
            raise TerraformRunError(
                f"Remote state lock creation returned HTTP {created.status_code}.",
                stdout="",
                stderr="",
            )
    elif existing.status_code == 200:
        try:
            previous_owner = existing.json()
        except ValueError as exc:
            raise TerraformRunError(
                "Remote state lock ownership is malformed.", stdout="", stderr=""
            ) from exc
        if (
            not isinstance(previous_owner, dict)
            or previous_owner.get("environmentId") != environment_id
            or not isinstance(previous_owner.get("workflowId"), str)
        ):
            raise TerraformRunError(
                "Remote state lock ownership does not match.", stdout="", stderr=""
            )
    else:
        raise TerraformRunError(
            f"Remote state lock read returned HTTP {existing.status_code}.",
            stdout="",
            stderr="",
        )
    recovery_url = _blob_url(recovery_blob)
    if not recovery_url:
        raise TerraformRunError(
            "Remote state configuration changed before acquisition.",
            stdout="",
            stderr="",
        )
    recovered = _lock_put(
        recovery_url,
        {
            "If-None-Match": "*",
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": "application/json",
        },
        json.dumps({**ownership, "leaseId": lease_id}).encode("utf-8"),
    )
    if recovered.status_code != 201:
        raise TerraformRunError(
            f"Remote state lease recovery record returned HTTP {recovered.status_code}; "
            "refusing acquisition without durable ownership recovery.",
            stdout="",
            stderr="",
        )
    acquired = _lock_put(
        f"{url}?comp=lease",
        {
            "x-ms-lease-action": "acquire",
            "x-ms-lease-duration": "-1",
            "x-ms-proposed-lease-id": lease_id,
        },
    )
    if acquired.status_code != 201 or acquired.headers.get("x-ms-lease-id") != lease_id:
        raise TerraformRunError(
            f"Remote state lock acquisition returned HTTP {acquired.status_code}; "
            "verify the owning workflow before retry.",
            stdout="",
            stderr="",
        )
    successful = False
    try:
        recorded = _lock_put(
            url,
            {
                "x-ms-lease-id": lease_id,
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": "application/json",
            },
            owner,
        )
        if recorded.status_code != 201:
            raise TerraformRunError(
                f"Remote state lock ownership write returned HTTP {recorded.status_code}.",
                stdout="",
                stderr="",
            )
        yield marker
        successful = True
    finally:
        # Never expire or release a failed mutation's lock into a blind retry.
        if successful or not marker.mutation_started:
            released = _lock_put(
                f"{url}?comp=lease",
                {"x-ms-lease-action": "release", "x-ms-lease-id": lease_id},
            )
            if released.status_code != 200:
                raise TerraformRunError(
                    f"Remote state lock release returned HTTP {released.status_code}; "
                    "operator recovery required.",
                    stdout="",
                    stderr="",
                )
        else:
            logging.getLogger(__name__).error(
                "Remote state lock retained after failed mutation; "
                "verify worker termination and recover state before retry."
            )


class TerraformRunError(RuntimeError):
    """Raised when Terraform exits non-zero; carries the captured output."""

    def __init__(self, message: str, *, stdout: str, stderr: str) -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def _write_tfvars(working_dir: Path, terraform_variables: dict[str, Any]) -> Path:
    tfvars_path = working_dir / "terraform.tfvars.json"
    tfvars_path.write_text(json.dumps(terraform_variables, indent=2), encoding="utf-8")
    return tfvars_path


def _run_terraform(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["terraform", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=APPLY_TIMEOUT_SECONDS,
    )


def _ensure_azure_cli_auth() -> None:
    """Authenticates the `az` CLI via this job's user-assigned managed identity,
    then steers the azurerm provider at ARM_USE_CLI (Azure CLI token cache)
    instead of ARM_USE_MSI (the provider's own MSI implementation).

    This works around a confirmed, still-open upstream bug
    (hashicorp/terraform-provider-azurerm#33001, hashicorp/go-azure-sdk#1217):
    Container Apps' managed-identity sidecar requires an `X-IDENTITY-HEADER`
    header on every token request, but azurerm's Go SDK never sends it
    (`CustomManagedIdentityHeaders` is never populated), so
    ManagedIdentityAuthorizer's mandatory Microsoft Graph claims-parsing call
    (internal/clients/auth.go's BuildResourceManagerAccount - runs
    unconditionally for every provider init, not gated by any argument) always
    gets HTTP 403 from the sidecar, regardless of ARM_MSI_ENDPOINT/
    ARM_MSI_API_VERSION. `az login --identity` uses azure-cli's own Python
    auth stack (azure.cli.core / MSAL), which *does* implement the Container
    Apps identity-header convention correctly, so routing the provider through
    the CLI's cached token instead sidesteps the broken code path entirely.
    Only this job needs the workaround: the other Container Apps Jobs
    authenticate via azure-identity's `DefaultAzureCredential` directly (no
    Terraform involved), which already handles this convention correctly.
    """
    client_id = os.environ.get("AZURE_CLIENT_ID") or os.environ.get("ARM_CLIENT_ID")
    if not client_id:
        raise TerraformRunError(
            "AZURE_CLIENT_ID/ARM_CLIENT_ID not set; cannot az login --identity",
            stdout="",
            stderr="",
        )
    login_result = subprocess.run(
        ["az", "login", "--identity", "--client-id", client_id],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if login_result.returncode != 0:
        raise TerraformRunError(
            "az login --identity failed",
            stdout=login_result.stdout,
            stderr=login_result.stderr,
        )
    # Steer the azurerm provider onto the (working) Azure CLI auth path instead
    # of its own (broken, in this hosting context) MSI implementation. These
    # override the static ARM_USE_MSI=true/ARM_USE_CLI env vars set on the job
    # by infra/control/main.tf, which are shared across all 5 jobs and correct
    # for everything except Terraform's own auth inside this one.
    os.environ["ARM_USE_MSI"] = "false"
    os.environ["ARM_USE_CLI"] = "true"


def run(
    *,
    workflow_id: str,
    environment_id: str,
    action: str,
    terraform_variables: dict[str, Any],
    working_dir: Path = INFRA_DEMO_DIR,
    callback: WorkflowCallbackClient,
) -> None:
    if action not in _ALLOWED_ACTIONS:
        raise CallbackClientError(
            f"Unsupported action '{action}'; expected apply or destroy."
        )
    if not re.fullmatch(r"[a-z0-9-]{3,20}", environment_id):
        raise CallbackClientError(
            "Invalid environmentId for Terraform state isolation."
        )
    if (
        "environment_id" in terraform_variables
        and terraform_variables["environment_id"] != environment_id
    ):
        raise CallbackClientError(
            "Terraform environment_id must match the state owner."
        )
    _blob_url(f"{environment_id}.tfstate")

    callback.report_progress(workflow_id, phase="initializing")
    _ensure_azure_cli_auth()
    with _remote_state_lock(environment_id, workflow_id) as lock:
        _download_shared_state(working_dir)
        _download_remote_state(
            working_dir, environment_id, allow_missing=action == "apply"
        )
        _validate_group_ownership(working_dir, environment_id, terraform_variables)
        _write_tfvars(working_dir, terraform_variables)

        init_result = _run_terraform(
            ["init", "-input=false", "-no-color"], cwd=working_dir
        )
        if init_result.returncode != 0:
            raise TerraformRunError(
                "terraform init failed",
                stdout=init_result.stdout,
                stderr=init_result.stderr,
            )

        callback.report_progress(workflow_id, phase=f"running terraform {action}")
        verb_args = (
            [
                "apply",
                "-input=false",
                "-auto-approve",
                "-no-color",
                "-var-file=terraform.tfvars.json",
            ]
            if action == "apply"
            else [
                "destroy",
                "-input=false",
                "-auto-approve",
                "-no-color",
                "-var-file=terraform.tfvars.json",
            ]
        )
        run_result = None
        lock.mutation_started = True
        try:
            run_result = _run_terraform(verb_args, cwd=working_dir)
        finally:
            _upload_remote_state(
                working_dir,
                environment_id,
                required=run_result is not None and run_result.returncode == 0,
            )
        if run_result.returncode != 0:
            raise TerraformRunError(
                f"terraform {action} failed",
                stdout=run_result.stdout,
                stderr=run_result.stderr,
            )

        outputs: dict[str, Any] = {}
        if action == "apply":
            output_result = _run_terraform(["output", "-json"], cwd=working_dir)
            if output_result.returncode != 0:
                raise TerraformRunError(
                    "terraform output failed",
                    stdout=output_result.stdout,
                    stderr=output_result.stderr,
                )
            try:
                outputs = json.loads(output_result.stdout)
            except json.JSONDecodeError as exc:
                raise TerraformRunError(
                    "terraform output is not valid JSON", stdout="", stderr=""
                ) from exc
            if not isinstance(outputs, dict):
                raise TerraformRunError(
                    "terraform output has invalid structure", stdout="", stderr=""
                )

    callback.complete_workflow(
        workflow_id,
        status="completed",
        phase="completed",
        diagnostics={"action": action, "outputs": outputs},
    )


def main() -> int:
    workflow_id = required_env("WORKFLOW_ID")
    logger = configure_job_telemetry(workflow_id, logger_name="terraform_runner")
    payload = job_input_from_env()
    environment_id = str(payload.get("environmentId", ""))
    action = str(payload.get("action", "apply"))
    terraform_variables = dict(payload.get("terraformVariables", {}))

    logger.info("Starting terraform %s for environment %s", action, environment_id)
    with WorkflowCallbackClient() as callback:
        try:
            run(
                workflow_id=workflow_id,
                environment_id=environment_id,
                action=action,
                terraform_variables=terraform_variables,
                callback=callback,
            )
        except TerraformRunError as exc:
            logger.error("terraform %s failed: %s", action, exc)
            callback.complete_workflow(
                workflow_id,
                status="failed",
                phase="failed",
                diagnostics={
                    "action": action,
                    "error": str(exc),
                    "stdout": exc.stdout[-4000:],
                    "stderr": exc.stderr[-4000:],
                },
            )
            return 1
        except Exception as exc:  # noqa: BLE001 - last-resort safety net so the job
            # always reports a terminal outcome rather than leaving the workflow
            # stuck as "running" forever if something unexpected blows up.
            logger.exception("terraform %s failed unexpectedly", action)
            callback.complete_workflow(
                workflow_id,
                status="failed",
                phase="failed",
                diagnostics={"action": action, "error": str(exc)},
            )
            return 1
    logger.info("Completed terraform %s for environment %s", action, environment_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
