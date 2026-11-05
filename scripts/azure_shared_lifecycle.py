"""Fixed, explicitly armed shared-stack lifecycle; never a general Azure deployer."""

from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import validate_shared_plan as scope
from azure_disk_probe import mask_subject
from azure_release_import import (
    FALLBACK_TARGET,
    GROUP,
    REGION,
    ReleaseImportError,
    az,
    command,
)
from azure_retained_platform import preserve_storage_topic
from validate_retained_group_plan import PlanRejected

REPOSITORY = "ribumann/llmserving"
CREATE_WORKFLOW = ".github/workflows/azure-fallback-shared.yml"
CLEANUP_WORKFLOW = ".github/workflows/azure-fallback-shared-cleanup.yml"
ACCOUNT = "llmreleasestate0ea5e6"
CONTAINER = "tfstate"
STATE_KEY = "shared.tfstate"
OWNER_KEY = "shared-owner.json"
ACCOUNT_ID = f"{scope.ROOT}/providers/Microsoft.Storage/storageAccounts/{ACCOUNT}"
STATE_ENDPOINT_ID = (
    f"{scope.ROOT}/providers/Microsoft.Network/privateEndpoints/llmrelease-state-pe"
)
STATE_SUBNET_ID = scope.RESOURCES["azurerm_subnet.private_endpoints"]["id"]
SOURCE_FILES = {"main.tf", "variables.tf", "providers.tf", "outputs.tf"}
OWNER_FIELDS = {
    "schemaVersion",
    "repository",
    "runId",
    "runAttempt",
    "sourceSha",
    "expiresAt",
    "status",
}


class SharedError(RuntimeError):
    pass


def utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise SharedError("Missing UTC owner timestamp.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise SharedError("Malformed UTC owner timestamp.") from None
    if parsed.utcoffset() != timedelta(0):
        raise SharedError("Owner timestamps must use UTC.")
    return parsed


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def owner_tags(owner: dict) -> dict[str, str]:
    return {
        "releaseOwnerRunId": owner["runId"],
        "releaseOwnerRunAttempt": owner["runAttempt"],
        "releaseOwnerSourceSha": owner["sourceSha"],
        "releaseCleanupAfter": owner["expiresAt"],
    }


def validate_owner(owner: object, *, now: datetime | None = None) -> dict:
    if (
        not isinstance(owner, dict)
        or set(owner) != OWNER_FIELDS
        or type(owner.get("schemaVersion")) is not int
        or owner["schemaVersion"] != 1
        or owner.get("repository") != REPOSITORY
        or not isinstance(owner.get("status"), str)
        or owner["status"] not in {"active", "cleaned"}
        or not isinstance(owner.get("sourceSha"), str)
        or not re.fullmatch(r"[0-9a-f]{40}", owner["sourceSha"])
        or any(
            not isinstance(owner.get(key), str)
            or not re.fullmatch(r"[1-9][0-9]*", owner[key])
            for key in ("runId", "runAttempt")
        )
    ):
        raise SharedError("Malformed fixed shared owner record.")
    expires = utc(owner["expiresAt"])
    run = command(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/actions/runs/{owner['runId']}/attempts/{owner['runAttempt']}",
        ]
    )
    if (
        not isinstance(run, dict)
        or str(run.get("id")) != owner["runId"]
        or str(run.get("run_attempt")) != owner["runAttempt"]
        or run.get("head_sha") != owner["sourceSha"]
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or not isinstance(run.get("path"), str)
        or run["path"] not in {CREATE_WORKFLOW, f"{CREATE_WORKFLOW}@main"}
        or not isinstance(run.get("repository"), dict)
        or run["repository"].get("full_name") != REPOSITORY
        or not isinstance(run.get("head_repository"), dict)
        or run["head_repository"].get("full_name") != REPOSITORY
        or expires != utc(run.get("created_at")) + timedelta(hours=4)
    ):
        raise SharedError(
            "Shared ownership is not bound to its exact trusted run attempt."
        )
    current = now or datetime.now(UTC)
    if utc(run["created_at"]) > current + timedelta(minutes=5):
        raise SharedError("Owning run timestamp is unexpectedly in the future.")
    return run


