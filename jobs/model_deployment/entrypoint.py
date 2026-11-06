"""model_deployment Container Apps Job (T136/T137): starts vLLM on the demo GPU
VM for a given checkpoint via the Azure VM Run Command extension, never SSH
(the VM has no public IP - FR-079).

The demo VM is Spot-priority (infra/demo/main.tf) so Azure can evict/deallocate
it at any time; before dispatching Run Command this job calls
`ensure_vm_running` to restart the VM if it isn't already running, otherwise
Run Command fails with `OperationNotAllowed`.

Invocation contract (env vars set by the Durable Functions `dispatch_job`
activity as a job-start template override, never baked into the image):

- `WORKFLOW_ID`    - the Orchestration Workflow this run reports against.
- `JOB_INPUT_JSON` - JSON object: {"environmentId": str, "modelRepo": str,
                      "hfToken": str, "revision": str (optional, default
                      "main"), "namePrefix": str (optional, default
                      "llm"), "resourceGroupName": str (optional, saved scope),
                      "extraArgs": list[str] (optional),
                      "healthCheckAttempts": int (optional, default 120),
                      "healthCheckIntervalSeconds": number (optional, default 15)}.
                      `modelRepo` must be the actual Hugging Face repo id (e.g.
                      "Qwen/Qwen3-4B") - it is passed verbatim as vLLM's
                      `--model`. `revision` is a git ref *within* that repo
                      (branch/tag/PR ref, default "main") and is forwarded as
                      vLLM's `--revision`; it is never a substitute for
                      `modelRepo`.

The Hugging Face token is held only in this process's memory for the duration
of the run-command call and is never logged, persisted, or echoed back through
the callback API (FR-082/FR-083) - `_build_script` intentionally excludes it
from anything this module writes to diagnostics.
"""

from __future__ import annotations

import shlex
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.azure_demo_vm import (  # noqa: E402
    ensure_vm_running,
    resolve_private_ip,
    run_command_on_vm,
    vllm_base_url,
)
from common.callback_client import (  # noqa: E402
    CallbackClientError,
    WorkflowCallbackClient,
    job_input_from_env,
    required_env,
)
from common.telemetry import configure_job_telemetry  # noqa: E402
from common.vllm_client import check_health  # noqa: E402

RUN_VLLM_SCRIPT_PATH = "/opt/llmserving/run-vllm.sh"
BOOTSTRAP_WAIT_SCRIPT = """\
# Terraform VM provisioning does not imply cloud-init/runtime readiness.
for attempt in $(seq 1 150); do
  if [ -f /opt/llmserving/bootstrap.failed ]; then
    echo "GPU runtime bootstrap failed; model startup refused." >&2
    exit 1
  fi
  if [ -f /opt/llmserving/bootstrap.ready ] && [ -x /opt/llmserving/run-vllm.sh ]; then
    break
  fi
  sleep 10
done
if [ ! -f /opt/llmserving/bootstrap.ready ] || [ ! -x /opt/llmserving/run-vllm.sh ]; then
  echo "Timed out waiting for GPU runtime bootstrap; model startup refused." >&2
  exit 1
fi"""


def _build_script_lines(
    model_repo: str, hf_token: str, extra_args: list[str], *, revision: str = "main"
) -> list[str]:
    quoted_args = " ".join(
        shlex.quote(str(arg)) for arg in [*extra_args, "--revision", revision]
    )
    command = (
        f"{RUN_VLLM_SCRIPT_PATH} {shlex.quote(model_repo)} {shlex.quote(hf_token)}"
    )
    if quoted_args:
        command = f"{command} {quoted_args}"
    return [BOOTSTRAP_WAIT_SCRIPT, command]


