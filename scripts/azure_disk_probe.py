"""One fixed unattached 4 GiB disk probe; never a general resource cleaner."""

from __future__ import annotations

from operator_config import setting

import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from azure_canary import FALLBACK_TARGET

GROUP = setting("demo_group")
DISK = "disk-llmserving-release-cleanup-probe"
REGION = setting("region")
CREATE_WORKFLOW = ".github/workflows/azure-fallback-disk-probe.yml"
CLEANUP_WORKFLOW = ".github/workflows/azure-fallback-disk-cleanup.yml"
REPOSITORY = setting("repository")
MAX_MONTHLY_USD = 10


class ProbeError(RuntimeError):
    pass


def validate_price(payload: object) -> float:
    if (
        not isinstance(payload, dict)
        or payload.get("BillingCurrency") != "USD"
        or payload.get("NextPageLink")
        or not isinstance(payload.get("Items"), list)
    ):
        raise ProbeError("Public disk-price response is malformed or incomplete.")
    matches = [
        item
        for item in payload["Items"]
        if isinstance(item, dict)
        and item.get("armRegionName") == REGION
        and item.get("productName") == "Standard HDD Managed Disks"
        and item.get("skuName") == "S4 LRS"
        and item.get("type") == "Consumption"
        and item.get("currencyCode") == "USD"
        and item.get("unitOfMeasure") == "1/Month"
        and item.get("isPrimaryMeterRegion") is True
    ]
    if len(matches) != 1:
        raise ProbeError(
            "Exactly one current Italy North S4 LRS monthly price is required."
        )
    item = matches[0]
    price = item.get("retailPrice")
    if type(price) not in {int, float} or not 0 < price <= MAX_MONTHLY_USD:
        raise ProbeError(
            "Disk monthly retail price is unknown or above the USD 10 ceiling."
        )
    try:
        effective = datetime.fromisoformat(item["effectiveStartDate"])
        if effective.tzinfo is None or effective > datetime.now(UTC):
            raise ValueError("Future/unspecified price.")
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ProbeError(
            "Disk price effective date is missing or not current."
        ) from None
    return float(price)


def quote() -> float:
    query = urlencode(
        {
            "$filter": (
                f"armRegionName eq '{REGION}' and "
                "productName eq 'Standard HDD Managed Disks' and skuName eq 'S4 LRS'"
            ),
        }
    )
    try:
        with urlopen(
            f"https://prices.azure.com/api/retail/prices?{query}", timeout=20
        ) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ProbeError("Public disk-price response exceeds the fixed size bound.")
        payload = json.loads(data)
        try:
            price = validate_price(payload)
        except ProbeError:
            if isinstance(payload, dict):
                items = payload.get("Items")
                print(
                    json.dumps(
                        {
                            "publicPriceSchemaKeys": sorted(payload),
                            "publicPriceRowCount": (
                                len(items) if isinstance(items, list) else None
                            ),
                            "publicPriceRows": [
                                {
                                    key: item.get(key)
                                    for key in (
                                        "armRegionName",
                                        "productName",
                                        "skuName",
                                        "type",
                                        "currencyCode",
                                        "unitOfMeasure",
                                        "isPrimaryMeterRegion",
                                        "effectiveStartDate",
                                        "retailPrice",
                                    )
                                }
                                for item in (
                                    items[:8] if isinstance(items, list) else []
                                )
                                if isinstance(item, dict)
                            ],
                        }
                    )
                )
            raise
    except (URLError, TimeoutError, OSError, ValueError):
        raise ProbeError(
            "Public disk-price query failed; no price fallback or creation."
        ) from None
    print(
        f"Current public S4 LRS price: USD {price:.6f}/month, "
        "excluding tax/contract discounts; requested 4 GiB bills at the S4 tier. "
        "One-month delayed-cleanup contingency is below USD 10. "
        "This is not an Azure hard spending cap."
    )
    return price


