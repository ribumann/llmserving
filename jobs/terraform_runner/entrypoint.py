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
re-uploads it after a successful `apply`/`destroy` - otherwise every run would
start from empty state and Terraform would never see resources a prior `apply`
created (breaking `destroy` entirely, and causing `apply` to try to recreate
already-existing resources). Auth uses this job's own user-assigned managed
identity via `DefaultAzureCredential` (storage-audience token), the same
pattern `common/callback_client.py` uses for the ARM-audience callback API.
`TF_STATE_STORAGE_ACCOUNT`/`TF_STATE_CONTAINER` are static env vars on this
job (infra/control/main.tf); when unset (local dev/tests), state
download/upload is a no-op and Terraform just uses fresh local state.

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
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

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
    if not account or not container:
        return None
    return f"https://{account}.blob.core.windows.net/{container}/{blob_name}"


def _storage_bearer_headers() -> dict[str, str] | None:
    try:
        from azure.identity import DefaultAzureCredential

        token = DefaultAzureCredential().get_token("https://storage.azure.com/.default").token
        return {"Authorization": f"Bearer {token}", "x-ms-version": "2023-11-03"}
    except Exception:
        return None


def _download_remote_state(working_dir: Path, environment_id: str) -> None:
    """Best-effort: downloads this environment's persisted state (if any) into
    working_dir/terraform.tfstate before init/apply/destroy. See module
    docstring for why this bypasses Terraform's own backend mechanism."""
    url = _blob_url(f"{environment_id}.tfstate")
    if not url:
        return
    headers = _storage_bearer_headers()
    if not headers:
        return
    try:
        response = httpx.get(url, headers=headers, timeout=30.0)
        if response.status_code == 200:
            (working_dir / _STATE_FILE_NAME).write_bytes(response.content)
    except Exception:
        pass  # fresh/local state is an acceptable fallback


def _upload_remote_state(working_dir: Path, environment_id: str) -> None:
    """Best-effort: persists this environment's state blob after a successful
    apply/destroy so the next run (on a different, ephemeral job execution)
    picks up where this one left off."""
    state_file = working_dir / _STATE_FILE_NAME
    url = _blob_url(f"{environment_id}.tfstate")
    if not url or not state_file.exists():
        return
    headers = _storage_bearer_headers()
    if not headers:
        return
    headers = {**headers, "x-ms-blob-type": "BlockBlob", "Content-Type": "application/json"}
    try:
        httpx.put(url, headers=headers, content=state_file.read_bytes(), timeout=30.0)
    except Exception:
        pass  # best-effort; the terraform run itself already succeeded


def _download_shared_state(working_dir: Path) -> None:
    """Best-effort: downloads infra/shared's one-time-applied state into a
    sibling `../shared/terraform.tfstate` directory next to `working_dir`, so
    infra/demo's `data.terraform_remote_state.shared` (main.tf) resolves
    inside this job's ephemeral container. See module docstring. Absent (e.g.
    local dev/tests, or infra/shared not yet applied), Terraform's own error
    surfaces normally rather than being masked here."""
    url = _blob_url(_SHARED_STATE_BLOB_NAME)
    if not url:
        return
    headers = _storage_bearer_headers()
    if not headers:
        return
    try:
        response = httpx.get(url, headers=headers, timeout=30.0)
        if response.status_code == 200:
            shared_dir = working_dir.parent / "shared"
            shared_dir.mkdir(parents=True, exist_ok=True)
            (shared_dir / _STATE_FILE_NAME).write_bytes(response.content)
    except Exception:
        pass  # let Terraform's own "state file not found" error surface instead


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
        raise CallbackClientError(f"Unsupported action '{action}'; expected apply or destroy.")

    callback.report_progress(workflow_id, phase="initializing")
    _ensure_azure_cli_auth()
    _download_shared_state(working_dir)
    _download_remote_state(working_dir, environment_id)
    _write_tfvars(working_dir, terraform_variables)

    init_result = _run_terraform(["init", "-input=false", "-no-color"], cwd=working_dir)
    if init_result.returncode != 0:
        raise TerraformRunError(
            "terraform init failed", stdout=init_result.stdout, stderr=init_result.stderr
        )

    callback.report_progress(workflow_id, phase=f"running terraform {action}")
    verb_args = (
        ["apply", "-input=false", "-auto-approve", "-no-color", "-var-file=terraform.tfvars.json"]
        if action == "apply"
        else [
            "destroy",
            "-input=false",
            "-auto-approve",
            "-no-color",
            "-var-file=terraform.tfvars.json",
        ]
    )
    run_result = _run_terraform(verb_args, cwd=working_dir)
    if run_result.returncode != 0:
        raise TerraformRunError(
            f"terraform {action} failed", stdout=run_result.stdout, stderr=run_result.stderr
        )
    _upload_remote_state(working_dir, environment_id)

    outputs: dict[str, Any] = {}
    if action == "apply":
        output_result = _run_terraform(["output", "-json"], cwd=working_dir)
        if output_result.returncode == 0:
            with contextlib.suppress(json.JSONDecodeError):
                outputs = json.loads(output_result.stdout)

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