def new_owner() -> dict:
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if any(not re.fullmatch(r"[1-9][0-9]*", value) for value in (run_id, attempt)):
        raise SharedError("Invalid creating run attempt.")
    run = command(
        ["gh", "api", f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}"]
    )
    if not isinstance(run, dict):
        raise SharedError("Malformed creating run.")
    owner = {
        "schemaVersion": 1,
        "repository": REPOSITORY,
        "runId": run_id,
        "runAttempt": attempt,
        "sourceSha": os.environ.get("GITHUB_SHA", ""),
        "expiresAt": timestamp(utc(run.get("created_at")) + timedelta(hours=4)),
        "status": "active",
    }
    checked = validate_owner(owner)
    if checked.get("status") != "in_progress" or utc(
        owner["expiresAt"]
    ) <= datetime.now(UTC):
        raise SharedError(
            "The creating run is not active within its bounded creation window."
        )
    return owner


def validate_environment(*, cleanup: bool) -> None:
    path = CLEANUP_WORKFLOW if cleanup else CREATE_WORKFLOW
    expected = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{path}@refs/heads/main",
        "AZURE_SUBSCRIPTION_ID": FALLBACK_TARGET.subscription,
        "AZURE_TENANT_ID": FALLBACK_TARGET.tenant,
        "AZURE_CLIENT_ID": FALLBACK_TARGET.client,
        "STATE_DATA_ACCESS_APPROVED": "true",
        "SHARED_CLEANUP_ARMED": "true",
        "PRIVATE_STATE_EXECUTOR_READY": "true",
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise SharedError(
            "Fixed protected shared configuration/access/cleanup authorization is not armed."
        )
    allowed = (
        {"workflow_dispatch", "workflow_run", "schedule"}
        if cleanup
        else {"workflow_dispatch"}
    )
    if os.environ.get("GITHUB_EVENT_NAME") not in allowed:
        raise SharedError("Unsupported shared lifecycle event.")
    if cleanup and os.environ.get("GITHUB_EVENT_NAME") == "workflow_run":
        trigger_run()
    if not cleanup and os.environ.get("SHARED_CREATION_ENABLED") != "true":
        raise SharedError("Shared provisioning is disabled.")
    if any(
        os.environ.get(key)
        for key in (
            "AZURE_STORAGE_CONNECTION_STRING",
            "AZURE_STORAGE_KEY",
            "AZURE_STORAGE_SAS_TOKEN",
            "ARM_ACCESS_KEY",
            "ARM_SAS_TOKEN",
        )
    ):
        raise SharedError("Storage keys/SAS/connection-string fallback is forbidden.")


def private_json(path: Path, value: object) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def stage_module(destination: Path, owner: dict) -> str:
    source = Path(__file__).resolve().parents[1] / "infra/shared"
    if {path.name for path in source.glob("*.tf")} != SOURCE_FILES or list(
        source.glob("*.tf.json")
    ):
        raise SharedError(
            "Unexpected shared module files require a reviewed lifecycle update."
        )
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    digest = hashlib.sha256()
    for name in sorted(SOURCE_FILES):
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise SharedError("Shared source must contain only regular reviewed files.")
        data = path.read_bytes()
        digest.update(name.encode() + b"\0" + data)
        fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    private_json(
        destination / "release_override.tf.json",
        {
            "terraform": {
                "required_providers": {
                    "azurerm": {"source": "hashicorp/azurerm", "version": "= 3.117.1"},
                },
                "backend": {
                    "azurerm": {
                        "resource_group_name": GROUP,
                        "storage_account_name": ACCOUNT,
                        "container_name": CONTAINER,
                        "key": STATE_KEY,
                        "subscription_id": FALLBACK_TARGET.subscription,
                        "tenant_id": FALLBACK_TARGET.tenant,
                        "client_id": FALLBACK_TARGET.client,
                        "use_azuread_auth": True,
                        "use_oidc": True,
                        "use_cli": False,
                        "use_msi": False,
                    }
                },
            },
            "provider": {
                "azurerm": {
                    "features": {
                        "key_vault": {
                            "purge_soft_delete_on_destroy": False,
                            "recover_soft_deleted_key_vaults": False,
                        }
                    }
                }
            },
        },
    )
    private_json(
        destination / "release.auto.tfvars.json",
        {
            "subscription_id": FALLBACK_TARGET.subscription,
            "location": REGION,
            "stage": "release",
            "name_prefix": "llmrelease",
            "existing_resource_group_name": GROUP,
            "tags": {**FALLBACK_TARGET.group_tags, **owner_tags(owner)},
            "key_vault_allowed_ip_ranges": [],
        },
    )
    return digest.hexdigest()


