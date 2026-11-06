"""Shared helpers for locating the per-environment demo GPU VM (infra/demo's
managed or explicitly retained resource group).

The VM has no public IP (FR-079) - Container Apps Jobs are VNet-integrated into
the same shared VNet (infra/control/main.tf's
`azurerm_container_app_environment.control.infrastructure_subnet_id`) and reach
it over its private IP directly, so callers here must resolve that IP rather
than assume any routable hostname exists.

All Azure SDK client construction is lazy (only reached when a caller doesn't
inject a fake `client`), matching `callback_client.py`'s pattern, so unit tests
never need `azure-mgmt-network`/`azure-mgmt-compute` actually installed.
"""

from __future__ import annotations

import re
import shlex
import uuid
from typing import Any


def demo_resource_names(
    environment_id: str,
    name_prefix: str = "llm",
    *,
    resource_group_name: str | None = None,
) -> tuple[str, str, str]:
    """Returns (resource_group_name, vm_name, nic_name) matching infra/demo/main.tf's
    naming convention: `rg-llm-demo-{environmentId}`, `{namePrefix}-{environmentId}-vm`,
    `{namePrefix}-{environmentId}-nic`. An explicit saved group changes only the group.
    """
    if resource_group_name is not None and (
        not isinstance(resource_group_name, str)
        or not re.fullmatch(r"[A-Za-z0-9._()-]{1,90}", resource_group_name)
        or resource_group_name.endswith(".")
    ):
        raise ValueError("Invalid persisted demo resource group name.")
    resource_group = (
        resource_group_name
        if resource_group_name is not None
        else f"rg-llm-demo-{environment_id}"
    )
    prefixed = f"{name_prefix}-{environment_id}"
    return resource_group, f"{prefixed}-vm", f"{prefixed}-nic"


def _default_credential() -> Any:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()


def _default_network_client(subscription_id: str, credential: Any | None) -> Any:
    from azure.mgmt.network import NetworkManagementClient

    return NetworkManagementClient(credential or _default_credential(), subscription_id)


def _default_compute_client(subscription_id: str, credential: Any | None) -> Any:
    from azure.mgmt.compute import ComputeManagementClient

    return ComputeManagementClient(credential or _default_credential(), subscription_id)


def resolve_private_ip(
    subscription_id: str,
    environment_id: str,
    *,
    name_prefix: str = "llm",
    resource_group_name: str | None = None,
    credential: Any | None = None,
    client: Any | None = None,
) -> str:
    """Looks up the demo VM's NIC and returns its private IPv4 address."""
    resource_group, _vm_name, nic_name = demo_resource_names(
        environment_id, name_prefix, resource_group_name=resource_group_name
    )
    network_client = client or _default_network_client(subscription_id, credential)
    nic = network_client.network_interfaces.get(resource_group, nic_name)
    ip_configurations = nic.ip_configurations or []
    private_ip = ip_configurations[0].private_ip_address if ip_configurations else None
    if not private_ip:
        raise RuntimeError(
            f"NIC '{nic_name}' in resource group '{resource_group}' has no private IP address"
        )
    return str(private_ip)


def vllm_base_url(private_ip: str, port: int = 8000) -> str:
    return f"http://{private_ip}:{port}"