def run(
    *,
    workflow_id: str,
    subscription_id: str,
    environment_id: str,
    model_repo: str,
    hf_token: str,
    name_prefix: str,
    extra_args: list[str],
    health_check_attempts: int,
    health_check_interval_seconds: float,
    callback: WorkflowCallbackClient,
    revision: str = "main",
    resource_group_name: str | None = None,
    resolve_ip: Any = resolve_private_ip,
    dispatch_run_command: Any = run_command_on_vm,
    ensure_running: Any = ensure_vm_running,
    is_healthy: Any = check_health,
    sleep: Any = time.sleep,
) -> None:
    callback.report_progress(workflow_id, phase="ensuring-vm-running")
    target = {"name_prefix": name_prefix}
    if resource_group_name is not None:
        target["resource_group_name"] = resource_group_name
    ensure_running(subscription_id, environment_id, **target)

    callback.report_progress(workflow_id, phase="dispatching-run-command")
    script_lines = _build_script_lines(
        model_repo, hf_token, extra_args, revision=revision
    )
    dispatch_run_command(
        subscription_id, environment_id, script_lines=script_lines, **target
    )

    callback.report_progress(workflow_id, phase="waiting-for-vllm-health")
    private_ip = resolve_ip(subscription_id, environment_id, **target)
    base_url = vllm_base_url(private_ip)

    # `docker run -d` (infra/demo/cloud-init.tftpl) returns as soon as the container
    # starts - it does NOT wait for vLLM to finish downloading/loading the model
    # weights, which for a 7B+ model with no warm Hugging Face cache can take well
    # beyond a few minutes. Report progress periodically (rather than only at the
    # start and end) so a long-but-healthy wait is distinguishable from a stuck one.
    healthy = False
    progress_interval_attempts = max(1, health_check_attempts // 10)
    for attempt in range(health_check_attempts):
        if is_healthy(base_url):
            healthy = True
            break
        if attempt > 0 and attempt % progress_interval_attempts == 0:
            callback.report_progress(
                workflow_id,
                phase="waiting-for-vllm-health",
                diagnostics={"attempt": attempt, "maxAttempts": health_check_attempts},
            )
        if attempt < health_check_attempts - 1:
            sleep(health_check_interval_seconds)

    if not healthy:
        raise RuntimeError(
            f"vLLM did not become healthy at {base_url}/health after "
            f"{health_check_attempts} attempts"
        )

    callback.complete_workflow(
        workflow_id,
        status="completed",
        phase="completed",
        diagnostics={"vllmBaseUrl": base_url, "modelRepo": model_repo},
    )


def main() -> int:
    workflow_id = required_env("WORKFLOW_ID")
    logger = configure_job_telemetry(workflow_id, logger_name="model_deployment")
    payload = job_input_from_env()
    environment_id = str(payload.get("environmentId", ""))
    model_repo = str(payload.get("modelRepo", ""))
    hf_token = str(payload.get("hfToken", ""))
    revision = str(payload.get("revision") or "main")
    name_prefix = str(payload.get("namePrefix", "llm"))
    extra_args = list(payload.get("extraArgs", []))
    # Defaults sized for a cold start (no warm Hugging Face cache) of a 7B-class
    # model on a fresh VM: 120 attempts * 15s = 30 minutes. The previous 30 * 10s
    # (5 minutes) budget only accounted for the Run Command dispatch itself
    # (docker run -d returns immediately) and left no room for vLLM's own
    # in-container model download/load, which reliably exceeded 5 minutes for
    # anything above a 3B model and caused spurious "did not become healthy"
    # deploy failures even though vLLM eventually did come up.
    health_check_attempts = int(payload.get("healthCheckAttempts", 120))
    health_check_interval_seconds = float(payload.get("healthCheckIntervalSeconds", 15))
    subscription_id = required_env("AZURE_SUBSCRIPTION_ID")

    # Deliberately logs only the model repo, never hf_token (FR-082/FR-083).
    logger.info(
        "Starting model deployment for environment %s repo=%s",
        environment_id,
        model_repo,
    )
    with WorkflowCallbackClient() as callback:
        try:
            if not environment_id or not model_repo:
                raise CallbackClientError(
                    "JOB_INPUT_JSON must include non-empty 'environmentId' and 'modelRepo'."
                )
            run(
                workflow_id=workflow_id,
                subscription_id=subscription_id,
                environment_id=environment_id,
                model_repo=model_repo,
                hf_token=hf_token,
                revision=revision,
                name_prefix=name_prefix,
                resource_group_name=payload.get("resourceGroupName"),
                extra_args=extra_args,
                health_check_attempts=health_check_attempts,
                health_check_interval_seconds=health_check_interval_seconds,
                callback=callback,
            )
        except Exception as exc:  # noqa: BLE001 - last-resort safety net so the job
            # always reports a terminal outcome; deliberately reports only str(exc),
            # never the raw hf_token/model_repo variables, to keep the credential
            # out of diagnostics (FR-082/FR-083).
            logger.exception("Model deployment failed")
            callback.complete_workflow(
                workflow_id,
                status="failed",
                phase="failed",
                diagnostics={"error": str(exc)},
            )
            return 1
    logger.info("Completed model deployment for environment %s", environment_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