def validate_owned_plan(
    plan: object, group: str, *, operation: str, owner: dict
) -> None:
    if not isinstance(plan, dict):
        raise PlanRejected("Malformed owned shared native plan.")
    normalized = copy.deepcopy(plan)
    required = owner_tags(owner)

    def remove_owned_tags(tags: object) -> None:
        if not isinstance(tags, dict) or any(
            tags.get(key) != value for key, value in required.items()
        ):
            raise PlanRejected(
                "Shared native tags are not owned by the exact run attempt."
            )
        for key in required:
            del tags[key]

    variables = normalized.get("variables")
    if not isinstance(variables, dict) or not isinstance(variables.get("tags"), dict):
        raise PlanRejected("Missing owned shared tags variable.")
    remove_owned_tags(variables["tags"].get("value"))
    modules = []
    planned = normalized.get("planned_values")
    if isinstance(planned, dict) and isinstance(planned.get("root_module"), dict):
        modules.append(planned["root_module"])
    prior = normalized.get("prior_state")
    if (
        isinstance(prior, dict)
        and isinstance(prior.get("values"), dict)
        and isinstance(prior["values"].get("root_module"), dict)
    ):
        modules.append(prior["values"]["root_module"])
    for module in modules:
        for resource in module.get("resources", []):
            if isinstance(resource, dict) and resource.get("mode") == "managed":
                values = resource.get("values")
                if isinstance(values, dict) and "tags" in values:
                    remove_owned_tags(values["tags"])
    for resource in normalized.get("resource_changes", []):
        if isinstance(resource, dict) and resource.get("mode") == "managed":
            change = resource.get("change")
            if isinstance(change, dict):
                for field in ("before", "after"):
                    values = change.get(field)
                    if isinstance(values, dict) and "tags" in values:
                        remove_owned_tags(values["tags"])
    scope.validate_fixed_shared(
        normalized,
        group,
        operation=operation,
        allow_partial_destroy=operation == "destroy",
    )


