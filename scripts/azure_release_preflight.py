"""Fixed read-only fallback inspection; never a deployment or VM validator."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter
from datetime import UTC, datetime
from fnmatch import fnmatchcase

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
INFRASTRUCTURE_GROUP = "rg-llmserving-e2e-aca-infra"
SSO_CLIENT = "962740a1-be3e-454f-87c3-537ed1f02b78"
SUBSCRIPTION_SCOPE = f"/subscriptions/{FALLBACK_TARGET.subscription}"
PERMISSION_SCOPES = {
    alias: f"{SUBSCRIPTION_SCOPE}/resourceGroups/{name}"
    for alias, name in {**GROUPS, "acaInfrastructure": INFRASTRUCTURE_GROUP}.items()
}
PERMISSION_URLS = {
    alias: f"https://management.azure.com{scope}/providers/Microsoft.Authorization/permissions?api-version=2022-04-01"
    for alias, scope in PERMISSION_SCOPES.items()
}
APP_URL = (
    f"https://graph.microsoft.com/v1.0/applications(appId='{SSO_CLIENT}')?"
    "$select=appId,signInAudience,web,passwordCredentials,requiredResourceAccess"
)
PROVIDERS = (
    "Microsoft.App",
    "Microsoft.Compute",
    "Microsoft.Network",
    "Microsoft.Storage",
    "Microsoft.KeyVault",
    "Microsoft.DBforPostgreSQL",
    "Microsoft.OperationalInsights",
    "Microsoft.ManagedIdentity",
    "Microsoft.Web",
    "Microsoft.Insights",
    "Microsoft.ContainerRegistry",
)


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
        ("provider", "show"),
    }
    if arguments[:2] == ("rest", "--method"):
        if (
            len(arguments) != 5
            or arguments[2:4] != ("GET", "--url")
            or arguments[4] not in {*PERMISSION_URLS.values(), APP_URL}
        ):
            raise PreflightError("REST read is outside the fixed GET URL allowlist.")
    elif arguments[:2] not in allowed:
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
        and isinstance(item.get("locations"), list)
        and any(
            isinstance(location, str) and location.casefold() == REGION.casefold()
            for location in item["locations"]
        )
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


def quota_count(value: object) -> int:
    if type(value) is int and value >= 0:
        return value
    if (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and len(value) <= 20
    ):
        return int(value)
    raise PreflightError(
        "Quota count must be a nonnegative integer or ASCII decimal string."
    )


def validate_account() -> None:
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


def permission_summary(payload: object) -> dict:
    fields = ("actions", "notActions", "dataActions", "notDataActions")
    if (
        not isinstance(payload, dict)
        or payload.get("nextLink")
        or not isinstance(payload.get("value"), list)
        or any(
            not isinstance(entry, dict)
            or any(
                not isinstance(entry.get(field), list)
                or any(not isinstance(value, str) for value in entry[field])
                for field in fields
            )
            for entry in payload["value"]
        )
    ):
        raise PreflightError("Caller permission-rule metadata is malformed/incomplete.")

    def permits(action: str, data: bool = False) -> bool:
        allow, exclude = (
            ("dataActions", "notDataActions") if data else ("actions", "notActions")
        )
        return any(
            any(fnmatchcase(action.lower(), rule.lower()) for rule in entry[allow])
            and not any(
                fnmatchcase(action.lower(), rule.lower()) for rule in entry[exclude]
            )
            for entry in payload["value"]
        )

    return {
        "permissionRuleCount": len(payload["value"]),
        "reportedAllowRules": {
            "resourceGroupWrite": permits(
                "Microsoft.Resources/subscriptions/resourceGroups/write"
            ),
            "containerAppEnvironmentWrite": permits(
                "Microsoft.App/managedEnvironments/write"
            ),
            "roleAssignmentWrite": permits(
                "Microsoft.Authorization/roleAssignments/write"
            ),
            "stateBlobWrite": permits(
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
                True,
            ),
        },
        "denyAssignmentsVerified": False,
        "platformCreateDeleteBehaviorVerified": False,
    }


def app_summary(payload: object) -> dict:
    if (
        not isinstance(payload, dict)
        or payload.get("appId") != SSO_CLIENT
        or not isinstance(payload.get("web"), dict)
        or not isinstance(payload["web"].get("redirectUris"), list)
        or any(not isinstance(uri, str) for uri in payload["web"]["redirectUris"])
        or not isinstance(payload.get("passwordCredentials"), list)
        or not isinstance(payload.get("requiredResourceAccess"), list)
        or payload.get("signInAudience")
        not in {
            "AzureADMyOrg",
            "AzureADMultipleOrgs",
            "AzureADandPersonalMicrosoftAccount",
            "PersonalMicrosoftAccount",
        }
    ):
        raise PreflightError("Exact existing fallback test app metadata is malformed.")
    active = 0
    try:
        for credential in payload["passwordCredentials"]:
            start = datetime.fromisoformat(credential["startDateTime"])
            end = datetime.fromisoformat(credential["endDateTime"])
            if start.tzinfo is None or end.tzinfo is None or end <= start:
                raise ValueError("Invalid credential lifetime.")
            active += start <= datetime.now(UTC) < end
    except (KeyError, TypeError, ValueError):
        raise PreflightError(
            "Test app credential lifetime metadata is malformed."
        ) from None
    return {
        "exactExistingAppVerified": True,
        "signInAudience": payload["signInAudience"],
        "redirectUriCount": len(payload["web"]["redirectUris"]),
        "activePasswordCredentialCount": active,
        "requestedResourceCount": len(payload["requiredResourceAccess"]),
        "secretValueRead": False,
        "exactNewTargetCallbacksVerified": False,
        "consentAssignmentsAndBrowserTokenFlowVerified": False,
    }


def inspect_bootstrap() -> dict:
    validate_config()
    validate_account()
    report = {
        "sourceSha": os.environ.get("GITHUB_SHA"),
        "scope": "Read-only caller rules and existing fallback test app metadata",
        "permissions": {},
        "providers": {},
        "testApp": None,
        "readErrors": [],
        "deploymentReady": False,
        "resourcesOrRolesChanged": False,
        "subscriptionLevelGroupCreationVerified": False,
        "vaultCredentialAccessVerified": False,
    }
    for namespace in PROVIDERS:
        try:
            provider = read_azure(
                "provider",
                "show",
                "--namespace",
                namespace,
                "--query",
                "{namespace:namespace,registrationState:registrationState}",
            )
            if (
                not isinstance(provider, dict)
                or provider.get("namespace") != namespace
                or provider.get("registrationState")
                not in {
                    "Registered",
                    "NotRegistered",
                    "Registering",
                    "Unregistering",
                }
            ):
                raise PreflightError(
                    "Exact provider registration metadata is malformed."
                )
            report["providers"][namespace] = provider["registrationState"]
        except PreflightError as exc:
            report["readErrors"].append({"scope": namespace, "error": str(exc)})
    for alias, url in PERMISSION_URLS.items():
        try:
            report["permissions"][alias] = permission_summary(
                read_azure("rest", "--method", "GET", "--url", url)
            )
        except PreflightError as exc:
            report["readErrors"].append({"scope": alias, "error": str(exc)})
    try:
        report["testApp"] = app_summary(
            read_azure("rest", "--method", "GET", "--url", APP_URL)
        )
    except PreflightError as exc:
        report["readErrors"].append({"scope": "existingTestApp", "error": str(exc)})
    report["allReadsSucceeded"] = not report["readErrors"]
    return report


def inspect() -> dict:
    validate_config()
    validate_account()
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
    if len(quota) != len(names) or {item["name"].lower() for item in quota} != names:
        raise PreflightError("Required quota rows are missing, ambiguous or malformed.")
    for item in quota:
        for field in ("current", "limit"):
            item[field] = quota_count(item[field])
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
    parser.add_argument(
        "operation", choices=("validate-config", "inspect", "inspect-bootstrap")
    )
    operation = parser.parse_args().operation
    try:
        if operation == "validate-config":
            validate_config()
            print("Fixed protected read-only target verified.")
        elif operation == "inspect-bootstrap":
            report = inspect_bootstrap()
            print(json.dumps(report, indent=2))
            if not report["allReadsSucceeded"]:
                raise PreflightError(
                    "Bootstrap inspection has explicit unread/unverified scopes; no permission expansion attempted."
                )
        else:
            print(json.dumps(inspect(), indent=2))
    except PreflightError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