def ensure_vm_running(
    subscription_id: str,
    environment_id: str,
    *,
    name_prefix: str = "llm",
    resource_group_name: str | None = None,
    credential: Any | None = None,
    client: Any | None = None,
) -> str:
    """Starts the demo VM if it isn't already running and returns the power
    state observed before any restart was attempted (mainly for diagnostics).

    infra/demo/main.tf provisions this VM at interruptible Spot priority with
    `eviction_policy = "Deallocate"`. Azure can therefore evict the VM at any
    time due to capacity reclaiming, which stops (deallocates) it. A
    deallocated VM rejects Run Command with `OperationNotAllowed` ("the
    operation requires the VM to be running"), so `model_deployment` must call
    this before `run_command_on_vm` to restart an evicted VM rather than
    surface that as an opaque deploy failure.
    """
    resource_group, vm_name, _nic_name = demo_resource_names(
        environment_id, name_prefix, resource_group_name=resource_group_name
    )
    compute_client = client or _default_compute_client(subscription_id, credential)
    instance_view = compute_client.virtual_machines.instance_view(
        resource_group, vm_name
    )
    statuses = list(getattr(instance_view, "statuses", []) or [])
    power_state = "PowerState/unknown"
    for status in statuses:
        code = str(getattr(status, "code", ""))
        if code.startswith("PowerState/"):
            power_state = code
            break

    if power_state != "PowerState/running":
        poller = compute_client.virtual_machines.begin_start(resource_group, vm_name)
        poller.result()

    return power_state


def run_command_on_vm(
    subscription_id: str,
    environment_id: str,
    *,
    script_lines: list[str],
    name_prefix: str = "llm",
    resource_group_name: str | None = None,
    credential: Any | None = None,
    client: Any | None = None,
) -> Any:
    """Invokes the Azure VM Run Command extension (RunShellScript) on the demo VM
    and blocks until it completes, returning the SDK's run-command result only
    after a fresh stdout marker confirms Bash success. Missing/malformed results
    and SDK errors raise a fixed, output-free RuntimeError: Azure provisioning
    status and stderr presence are not the script's exit status.

    Used by `model_deployment` to invoke `/opt/llmserving/run-vllm.sh` with the
    model repo/HF token as transient parameters (cloud-init.tftpl) - never via
    SSH (the VM has no public IP and no inbound NSG rule for jobs beyond the
    VNet-internal path already used for HTTP)."""
    resource_group, vm_name, _nic_name = demo_resource_names(
        environment_id, name_prefix, resource_group_name=resource_group_name
    )
    compute_client = client or _default_compute_client(subscription_id, credential)
    # Classic RunShellScript can report ProvisioningState/succeeded even when
    # the shell exits 127. Run in explicit Bash (the extension may use /bin/sh),
    # with a separate parent that only prints a fresh marker on successful exit.
    # In particular, an explicit `exit 0` in the supplied script must still work.
    marker = f"LLMSERVING_RUN_OK_{uuid.uuid4().hex}"
    script = "set -euo pipefail\n" + "\n".join(script_lines)
    wrapped = [
        f"bash -c {shlex.quote(script)} || exit $?",
        f"printf '\\n%s\\n' {shlex.quote(marker)}",
    ]
    try:
        poller = compute_client.virtual_machines.begin_run_command(
            resource_group,
            vm_name,
            {"command_id": "RunShellScript", "script": wrapped},
        )
        result = poller.result()
        # SDK objects and their REST/dict equivalent both occur in callers/tests.
        values = result.get("value", []) if isinstance(result, dict) else result.value
        stdout: list[str] = []
        for value in values or []:
            code = value.get("code", "") if isinstance(value, dict) else value.code
            message = (
                value.get("message", "") if isinstance(value, dict) else value.message
            )
            if not isinstance(message, str):
                continue
            if code == "ComponentStatus/StdOut/succeeded":
                stdout.append(message)
            elif code == "ProvisioningState/succeeded":
                # Classic Linux Run Command combines the streams in one message.
                # Never accept a marker found only in stderr or in the preamble.
                before, separator, _stderr = message.partition("\n[stderr]")
                _prefix, start, output = before.partition("[stdout]\n")
                if separator and start:
                    stdout.append(output)
        if sum(output.splitlines().count(marker) for output in stdout) != 1:
            raise ValueError("Missing or ambiguous completion marker")
    except Exception:
        # SDK exceptions and extension streams can include the entire script,
        # including a transient HF token. Do not retain them as exception context.
        pass
    else:
        return result
    raise RuntimeError(
        "VM Run Command did not confirm successful script completion; "
        "command and output withheld."
    ) from None