def terraform(module: Path, arguments: list[str], log: Path) -> None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("TF_CLI_ARGS", "TF_LOG", "TF_VAR_", "ARM_"))
        and key
        not in {
            "TF_DATA_DIR",
            "TF_WORKSPACE",
            "TF_CLI_CONFIG_FILE",
            "AZURE_CLIENT_SECRET",
            "AZURE_CLIENT_CERTIFICATE_PATH",
            "AZURE_STORAGE_CONNECTION_STRING",
            "AZURE_STORAGE_KEY",
            "AZURE_STORAGE_SAS_TOKEN",
        }
    }
    environment.update(
        {
            "ARM_USE_OIDC": "true",
            "ARM_USE_AZUREAD": "true",
            "ARM_USE_CLI": "false",
            "ARM_USE_MSI": "false",
            "ARM_SUBSCRIPTION_ID": FALLBACK_TARGET.subscription,
            "ARM_TENANT_ID": FALLBACK_TARGET.tenant,
            "ARM_CLIENT_ID": FALLBACK_TARGET.client,
            "TF_IN_AUTOMATION": "true",
            "TF_INPUT": "0",
        }
    )
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        try:
            result = subprocess.run(
                ["terraform", *arguments],
                cwd=module,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=1800,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SharedError(
                f"Terraform execution failed ({type(exc).__name__}); inspect private log."
            ) from None
        if result.returncode:
            raise SharedError(
                f"Terraform {arguments[0]} failed (exit {result.returncode}); "
                "raw diagnostics remain private. Inspect Azure Activity Log and retained "
                "backend/owner state; no auth fallback or force-unlock is attempted."
            )


def arm(resource_id: str, api: str) -> dict:
    value = az(
        "rest",
        "--method",
        "GET",
        "--url",
        f"https://management.azure.com{resource_id}?api-version={api}",
    )
    if not isinstance(value, dict) or not scope.equal(value.get("id"), resource_id):
        raise SharedError(
            "Fixed ARM metadata is malformed or outside the approved resource."
        )
    return value


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
        raise SharedError("Shared lifecycle caller is not the fixed protected UAMI.")
    for group in (GROUP, "rg-llmserving-e2e-control", "rg-llmserving-e2e-demo"):
        value = az("group", "show", "--name", group)
        expected = (
            f"/subscriptions/{FALLBACK_TARGET.subscription}/resourceGroups/{group}"
        )
        if (
            not isinstance(value, dict)
            or not scope.equal(value.get("id"), expected)
            or value.get("name") != group
            or value.get("tags") != FALLBACK_TARGET.group_tags
        ):
            raise SharedError(
                "A retained group identity/tag set differs; never adopt or change it."
            )
    storage = arm(ACCOUNT_ID, "2023-05-01")
    properties = storage.get("properties")
    if (
        storage.get("name") != ACCOUNT
        or storage.get("location") != REGION
        or storage.get("kind") != "StorageV2"
        or not isinstance(storage.get("sku"), dict)
        or storage["sku"].get("name") != "Standard_LRS"
        or storage.get("tags") != FALLBACK_TARGET.group_tags
        or not isinstance(properties, dict)
        or properties.get("provisioningState") != "Succeeded"
        or properties.get("allowSharedKeyAccess") is not False
        or properties.get("allowBlobPublicAccess") is not False
        or properties.get("supportsHttpsTrafficOnly") is not True
        or properties.get("defaultToOAuthAuthentication") is not True
        or properties.get("minimumTlsVersion") != "TLS1_2"
        or properties.get("publicNetworkAccess") != "Disabled"
    ):
        raise SharedError(
            "Existing retained state account is absent, foreign or not keyless/private."
        )
    blobs = arm(f"{ACCOUNT_ID}/blobServices/default", "2023-05-01")
    settings = blobs.get("properties")
    if (
        not isinstance(settings, dict)
        or settings.get("isVersioningEnabled") is not True
    ):
        raise SharedError("State blob version recovery is not enabled.")
    for key in ("deleteRetentionPolicy", "containerDeleteRetentionPolicy"):
        recovery = settings.get(key)
        if (
            not isinstance(recovery, dict)
            or recovery.get("enabled") is not True
            or type(recovery.get("days")) is not int
            or recovery["days"] != 7
        ):
            raise SharedError(
                "State recovery must retain the reviewed seven-day policy."
            )
    container = arm(
        f"{ACCOUNT_ID}/blobServices/default/containers/{CONTAINER}", "2023-05-01"
    )
    if (
        not isinstance(container.get("properties"), dict)
        or container["properties"].get("publicAccess") != "None"
    ):
        raise SharedError("The fixed state container is not private.")
    validate_private_state_route(properties)


def validate_private_state_route(properties: dict) -> None:
    connections = properties.get("privateEndpointConnections")
    if not isinstance(connections, list):
        raise SharedError("State account has no verified private endpoint connection.")
    approved = []
    for connection in connections:
        details = connection.get("properties") if isinstance(connection, dict) else None
        if not isinstance(details, dict):
            raise SharedError("Malformed storage private endpoint connection.")
        endpoint = details.get("privateEndpoint")
        status = details.get("privateLinkServiceConnectionState")
        if (
            isinstance(endpoint, dict)
            and scope.equal(endpoint.get("id"), STATE_ENDPOINT_ID)
            and isinstance(status, dict)
            and status.get("status") == "Approved"
            and details.get("provisioningState") == "Succeeded"
        ):
            approved.append(connection)
    if len(approved) != 1:
        raise SharedError("The retained state blob endpoint is not uniquely approved.")
    endpoint = arm(STATE_ENDPOINT_ID, "2023-09-01")
    details = endpoint.get("properties")
    if (
        not isinstance(details, dict)
        or details.get("provisioningState") != "Succeeded"
        or not isinstance(details.get("subnet"), dict)
        or not scope.equal(details["subnet"].get("id"), STATE_SUBNET_ID)
        or details.get("manualPrivateLinkServiceConnections", []) != []
    ):
        raise SharedError("Retained state endpoint/subnet is unverified.")
    links = details.get("privateLinkServiceConnections")
    if not isinstance(links, list) or len(links) != 1:
        raise SharedError(
            "Retained state endpoint must select only the blob subresource."
        )
    link = links[0].get("properties") if isinstance(links[0], dict) else None
    if (
        not isinstance(link, dict)
        or not scope.equal(link.get("privateLinkServiceId"), ACCOUNT_ID)
        or link.get("groupIds") != ["blob"]
        or not isinstance(link.get("privateLinkServiceConnectionState"), dict)
        or link["privateLinkServiceConnectionState"].get("status") != "Approved"
    ):
        raise SharedError(
            "Retained state endpoint is not the fixed approved blob target."
        )
    configurations = details.get("customDnsConfigs")
    hostname = f"{ACCOUNT}.blob.core.windows.net"
    if not isinstance(configurations, list):
        raise SharedError("Retained blob endpoint IP metadata is unverified.")
    expected = set()
    networks = [
        ipaddress.ip_network(value)
        for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    ]
    for configuration in configurations:
        if not isinstance(configuration, dict) or configuration.get("fqdn") != hostname:
            raise SharedError("Unexpected retained state endpoint DNS target.")
        addresses = configuration.get("ipAddresses")
        if not isinstance(addresses, list) or not addresses:
            raise SharedError("Missing retained state endpoint private IP.")
        for value in addresses:
            address = ipaddress.ip_address(value)
            if not any(address in network for network in networks):
                raise SharedError("State endpoint must use an RFC1918 address.")
            expected.add(str(address))
    try:
        resolved = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError:
        raise SharedError(
            "Private executor cannot resolve the fixed state blob endpoint."
        ) from None
    if not expected or resolved != expected:
        raise SharedError(
            "Private executor DNS does not resolve exclusively to the verified state endpoint."
        )


def dependencies_absent() -> None:
    for group in ("rg-llmserving-e2e-control", "rg-llmserving-e2e-demo"):
        resources = az("resource", "list", "--resource-group", group)
        if not isinstance(resources, list) or resources:
            raise SharedError(
                "Control/demo dependencies are present or unverified; refuse shared deletion."
            )


def blob(operation: str, key: str, *arguments: str, decode: bool = True) -> object:
    if operation not in {"exists", "show", "download", "upload"} or key not in {
        OWNER_KEY,
        STATE_KEY,
    }:
        raise SharedError(
            "Unsupported state operation/key; never delete state or use other storage."
        )
    if key == STATE_KEY and operation != "exists":
        raise SharedError("Terraform alone owns the state protocol and locking.")
    return az(
        "storage",
        "blob",
        operation,
        "--account-name",
        ACCOUNT,
        "--container-name",
        CONTAINER,
        "--name",
        key,
        "--auth-mode",
        "login",
        *arguments,
        decode=decode,
    )


def blob_exists(key: str) -> bool:
    value = blob("exists", key)
    if not isinstance(value, dict) or type(value.get("exists")) is not bool:
        raise SharedError(
            "Blob existence is unverified; never infer empty state from denial."
        )
    return value["exists"]


def read_owner(directory: Path) -> tuple[dict, str] | None:
    if not blob_exists(OWNER_KEY):
        return None
    properties = blob("show", OWNER_KEY)
    if not isinstance(properties, dict) or not isinstance(
        properties.get("properties"), dict
    ):
        raise SharedError("Owner blob metadata is malformed.")
    etag = properties["properties"].get("etag")
    size = properties["properties"].get("contentLength")
    if type(size) is not int or not 1 <= size <= 8192:
        raise SharedError("Owner record is not bounded metadata.")
    if (
        not isinstance(etag, str)
        or not etag
        or len(etag) > 256
        or "\r" in etag
        or "\n" in etag
    ):
        raise SharedError("Owner blob ETag cannot be used safely.")
    path = directory / "downloaded-owner.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    blob(
        "download",
        OWNER_KEY,
        "--file",
        str(path),
        "--if-match",
        etag,
        "--overwrite",
        "true",
        decode=False,
    )
    if path.stat().st_size > 8192:
        raise SharedError("Owner record exceeds its bounded metadata size.")
    owner = json.loads(path.read_text())
    validate_owner(owner)
    return owner, etag