def command(arguments: list[str]) -> object:
    try:
        result = subprocess.run(
            arguments, capture_output=True, text=True, check=False, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(f"Probe command failed ({type(exc).__name__}).") from None
    if result.returncode:
        raise ProbeError(
            f"{arguments[0]} command failed (exit {result.returncode}); "
            "inspect service/authorization diagnostics privately."
        )
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except ValueError:
        raise ProbeError("Probe command returned invalid JSON.") from None


def az(*arguments: str) -> object:
    return command(
        [
            "az",
            *arguments,
            "--subscription",
            FALLBACK_TARGET.subscription,
            "--only-show-errors",
            "--output",
            "json",
        ]
    )


def validate_config(operation: str) -> None:
    expected = {
        "AZURE_SUBSCRIPTION_ID": FALLBACK_TARGET.subscription,
        "AZURE_TENANT_ID": FALLBACK_TARGET.tenant,
        "AZURE_CLIENT_ID": FALLBACK_TARGET.client,
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise ProbeError("Protected disk-probe target configuration mismatch.")
    workflow = CREATE_WORKFLOW if operation == "create" else CLEANUP_WORKFLOW
    if (
        os.environ.get("GITHUB_WORKFLOW_REF")
        != f"{REPOSITORY}/{workflow}@refs/heads/main"
    ):
        raise ProbeError("Operation does not match the fixed protected workflow.")
    event = os.environ.get("GITHUB_EVENT_NAME")
    if event not in (
        {"workflow_dispatch"}
        if operation == "create"
        else {
            "workflow_run",
            "workflow_dispatch",
            "schedule",
        }
    ):
        raise ProbeError("Operation does not match an allowed trusted event.")
    if event == "workflow_run" and not re.fullmatch(
        r"[1-9][0-9]*", os.environ.get("EXPECTED_RUN_ID", "")
    ):
        raise ProbeError("Cleanup requires the exact triggering workflow run.")


def mask_subject() -> None:
    owner_id = os.environ.get("GITHUB_REPOSITORY_OWNER_ID", "")
    repo_id = os.environ.get("GITHUB_REPOSITORY_ID", "")
    if owner_id.isdecimal() and repo_id.isdecimal():
        owner, repository = REPOSITORY.split("/")
        print(
            f"::add-mask::repo:{owner}@{owner_id}/{repository}@{repo_id}"
            ":environment:azure-e2e-fallback"
        )


def validate_scope() -> None:
    account = az("account", "show")
    if (
        not isinstance(account, dict)
        or account.get("id") != FALLBACK_TARGET.subscription
        or account.get("tenantId") != FALLBACK_TARGET.tenant
        or not isinstance(account.get("user"), dict)
        or account["user"].get("type") != "servicePrincipal"
        or account["user"].get("name") != FALLBACK_TARGET.client
    ):
        raise ProbeError("Disk-probe login principal or target does not match.")
    group = az("group", "show", "--name", GROUP)
    if (
        not isinstance(group, dict)
        or str(group.get("id", "")).lower() != group_id().lower()
        or group.get("name") != GROUP
        or group.get("tags") != FALLBACK_TARGET.group_tags
    ):
        raise ProbeError("Persistent demo group identity/ownership does not match.")


def group_id() -> str:
    return f"/subscriptions/{FALLBACK_TARGET.subscription}/resourceGroups/{GROUP}"


def fixed_tags() -> dict:
    tags = FALLBACK_TARGET.group_tags
    tags["releaseRunId"] = tags.pop("runId")
    return {**tags, "purpose": "billable-disk-cleanup-probe", "repository": REPOSITORY}


def disk() -> dict | None:
    records = az("disk", "list", "--resource-group", GROUP)
    if not isinstance(records, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not item["name"]
        for item in records
    ):
        raise ProbeError("Disk inventory is malformed.")
    matches = [
        item
        for item in records
        if isinstance(item, dict) and str(item.get("name", "")).lower() == DISK.lower()
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ProbeError("Fixed disk identity is ambiguous; preserving resources.")
    result = matches[0]
    tags = result.get("tags")
    if (
        str(result.get("id", "")).lower()
        != f"{group_id()}/providers/Microsoft.Compute/disks/{DISK}".lower()
        or result.get("name") != DISK
        or str(result.get("type", "")).lower() != "microsoft.compute/disks"
        or str(result.get("location", "")).lower() != REGION
        or type(result.get("diskSizeGB")) is not int
        or result["diskSizeGB"] != 4
        or not isinstance(result.get("sku"), dict)
        or result.get("sku", {}).get("name") != "Standard_LRS"
        or result.get("managedBy") is not None
        or result.get("diskState") != "Unattached"
        or not isinstance(result.get("creationData"), dict)
        or result.get("creationData", {}).get("createOption") != "Empty"
        or result.get("networkAccessPolicy") != "DenyAll"
        or result.get("publicNetworkAccess") != "Disabled"
        or not isinstance(tags, dict)
        or set(tags) != {*fixed_tags(), "runId", "runAttempt", "sourceSha", "expiresAt"}
        or any(tags.get(key) != value for key, value in fixed_tags().items())
        or not re.fullmatch(r"[1-9][0-9]*", str(tags.get("runId", "")))
        or not re.fullmatch(r"[1-9][0-9]*", str(tags.get("runAttempt", "")))
        or not re.fullmatch(r"[0-9a-f]{40}", str(tags.get("sourceSha", "")))
    ):
        raise ProbeError(
            "Fixed disk scope, shape or ownership mismatch; preserving it."
        )
    try:
        datetime.strptime(tags["expiresAt"], "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        raise ProbeError("Fixed disk expiry tag is malformed; preserving it.") from None
    return result


def create() -> None:
    validate_config("create")
    run = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    sha = os.environ.get("GITHUB_SHA", "")
    if (
        not re.fullmatch(r"[1-9][0-9]*", run)
        or not re.fullmatch(r"[1-9][0-9]*", attempt)
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
    ):
        raise ProbeError("Invalid trusted disk-probe run identity.")
    quote()
    validate_scope()
    if disk() is not None:
        raise ProbeError("Fixed disk exists; independent cleanup must finish first.")
    tags = {
        **fixed_tags(),
        "runId": run,
        "runAttempt": attempt,
        "sourceSha": sha,
        "expiresAt": (datetime.now(UTC) + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    az(
        "disk",
        "create",
        "--resource-group",
        GROUP,
        "--name",
        DISK,
        "--location",
        REGION,
        "--size-gb",
        "4",
        "--sku",
        "Standard_LRS",
        "--network-access-policy",
        "DenyAll",
        "--public-network-access",
        "Disabled",
        "--tags",
        *(f"{key}={value}" for key, value in tags.items()),
    )
    result = disk()
    if result is None or result["tags"] != tags:
        raise ProbeError(
            "Created disk did not verify; independent cleanup is required."
        )
    print("Fixed owned 4 GiB unattached disk verified; no VM or network was created.")


def cleanup() -> None:
    validate_config("cleanup")
    validate_scope()
    result = disk()
    if result is None:
        print("Verified: fixed disk is absent; persistent demo group is preserved.")
        return
    tags = result["tags"]
    expected = os.environ.get("EXPECTED_RUN_ID", "")
    if expected and tags["runId"] != expected:
        raise ProbeError("Fixed disk belongs to another run; preserving it.")
    run = command(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/actions/runs/{tags['runId']}/attempts/{tags['runAttempt']}",
        ]
    )
    if (
        not isinstance(run, dict)
        or not isinstance(run.get("repository"), dict)
        or not isinstance(run.get("head_repository"), dict)
        or run.get("repository", {}).get("full_name") != REPOSITORY
        or run.get("head_repository", {}).get("full_name") != REPOSITORY
        or run.get("path") not in {CREATE_WORKFLOW, f"{CREATE_WORKFLOW}@main"}
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or run.get("head_sha") != tags["sourceSha"]
        or str(run.get("run_attempt")) != tags["runAttempt"]
        or run.get("status") != "completed"
    ):
        raise ProbeError(
            "Owning run is not a completed trusted probe; preserving disk."
        )
    az("disk", "delete", "--resource-group", GROUP, "--name", DISK, "--yes")
    if disk() is not None:
        raise ProbeError("Fixed disk deletion did not verify.")
    validate_scope()
    print("Verified: exact owned billable disk deleted; demo group/tags preserved.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("create", "cleanup", "validate-create", "validate-cleanup", "quote"),
    )
    operation = parser.parse_args().operation
    try:
        if operation == "quote":
            quote()
        elif operation.startswith("validate-"):
            validate_config(operation.removeprefix("validate-"))
            mask_subject()
            print(
                "Fixed protected disk-probe configuration verified; no Azure commands."
            )
        elif operation == "create":
            create()
        else:
            cleanup()
    except ProbeError as exc:
        raise SystemExit(f"Disk probe refused or failed: {exc}") from None


if __name__ == "__main__":
    main()
