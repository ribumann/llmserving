"""Fixed read-only fallback inspection; never a deployment or VM validator."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter

from azure_canary import FALLBACK_TARGET

WORKFLOW = ".github/workflows/azure-fallback-preflight.yml"
REGION = "italynorth"
SKU = "Standard_NC4as_T4_v3"
GROUPS = {
    "shared": "rg-llmserving-e2e-shared",
    "control": "rg-llmserving-e2e-control",
    "demo": "rg-llmserving-e2e-demo",
    "canary": "rg-llmserving-e2e-canary",
}


class PreflightError(RuntimeError):
    pass


def validate_config() -> None:
    expected = {
        "AZURE_SUBSCRIPTION_ID": FALLBACK_TARGET.subscription,
        "AZURE_TENANT_ID": FALLBACK_TARGET.tenant,
        "AZURE_CLIENT_ID": FALLBACK_TARGET.client,
        "GITHUB_REPOSITORY": "ribumann/llmserving",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_WORKFLOW_REF": f"ribumann/llmserving/{WORKFLOW}@refs/heads/main",
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise PreflightError("Protected read-only preflight configuration mismatch.")


def read_azure(*arguments: str) -> object:
    allowed = {
        ("account", "show"),
        ("group", "show"),
        ("resource", "list"),
        ("vm", "list-skus"),
        ("vm", "list-usage"),
    }
    if arguments[:2] not in allowed:
        raise PreflightError("Operation is outside the read-only command allowlist.")
    try:
        result = subprocess.run(
            [
                "az",
                *arguments,
                "--subscription",
                FALLBACK_TARGET.subscription,
                "--only-show-errors",
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(f"Azure read failed ({type(exc).__name__}).") from None
    if result.returncode:
        raise PreflightError(
            f"Azure {' '.join(arguments[:2])} failed (exit {result.returncode}); "
            "authorization or service availability must be checked privately."
        )
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise PreflightError("Azure read returned invalid JSON.") from None


def summarize_sku(records: object) -> dict:
    if not isinstance(records, list):
        raise PreflightError("SKU response must be a list.")
    matches = [
        item
        for item in records
        if isinstance(item, dict)
        and item.get("name") == SKU
        and item.get("resourceType") == "virtualMachines"
        and REGION in item.get("locations", [])
    ]
    if len(matches) != 1:
        raise PreflightError("Exact regional VM SKU metadata is absent or ambiguous.")
    sku = matches[0]
    if (
        not isinstance(sku.get("capabilities", []), list)
        or any(not isinstance(entry, dict) for entry in sku.get("capabilities", []))
        or not isinstance(sku.get("restrictions", []), list)
        or not isinstance(sku.get("locationInfo", []), list)
    ):
        raise PreflightError("Exact SKU capability/restriction metadata is malformed.")
    return {
        "name": SKU,
        "region": REGION,
        "family": sku.get("family"),
        "capabilities": {
            entry["name"]: entry.get("value")
            for entry in sku.get("capabilities", [])
            if entry.get("name") in {"vCPUs", "MemoryGB", "GPUs", "LowPriorityCapable"}
        },
        "restrictions": sku.get("restrictions", []),
        "locationInfo": sku.get("locationInfo", []),
        "allocationVerified": False,
        "unzonedEligibility": "unknown; list-skus is not server-side deployment validation",
    }


def inspect() -> dict:
    validate_config()
    account = read_azure("account", "show")
    if (
        not isinstance(account, dict)
        or account.get("id") != FALLBACK_TARGET.subscription
        or account.get("tenantId") != FALLBACK_TARGET.tenant
        or not isinstance(account.get("user"), dict)
        or account.get("user", {}).get("type") != "servicePrincipal"
        or account.get("user", {}).get("name") != FALLBACK_TARGET.client
    ):
        raise PreflightError("Azure account/principal does not match the fixed target.")
    inventory = {}
    for alias, name in GROUPS.items():
        group = read_azure("group", "show", "--name", name)
        expected_id = (
            f"/subscriptions/{FALLBACK_TARGET.subscription}/resourceGroups/{name}"
        )
        if (
            not isinstance(group, dict)
            or str(group.get("id", "")).lower() != expected_id.lower()
            or group.get("name") != name
            or group.get("tags") != FALLBACK_TARGET.group_tags
        ):
            raise PreflightError(f"Fixed {alias} group ownership does not match.")
        resources = read_azure("resource", "list", "--resource-group", name)
        if not isinstance(resources, list) or any(
            not isinstance(item, dict)
            or not str(item.get("id", "")).lower().startswith(expected_id.lower() + "/")
            or not isinstance(item.get("type"), str)
            for item in resources
        ):
            raise PreflightError(f"Invalid {alias} resource inventory.")
        inventory[alias] = {
            "groupOwnershipVerified": True,
            "resourceCount": len(resources),
            "types": dict(Counter(item["type"] for item in resources)),
        }
    sku = summarize_sku(
        read_azure(
            "vm",
            "list-skus",
            "--location",
            REGION,
            "--resource-type",
            "virtualMachines",
            "--size",
            SKU,
            "--all",
        )
    )
    usage = read_azure("vm", "list-usage", "--location", REGION)
    if not isinstance(usage, list):
        raise PreflightError("Quota response must be a list.")
    family = sku["family"]
    if not isinstance(family, str) or not family.strip():
        raise PreflightError("Exact SKU family is missing; quota cannot be resolved.")
    names = {family.lower(), "cores", "lowprioritycores"}
    quota = [
        {
            "name": item["name"]["value"],
            "current": item.get("currentValue"),
            "limit": item.get("limit"),
        }
        for item in usage
        if isinstance(item, dict)
        and isinstance(item.get("name"), dict)
        and str(item["name"].get("value", "")).lower() in names
    ]
    if (
        len(quota) != len(names)
        or {item["name"].lower() for item in quota} != names
        or any(
            type(item[field]) is not int or item[field] < 0
            for item in quota
            for field in ("current", "limit")
        )
    ):
        raise PreflightError("Required quota rows are missing, ambiguous or malformed.")
    return {
        "sourceSha": os.environ.get("GITHUB_SHA"),
        "scope": "Read-only fallback inventory/SKU/quota, not deployment readiness",
        "groups": inventory,
        "sku": sku,
        "quota": quota,
        "resourcesCreated": False,
        "billableCleanupVerified": False,
        "deploymentAuthorizedByThisReport": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("validate-config", "inspect"))
    operation = parser.parse_args().operation
    try:
        if operation == "validate-config":
            validate_config()
            print("Fixed protected read-only target verified.")
        else:
            print(json.dumps(inspect(), indent=2))
    except PreflightError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