def write_owner(directory: Path, owner: dict, *, etag: str | None) -> None:
    path = directory / "upload-owner.json"
    private_json(path, owner)
    if etag is None:
        condition = ["--overwrite", "false", "--if-none-match", "*"]
    else:
        condition = ["--overwrite", "true", "--if-match", etag]
    blob(
        "upload",
        OWNER_KEY,
        "--file",
        str(path),
        "--content-type",
        "application/json",
        *condition,
        decode=False,
    )


def trigger_run() -> dict:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    run = event.get("workflow_run") if isinstance(event, dict) else None
    if (
        not isinstance(run, dict)
        or type(run.get("id")) is not int
        or run["id"] <= 0
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] <= 0
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("path") not in (CREATE_WORKFLOW, f"{CREATE_WORKFLOW}@main")
        or not isinstance(run.get("head_repository"), dict)
        or run["head_repository"].get("full_name") != REPOSITORY
        or run.get("status") != "completed"
    ):
        raise SharedError(
            "Completion cleanup requires the exact trusted main/manual source."
        )
    return run


def inventory(owner: dict | None, *, bridge: bool = False) -> dict[str, dict]:
    if bridge and owner is not None:
        raise SharedError("Local bridge cannot use remote campaign ownership.")
    resources = az("resource", "list", "--resource-group", GROUP)
    if not isinstance(resources, list):
        raise SharedError("Shared inventory is unverified.")
    known = {
        value["id"].casefold(): address for address, value in scope.RESOURCES.items()
    }
    records = {}
    generated = []
    for resource in resources:
        if not isinstance(resource, dict) or not isinstance(resource.get("id"), str):
            raise SharedError("Malformed ARM inventory entry.")
        identifier = resource["id"]
        if scope.equal(identifier, ACCOUNT_ID):
            continue
        address = known.get(identifier.casefold())
        if address is None:
            generated.append(resource)
            continue
        if address in records:
            raise SharedError("Duplicate fixed shared ARM resource.")
        records[address] = resource
    if owner is None and not bridge:
        if records or generated:
            raise SharedError(
                "Initial shared inventory is not empty except retained bootstrap storage."
            )
        return records
    expected_tags = scope.TAGS if bridge else {**scope.TAGS, **owner_tags(owner)}

    def check(address: str, resource: dict) -> None:
        expected = scope.RESOURCES[address]
        if (
            not scope.equal(resource.get("id"), expected["id"])
            or "tags" in expected
            and resource.get("tags") != expected_tags
        ):
            raise SharedError(
                "Live shared resource is not owned by the exact run cohort."
            )

    for address, resource in records.items():
        check(address, resource)
        if (
            address.startswith("azurerm_subnet.")
            and "azurerm_virtual_network.shared" not in records
        ):
            raise SharedError(
                "An untagged subnet lacks its live cohort-owned VNet parent."
            )
    vnet = records.get("azurerm_virtual_network.shared")
    if vnet is not None:
        metadata = arm(
            scope.RESOURCES["azurerm_virtual_network.shared"]["id"], "2023-09-01"
        )
        properties = metadata.get("properties")
        subnets = properties.get("subnets") if isinstance(properties, dict) else None
        if not isinstance(subnets, list):
            raise SharedError("Owned VNet child subnet inventory is unverified.")
        for subnet in subnets:
            if not isinstance(subnet, dict) or not isinstance(subnet.get("id"), str):
                raise SharedError("Malformed owned VNet subnet.")
            address = known.get(subnet["id"].casefold())
            if address is None or not address.startswith("azurerm_subnet."):
                raise SharedError(
                    "Foreign subnet in the owned VNet; refuse cascade deletion."
                )
            check(address, subnet)
            records[address] = subnet
    for label in ("postgres", "vault", "blob", "queue", "table"):
        address = f"azurerm_private_dns_zone.{label}"
        if address not in records:
            continue
        zone = scope.RESOURCES[address]["id"]
        links = az(
            "rest",
            "--method",
            "GET",
            "--url",
            f"https://management.azure.com{zone}/virtualNetworkLinks?api-version=2020-06-01",
        )
        if (
            not isinstance(links, dict)
            or not isinstance(links.get("value"), list)
            or links.get("nextLink")
        ):
            raise SharedError("Private DNS link inventory is incomplete.")
        for link in links["value"]:
            address = f"azurerm_private_dns_zone_virtual_network_link.{label}"
            if not isinstance(link, dict):
                raise SharedError("Malformed private DNS link.")
            check(address, link)
            records[address] = link
    endpoint = scope.RESOURCES["azurerm_private_endpoint.vault"]["id"]
    for resource in generated:
        if preserve_storage_topic(resource):
            continue
        identifier = resource["id"]
        prefix = f"{scope.ROOT}/providers/Microsoft.Network/networkInterfaces/"
        if (
            identifier.casefold().startswith(prefix.casefold())
            and "/" not in identifier[len(prefix) :]
            and "azurerm_private_endpoint.vault" in records
        ):
            nic = arm(identifier, "2023-09-01")
            properties = nic.get("properties")
            parent = (
                properties.get("privateEndpoint")
                if isinstance(properties, dict)
                else None
            )
            if isinstance(parent, dict) and scope.equal(parent.get("id"), endpoint):
                continue
        if (
            scope.equal(identifier, f"{endpoint}/privateDnsZoneGroups/vault-zone-group")
            and "azurerm_private_endpoint.vault" in records
        ):
            continue
        raise SharedError(
            "Unknown shared resource: never delete/adopt it, including bootstrap or roles."
        )
    return records


