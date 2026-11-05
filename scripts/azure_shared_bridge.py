"""Operator-local shared bootstrap and independent ARM-only emergency cleanup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import azure_shared_lifecycle as shared
import validate_shared_plan as scope
import validate_shared_reconcile as reconcile
from azure_disk_probe import mask_subject
from azure_release_import import ReleaseImportError, az, command
from validate_retained_group_plan import PlanRejected, run_saved_plan

WORKFLOW = ".github/workflows/azure-fallback-shared-bridge-cleanup.yml"
ARMED = "FALLBACK_SHARED_BRIDGE_CLEANUP_ARMED"
DEADLINE = "FALLBACK_SHARED_BRIDGE_EXPIRES_AT"
PROVIDER_OVERRIDE = {
    "terraform": {
        "required_providers": {
            "azurerm": {"source": "hashicorp/azurerm", "version": "= 3.117.1"},
        }
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
}
APIS = {
    "Microsoft.Network": "2023-09-01",
    "Microsoft.PrivateDns": "2020-06-01",
    "Microsoft.ContainerRegistry": "2023-07-01",
    "Microsoft.KeyVault": "2023-07-01",
    "Microsoft.OperationalInsights": "2023-09-01",
    "Microsoft.Insights": "2020-02-02",
}
# Links/endpoint before VNet, then NAT dependencies; no group, storage or role.
DELETE_ORDER = [
    "azurerm_private_endpoint.vault",
    "azurerm_application_insights.shared",
    *[
        f"azurerm_private_dns_zone_virtual_network_link.{key}"
        for key in ("postgres", "vault", "blob", "queue", "table")
    ],
    "azurerm_virtual_network.shared",
    "azurerm_nat_gateway.shared",
    "azurerm_public_ip.nat",
    "azurerm_network_security_group.gpu",
    *[
        f"azurerm_private_dns_zone.{key}"
        for key in ("postgres", "vault", "blob", "queue", "table")
    ],
    "azurerm_container_registry.shared",
    "azurerm_key_vault.shared",
    "azurerm_log_analytics_workspace.shared",
]


def configuration(*, creating: bool = False) -> datetime:
    values = {}
    for name in (ARMED, DEADLINE):
        if os.environ.get("GITHUB_ACTIONS") == "true":
            values[name] = os.environ.get(name)
        else:
            response = command(
                ["gh", "api", f"repos/{shared.REPOSITORY}/actions/variables/{name}"]
            )
            if not isinstance(response, dict) or response.get("name") != name:
                raise shared.SharedError("Bridge cleanup configuration is unverified.")
            values[name] = response.get("value")
    if values[ARMED] != "true":
        raise shared.SharedError("Independent ARM bridge cleanup is not armed.")
    deadline = shared.utc(values[DEADLINE])
    now = datetime.now(UTC)
    if deadline > now + timedelta(hours=4) or creating and deadline <= now:
        raise shared.SharedError(
            "Bridge expiry must be within its fixed four-hour creation window."
        )
    return deadline


def identity(*, protected: bool) -> None:
    if protected:
        expected = {
            "GITHUB_REPOSITORY": shared.REPOSITORY,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW_REF": f"{shared.REPOSITORY}/{WORKFLOW}@refs/heads/main",
            "AZURE_SUBSCRIPTION_ID": shared.FALLBACK_TARGET.subscription,
            "AZURE_TENANT_ID": shared.FALLBACK_TARGET.tenant,
            "AZURE_CLIENT_ID": shared.FALLBACK_TARGET.client,
        }
        if any(os.environ.get(key) != value for key, value in expected.items()):
            raise shared.SharedError(
                "Bridge cleanup requires its fixed protected main workflow."
            )
        if os.environ.get("GITHUB_EVENT_NAME") not in {"workflow_dispatch", "schedule"}:
            raise shared.SharedError("Unsupported bridge cleanup event.")
    account = az("account", "show")
    if (
        not isinstance(account, dict)
        or account.get("id") != shared.FALLBACK_TARGET.subscription
        or account.get("tenantId") != shared.FALLBACK_TARGET.tenant
    ):
        raise shared.SharedError(
            "Bridge caller is outside the isolated main subscription/tenant."
        )
    if protected and account.get("user") != {
        "name": shared.FALLBACK_TARGET.client,
        "type": "servicePrincipal",
    }:
        raise shared.SharedError("Independent bridge cleanup requires the exact UAMI.")
    for group in (shared.GROUP, "rg-llmserving-e2e-control", "rg-llmserving-e2e-demo"):
        record = az("group", "show", "--name", group)
        identifier = f"/subscriptions/{shared.FALLBACK_TARGET.subscription}/resourceGroups/{group}"
        if (
            not isinstance(record, dict)
            or not scope.equal(record.get("id"), identifier)
            or record.get("name") != group
            or record.get("tags") != shared.FALLBACK_TARGET.group_tags
        ):
            raise shared.SharedError("Retained group ownership is unverified.")


def reject_attached_children(records: dict) -> None:
    for address, record in records.items():
        if not address.startswith("azurerm_subnet."):
            continue
        properties = record.get("properties")
        if not isinstance(properties, dict):
            raise shared.SharedError("Live subnet attachment metadata is unverified.")
        for field in (
            "ipConfigurations",
            "privateEndpoints",
            "serviceAssociationLinks",
            "resourceNavigationLinks",
        ):
            children = properties.get(field, [])
            if not isinstance(children, list):
                raise shared.SharedError("Malformed live subnet attachment metadata.")
            if field == "privateEndpoints":
                allowed = scope.RESOURCES["azurerm_private_endpoint.vault"]["id"]
                if all(
                    isinstance(item, dict) and scope.equal(item.get("id"), allowed)
                    for item in children
                ):
                    continue
            if children:
                raise shared.SharedError(
                    "Subnet has active attachments; never cascade-delete dependencies."
                )


def verify_dns_records(records: dict) -> None:
    for address in records:
        if not address.startswith("azurerm_private_dns_zone."):
            continue
        identifier = scope.RESOURCES[address]["id"]
        response = az(
            "rest",
            "--method",
            "GET",
            "--url",
            f"https://management.azure.com{identifier}/ALL?api-version=2020-06-01",
        )
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("value"), list)
            or response.get("nextLink")
        ):
            raise shared.SharedError(
                "DNS record inventory is incomplete; refuse zone cascade deletion."
            )
        soa = 0
        for record in response["value"]:
            if (
                not isinstance(record, dict)
                or not scope.equal(record.get("id"), f"{identifier}/SOA/@")
                or not isinstance(record.get("type"), str)
                or record["type"].casefold() != "microsoft.network/privatednszones/soa"
                or record.get("name") != "@"
            ):
                raise shared.SharedError(
                    "DNS zone has non-default records; remove only separately verified endpoint-owned records first."
                )
            soa += 1
        if soa != 1:
            raise shared.SharedError("DNS zone default SOA is not uniquely verified.")


def emergency_cleanup(*, force: bool) -> None:
    deadline = configuration()
    identity(protected=True)
    shared.dependencies_absent()
    records = shared.inventory(None, bridge=True)
    reject_attached_children(records)
    if datetime.now(UTC) < deadline and not force:
        print(
            "ARM cleanup gate verified; fixed deadline not reached. No resource mutation."
        )
        return
    for address in DELETE_ORDER:
        current = shared.inventory(None, bridge=True)
        reject_attached_children(current)
        if address.startswith("azurerm_private_dns_zone."):
            verify_dns_records(current)
        shared.dependencies_absent()
        if address not in current:
            continue
        identifier = scope.RESOURCES[address]["id"]
        namespace = identifier.split("/providers/")[1].split("/")[0]
        api = APIS[
            "Microsoft.PrivateDns" if "/privateDnsZones/" in identifier else namespace
        ]
        az(
            "rest",
            "--method",
            "DELETE",
            "--url",
            f"https://management.azure.com{identifier}?api-version={api}",
            decode=False,
        )
        # A pending asynchronous deletion is not absence. Stop and let a later
        # independent run resume rather than deleting its dependencies early.
        if address in shared.inventory(None, bridge=True):
            raise shared.SharedError(
                "ARM deletion remains pending; retained state is unchanged, retry independent cleanup."
            )
    if shared.inventory(None, bridge=True):
        raise shared.SharedError("Shared bridge cleanup has remaining owned resources.")
    print(
        "No active shared29 roots remain; bootstrap storage/groups/grants and soft-deleted vault preserved. Operator must reconcile private local state."
    )


def private_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise shared.SharedError(
            "Private directory must be a regular existing directory."
        )
    if os.name != "nt":
        if path.stat().st_mode & 0o077:
            raise shared.SharedError("Private directory permits group/other access.")
        return
    script = (
        "$ErrorActionPreference='Stop';"
        "$a=Get-Acl -LiteralPath $env:LLMSERVING_PRIVATE_PATH;"
        "$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
        "$allowed=@($u,'S-1-5-18','S-1-5-32-544');"
        "$bad=@($a.Access | Where-Object {"
        "$_.AccessControlType -eq 'Allow' -and "
        "$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -notin $allowed"
        "}); if($bad.Count -ne 0){exit 2}"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        timeout=30,
        env={**os.environ, "LLMSERVING_PRIVATE_PATH": str(path.resolve())},
    )
    if result.returncode:
        raise shared.SharedError(
            "Private Windows directory ACL is not limited to caller/SYSTEM/Administrators."
        )


def backup(module: Path, destination: Path, label: str) -> dict:
    private_directory(destination)
    if (
        destination.resolve() == module.resolve()
        or module.resolve() in destination.resolve().parents
    ):
        raise shared.SharedError(
            "Second backup must be an existing private directory outside the module."
        )
    checkpoint = destination / label
    # Windows 0700 synthesizes OWNER RIGHTS ACEs rather than inheriting the
    # already-verified parent ACL. Verify the inherited ACL before writing.
    checkpoint.mkdir(mode=0o777 if os.name == "nt" else 0o700, exist_ok=False)
    private_directory(checkpoint)
    metadata = {"schemaVersion": 1, "state": None, "files": {}}
    for path in sorted(module.iterdir()):
        if path.name not in {
            "terraform.tfstate",
            "terraform.tfstate.backup",
            ".terraform.lock.hcl",
        } and path.suffix not in {".tf", ".tfvars", ".json"}:
            continue
        if path.is_symlink() or not path.is_file():
            raise shared.SharedError(
                "Checkpoint source must be a regular private module file."
            )
        data = path.read_bytes()
        target = checkpoint / path.name
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        digest = hashlib.sha256(data).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise shared.SharedError(
                "Second private checkpoint hash verification failed."
            )
        metadata["files"][path.name] = digest
        if path.name == "terraform.tfstate":
            state = json.loads(data)
            if (
                not isinstance(state, dict)
                or not isinstance(state.get("lineage"), str)
                or type(state.get("serial")) is not int
            ):
                raise shared.SharedError(
                    "Canonical local state lineage/serial is malformed."
                )
            metadata["state"] = {
                "sha256": digest,
                "lineage": state["lineage"],
                "serial": state["serial"],
            }
    shared.private_json(checkpoint / "checkpoint.json", metadata)
    return metadata


def local_apply(
    plan: Path,
    log: Path,
    second_backup: Path,
    cleanup_run: str,
    *,
    recovering: bool = False,
) -> None:
    if not re.fullmatch(r"[1-9][0-9]*", cleanup_run):
        raise shared.SharedError(
            "Exact successful independent cleanup arming run is required."
        )
    configuration(creating=True)
    run = command(
        [
            "gh",
            "api",
            f"repos/{shared.REPOSITORY}/actions/runs/{cleanup_run}/attempts/1",
        ]
    )
    if (
        not isinstance(run, dict)
        or str(run.get("id")) != cleanup_run
        or run.get("run_attempt") != 1
        or run.get("path") not in {WORKFLOW, f"{WORKFLOW}@main"}
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or not isinstance(run.get("head_repository"), dict)
        or run["head_repository"].get("full_name") != shared.REPOSITORY
        or shared.utc(run.get("created_at")) < datetime.now(UTC) - timedelta(minutes=30)
    ):
        raise shared.SharedError(
            "Independent ARM cleanup arming run is not a recent trusted successful exact attempt."
        )
    identity(protected=False)
    shared.dependencies_absent()
    if recovering:
        recovery_inventory()
    else:
        shared.inventory(None)
    deleted = az("keyvault", "list-deleted", "--resource-type", "vault")
    if not isinstance(deleted, list) or any(
        not isinstance(item, dict) or item.get("name") == "llmrelease-kv-0ea5e6"
        for item in deleted
    ):
        raise shared.SharedError(
            "Deleted-vault inventory is unverified or name is retained; never auto-recover/purge it."
        )
    module = Path.cwd()
    private_directory(module)
    override = module / "release_override.tf.json"
    if (
        override.is_symlink()
        or not override.is_file()
        or json.loads(override.read_text()) != PROVIDER_OVERRIDE
    ):
        raise shared.SharedError(
            "Local bridge requires the exact reviewed no-purge/no-recovery provider override before plan generation."
        )
    if any(
        os.environ.get(key)
        for key in ("TF_DATA_DIR", "TF_WORKSPACE", "TF_CLI_CONFIG_FILE")
    ):
        raise shared.SharedError(
            "Bridge refuses redirected Terraform data/workspace/config."
        )
    workspace = module / ".terraform/environment"
    if (
        workspace.is_symlink()
        or workspace.exists()
        and workspace.read_text().strip() != "default"
    ):
        raise shared.SharedError(
            "Bridge requires the persisted default workspace before any mutation."
        )
    version = command(["terraform", "version", "-json"])
    if not isinstance(version, dict) or version.get("terraform_version") != "1.16.6":
        raise shared.SharedError("Bridge requires Terraform 1.16.6.")
    backend_path = module / ".terraform/terraform.tfstate"
    if backend_path.exists():
        backend = json.loads(backend_path.read_text())
        selected = backend.get("backend", {})
        if not isinstance(selected, dict) or selected.get("type") not in {
            None,
            "local",
        }:
            raise shared.SharedError("Bridge must not use a remote backend.")
        if selected.get("type") == "local":
            settings = selected.get("config")
            if not isinstance(settings, dict) or settings.get("path") not in {
                None,
                "",
                "terraform.tfstate",
            }:
                raise shared.SharedError(
                    "Bridge refuses redirected canonical local state."
                )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    before = backup(module, second_backup, f"{stamp}-before")
    if recovering:
        recovery_state(before["state"])
    elif before["state"] is not None:
        raise shared.SharedError(
            "Initial bridge cannot adopt/retry existing canonical state."
        )

    def gate(native: object, group: str) -> None:
        if recovering:
            recovery_state(before["state"])
            canonical = command(["terraform", "show", "-json", "terraform.tfstate"])
            reconcile.validate_reconcile(native, group, canonical)
        else:
            scope.validate_fixed_shared(native, group, operation="create")
        # Recheck the independent deadline immediately before the single apply.
        configuration(creating=True)
        if recovering:
            recovery_inventory()
        else:
            shared.inventory(None)
        shared.dependencies_absent()

    try:
        run_saved_plan(
            plan,
            shared.GROUP,
            log,
            terraform="terraform",
            apply=True,
            validator=gate,
        )
    finally:
        backup(module, second_backup, f"{stamp}-after")
    state = module / "terraform.tfstate"
    if not state.is_file():
        raise shared.SharedError(
            "Apply did not persist canonical local state; no automatic retry."
        )
    state.chmod(0o600)
    print(
        "Guarded shared29 applied; verified private checkpoints retained. No remote migration or private executor claim."
    )


def recovery_state(metadata: object) -> None:
    if metadata != {
        "sha256": reconcile.STATE_SHA256,
        "lineage": reconcile.LINEAGE,
        "serial": reconcile.SERIAL,
    }:
        raise shared.SharedError(
            "Recovery requires the exact preserved failed-apply snapshot."
        )
    state = Path.cwd() / "terraform.tfstate"
    if (
        state.is_symlink()
        or hashlib.sha256(state.read_bytes()).hexdigest() != reconcile.STATE_SHA256
    ):
        raise shared.SharedError(
            "Canonical recovery state changed; never retry automatically."
        )


def recovery_inventory() -> None:
    if configuration(creating=True) > shared.utc(reconcile.DEADLINE):
        raise shared.SharedError(
            "Recovery cannot extend the existing cleanup deadline."
        )
    feature = az(
        "feature",
        "show",
        "--namespace",
        "Microsoft.Network",
        "--name",
        "AllowBringYourOwnPublicIpAddress",
    )
    if (
        not isinstance(feature, dict)
        or feature.get("properties", {}).get("state") != "Registered"
    ):
        raise shared.SharedError("Policy-required public IP feature is not Registered.")
    present = shared.inventory(None, bridge=True)
    if set(present) != set(scope.RESOURCES) - {"azurerm_public_ip.nat"}:
        raise shared.SharedError(
            "Recovery live owned inventory differs from exact missing PIP."
        )
    reject_attached_children(present)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("local-apply", "local-reconcile", "arm-cleanup")
    )
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--private-log", type=Path)
    parser.add_argument("--second-backup", type=Path)
    parser.add_argument("--cleanup-run")
    parser.add_argument("--now", action="store_true")
    args = parser.parse_args()
    try:
        if args.operation == "arm-cleanup":
            if args.now and os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
                raise shared.SharedError(
                    "Immediate ARM cleanup requires protected manual dispatch."
                )
            mask_subject()
            emergency_cleanup(force=args.now)
        else:
            if (
                not all(
                    (args.plan, args.private_log, args.second_backup, args.cleanup_run)
                )
                or args.now
            ):
                raise shared.SharedError(
                    "Local apply needs private plan/log/backup and exact cleanup arming run."
                )
            local_apply(
                args.plan,
                args.private_log,
                args.second_backup,
                args.cleanup_run,
                recovering=args.operation == "local-reconcile",
            )
    except (shared.SharedError, PlanRejected, ReleaseImportError) as error:
        raise SystemExit(f"Shared bridge stopped: {error}") from None
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(
            f"Shared bridge stopped: private metadata/I/O invalid ({type(error).__name__}); preserve local state, no retry."
        ) from None


if __name__ == "__main__":
    main()