def state_resources(module: Path, directory: Path, label: str, owner: dict) -> set[str]:
    path = directory / f"{label}-state.json"
    terraform(module, ["show", "-json"], path)
    state = json.loads(path.read_text())
    if not isinstance(state, dict) or state.get("format_version") != "1.0":
        raise SharedError("Malformed private native state.")
    values = state.get("values", {})
    if not isinstance(values, dict):
        raise SharedError("Malformed private native state values.")
    records = scope.module_records(values.get("root_module", {}))
    found = set()
    for record in records:
        if not isinstance(record, dict):
            raise SharedError("Malformed native state resource.")
        if record.get("mode") == "data":
            scope.validate_data(record)
            continue
        address = record.get("address")
        if (
            not isinstance(address, str)
            or address not in scope.ADDRESSES
            or address in found
            or record.get("mode") != "managed"
            or record.get("type") != address.split(".")[0]
            or record.get("provider_name") != "registry.terraform.io/hashicorp/azurerm"
        ):
            raise SharedError(
                "Private state contains unexpected managed ownership/provider bindings."
            )
        normalized = copy.deepcopy(record.get("values"))
        if not isinstance(normalized, dict):
            raise SharedError("Malformed native state attributes.")
        if "tags" in normalized:
            tags = normalized["tags"]
            if not isinstance(tags, dict) or any(
                tags.get(key) != value for key, value in owner_tags(owner).items()
            ):
                raise SharedError("Private state is not owned by its exact run cohort.")
            for key in owner_tags(owner):
                del tags[key]
        scope.validate_values(
            {
                "configuration": {
                    "root_module": {
                        "resources": [
                            {
                                "address": "azurerm_private_endpoint.vault",
                                "expressions": {},
                            }
                        ]
                    }
                },
            },
            address,
            normalized,
            existing=True,
            allow_partial_destroy=True,
        )
        found.add(address)
    return found


def execute_plan(module: Path, directory: Path, *, owner: dict, operation: str) -> None:
    saved = directory / "approved.tfplan"
    arguments = [
        "plan",
        "-input=false",
        "-no-color",
        "-lock-timeout=60s",
        f"-out={saved}",
    ]
    if operation == "destroy":
        arguments.append("-destroy")
    terraform(module, arguments, directory / "plan.log")
    saved.chmod(0o600)
    shown = directory / "plan.json"
    terraform(module, ["show", "-json", str(saved)], shown)
    validate_owned_plan(
        json.loads(shown.read_text()), GROUP, operation=operation, owner=owner
    )
    dependencies_absent()
    inventory(owner if operation == "destroy" else None)
    terraform(
        module,
        ["apply", "-input=false", "-no-color", "-lock-timeout=60s", str(saved)],
        directory / "apply.log",
    )


def create(directory: Path) -> None:
    owner = new_owner()
    validate_scope()
    dependencies_absent()
    inventory(None)
    if blob_exists(OWNER_KEY) or blob_exists(STATE_KEY):
        raise SharedError(
            "One-shot campaign already has owner/state data; never overwrite, migrate or rearm."
        )
    write_owner(directory, owner, etag=None)
    persisted = read_owner(directory)
    if persisted is None or persisted[0] != owner:
        raise SharedError("Initial owner record readback differs; no provisioning.")
    module = directory / "shared"
    stage_module(module, owner)
    terraform(module, ["init", "-input=false", "-no-color"], directory / "init.log")
    if state_resources(module, directory, "initial", owner):
        raise SharedError("Initial shared provisioning requires fresh remote state.")
    execute_plan(module, directory, owner=owner, operation="create")
    if state_resources(module, directory, "created", owner) != scope.ADDRESSES:
        raise SharedError("Shared creation did not persist all 29 native addresses.")
    inventory(owner)
    print(
        "Shared native create completed; cleanup remains armed. No app/runtime/registry-import claim."
    )


def cleanup_due(owner: dict, run: dict, now: datetime) -> bool:
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_run":
        trigger = trigger_run()
        if (str(trigger["id"]), str(trigger["run_attempt"])) != (
            owner["runId"],
            owner["runAttempt"],
        ):
            return False
    if run.get("status") != "completed":
        raise SharedError(
            "Owner run is still active or unverified; never race its Azure operations."
        )
    if not isinstance(run.get("conclusion"), str) or run["conclusion"] not in {
        "success",
        "failure",
        "cancelled",
        "timed_out",
        "action_required",
        "neutral",
        "skipped",
        "stale",
        "startup_failure",
    }:
        raise SharedError("Owner completion conclusion is unverified.")
    return (
        owner["status"] == "cleaned"
        or run["conclusion"] != "success"
        or utc(owner["expiresAt"]) <= now
        or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    )


def cleanup(directory: Path) -> None:
    validate_scope()
    record = read_owner(directory)
    if record is None:
        inventory(None)
        if blob_exists(STATE_KEY):
            raise SharedError("Unowned state exists; never destroy/adopt it.")
        print("No shared campaign owner, state or active resource; nothing changed.")
        return
    owner, etag = record
    run = validate_owner(owner)
    if not cleanup_due(owner, run, datetime.now(UTC)):
        print(
            "No eligible owning attempt: success is retained only until its four-hour expiry."
        )
        return
    dependencies_absent()
    live = inventory(owner)
    module = directory / "shared"
    stage_module(module, owner)
    terraform(module, ["init", "-input=false", "-no-color"], directory / "init.log")
    tracked = state_resources(module, directory, "before", owner)
    # Recover only exact, live cohort-tagged primary resources; no arbitrary import.
    for index, address in enumerate(sorted(set(live) - tracked)):
        terraform(
            module,
            [
                "import",
                "-input=false",
                "-no-color",
                "-lock-timeout=60s",
                address,
                scope.RESOURCES[address]["id"],
            ],
            directory / f"recover-{index}.log",
        )
    tracked = state_resources(module, directory, "recovered", owner)
    if tracked:
        execute_plan(module, directory, owner=owner, operation="destroy")
    if state_resources(module, directory, "after", owner) or inventory(owner):
        raise SharedError(
            "Shared cleanup incomplete; preserve owner/state and retry independently."
        )
    if owner["status"] != "cleaned":
        write_owner(directory, {**owner, "status": "cleaned"}, etag=etag)
    print(
        "No active managed shared resources remain. Retained bootstrap/state/groups/grants and soft-deleted vault are not purged; expiry scans continue."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "validate-create",
            "validate-cleanup",
            "stage-check",
            "create",
            "cleanup",
        ),
    )
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "stage-check":
            if args.destination is None:
                raise SharedError("A fresh private destination is required.")
            stage_module(
                args.destination,
                {
                    "runId": "1",
                    "runAttempt": "1",
                    "sourceSha": "a" * 40,
                    "expiresAt": "2000-01-01T04:00:00Z",
                },
            )
            print(
                "Staged credential-free source only; no backend/data access or deployment."
            )
            return
        validate_environment(cleanup=args.operation in {"validate-cleanup", "cleanup"})
        mask_subject()
        if args.operation.startswith("validate-"):
            print("Explicit protected configuration gate passed; no Azure call.")
            return
        version = command(["terraform", "version", "-json"])
        if (
            not isinstance(version, dict)
            or version.get("terraform_version") != "1.16.6"
        ):
            raise SharedError(
                "Lifecycle requires the reviewed Terraform 1.16.6 binary."
            )
        with tempfile.TemporaryDirectory(prefix="llm-shared-") as directory:
            (cleanup if args.operation == "cleanup" else create)(Path(directory))
    except (SharedError, ReleaseImportError, PlanRejected) as exc:
        raise SystemExit(f"Shared lifecycle stopped: {exc}") from None
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(
            f"Shared lifecycle stopped: invalid private metadata/I/O ({type(exc).__name__}); no fallback."
        ) from None


if __name__ == "__main__":
    main()
