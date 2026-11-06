from __future__ import annotations

from scripts.tests import operator_fixture  # noqa: F401

import copy
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import azure_shared_lifecycle as lifecycle
import test_shared_plan as shared_fixture


class SharedLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.owner = {
            "schemaVersion": 1,
            "repository": lifecycle.REPOSITORY,
            "runId": "123",
            "runAttempt": "2",
            "sourceSha": "a" * 40,
            "expiresAt": "2026-11-05T16:00:00Z",
            "status": "active",
        }
        self.run = {
            "id": 123,
            "run_attempt": 2,
            "head_sha": "a" * 40,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "path": lifecycle.CREATE_WORKFLOW,
            "repository": {"full_name": lifecycle.REPOSITORY},
            "head_repository": {"full_name": lifecycle.REPOSITORY},
            "created_at": "2026-11-05T12:00:00Z",
            "status": "completed",
            "conclusion": "success",
        }
        self.now = datetime(2026, 11, 5, 15, tzinfo=UTC)
        self.environment = {
            "GITHUB_REPOSITORY": lifecycle.REPOSITORY,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW_REF": f"{lifecycle.REPOSITORY}/{lifecycle.CREATE_WORKFLOW}@refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "AZURE_SUBSCRIPTION_ID": lifecycle.FALLBACK_TARGET.subscription,
            "AZURE_TENANT_ID": lifecycle.FALLBACK_TARGET.tenant,
            "AZURE_CLIENT_ID": lifecycle.FALLBACK_TARGET.client,
            "STATE_DATA_ACCESS_APPROVED": "true",
            "SHARED_CLEANUP_ARMED": "true",
            "SHARED_CREATION_ENABLED": "true",
            "PRIVATE_STATE_EXECUTOR_READY": "true",
        }

    def test_exact_owner_attempt_and_expiry(self):
        with patch.object(lifecycle, "command", return_value=self.run) as call:
            lifecycle.validate_owner(self.owner, now=self.now)
        self.assertIn("/123/attempts/2", call.call_args.args[0][-1])
        for field, value in (
            ("run_attempt", 1),
            ("head_branch", "feature"),
            ("event", "pull_request"),
            ("head_sha", "b" * 40),
            ("head_repository", {"full_name": "foreign/repo"}),
            ("path", ".github/workflows/other.yml"),
            ("created_at", "2026-11-05T11:00:00Z"),
        ):
            with (
                self.subTest(field=field),
                patch.object(
                    lifecycle, "command", return_value={**self.run, field: value}
                ),
                self.assertRaises(lifecycle.SharedError),
            ):
                lifecycle.validate_owner(self.owner, now=self.now)

    def test_malformed_owner_rejected_before_github(self):
        for field, value in (
            ("schemaVersion", True),
            ("status", []),
            ("sourceSha", "A" * 40),
            ("runId", "../123"),
            ("runAttempt", 2),
            ("expiresAt", None),
            ("expiresAt", "2026-11-05T16:00:00"),
            ("repository", "foreign/repo"),
        ):
            with self.subTest(field=field), patch.object(lifecycle, "command") as call:
                with self.assertRaises(lifecycle.SharedError):
                    lifecycle.validate_owner({**self.owner, field: value}, now=self.now)
                call.assert_not_called()

    def test_config_approval_and_auth_fallback_gates(self):
        with patch.dict(os.environ, self.environment, clear=True):
            lifecycle.validate_environment(cleanup=False)
        for field in self.environment:
            with (
                self.subTest(field=field),
                patch.dict(
                    os.environ, {**self.environment, field: "false"}, clear=True
                ),
                self.assertRaises(lifecycle.SharedError),
            ):
                lifecycle.validate_environment(cleanup=False)
        for key in (
            "ARM_ACCESS_KEY",
            "ARM_SAS_TOKEN",
            "AZURE_STORAGE_CONNECTION_STRING",
            "AZURE_STORAGE_KEY",
            "AZURE_STORAGE_SAS_TOKEN",
        ):
            with (
                self.subTest(key=key),
                patch.dict(
                    os.environ, {**self.environment, key: "forbidden"}, clear=True
                ),
                self.assertRaises(lifecycle.SharedError),
            ):
                lifecycle.validate_environment(cleanup=False)

    def test_cleanup_attempt_failure_cancel_expiry_manual(self):
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}, clear=True):
            self.assertFalse(lifecycle.cleanup_due(self.owner, self.run, self.now))
            self.assertTrue(
                lifecycle.cleanup_due(
                    self.owner, self.run, self.now + timedelta(hours=1)
                )
            )
            for conclusion in ("failure", "cancelled", "timed_out"):
                self.assertTrue(
                    lifecycle.cleanup_due(
                        self.owner, {**self.run, "conclusion": conclusion}, self.now
                    )
                )
            with self.assertRaises(lifecycle.SharedError):
                lifecycle.cleanup_due(
                    self.owner, {**self.run, "status": "in_progress"}, self.now
                )
        with patch.dict(
            os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch"}, clear=True
        ):
            self.assertTrue(lifecycle.cleanup_due(self.owner, self.run, self.now))
        with (
            patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_run"}, clear=True),
            patch.object(
                lifecycle, "trigger_run", return_value={**self.run, "run_attempt": 1}
            ),
        ):
            self.assertFalse(
                lifecycle.cleanup_due(
                    self.owner, {**self.run, "conclusion": "cancelled"}, self.now
                )
            )

    def test_staged_source_is_private_keyless_and_does_not_change_original(self):
        original = (
            Path(lifecycle.__file__).resolve().parents[1] / "infra/shared/providers.tf"
        ).read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "shared"
            digest = lifecycle.stage_module(destination, self.owner)
            self.assertEqual(len(digest), 64)
            override = json.loads(
                (destination / "release_override.tf.json").read_text()
            )
            backend = override["terraform"]["backend"]["azurerm"]
            self.assertEqual(backend["storage_account_name"], lifecycle.ACCOUNT)
            self.assertEqual(backend["key"], lifecycle.STATE_KEY)
            self.assertTrue(backend["use_oidc"] and backend["use_azuread_auth"])
            self.assertFalse(backend["use_cli"] or backend["use_msi"])
            self.assertEqual(
                override["provider"]["azurerm"]["features"]["key_vault"],
                {
                    "purge_soft_delete_on_destroy": False,
                    "recover_soft_deleted_key_vaults": False,
                },
            )
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            for file in destination.iterdir():
                self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                lifecycle.stage_module(destination, self.owner)
        self.assertEqual(
            (
                Path(lifecycle.__file__).resolve().parents[1]
                / "infra/shared/providers.tf"
            ).read_bytes(),
            original,
        )

    def owned_plan(self, operation="create", selected=None):
        plan = shared_fixture.SharedPlanTests().plan(operation, selected)
        tags = lifecycle.owner_tags(self.owner)
        plan["variables"]["tags"]["value"].update(tags)
        for container in (
            plan.get("planned_values", {}).get("root_module", {}),
            plan.get("prior_state", {}).get("values", {}).get("root_module", {}),
        ):
            for record in container.get("resources", []):
                if record["mode"] == "managed" and "tags" in record["values"]:
                    record["values"]["tags"].update(tags)
        for record in plan["resource_changes"]:
            for field in ("before", "after"):
                values = record["change"].get(field)
                if isinstance(values, dict) and "tags" in values:
                    values["tags"].update(tags)
        return plan

    def test_native_owner_tag_normalization_preserves_input_and_scope(self):
        for operation, selected in (
            ("create", None),
            ("destroy", {"azurerm_container_registry.shared"}),
        ):
            plan = self.owned_plan(operation, selected)
            before = copy.deepcopy(plan)
            lifecycle.validate_owned_plan(
                plan, lifecycle.GROUP, operation=operation, owner=self.owner
            )
            self.assertEqual(plan, before)
            with self.assertRaises(lifecycle.PlanRejected):
                lifecycle.validate_owned_plan(
                    plan,
                    lifecycle.GROUP,
                    operation=operation,
                    owner={**self.owner, "runAttempt": "1"},
                )
        plan = self.owned_plan()
        plan["variables"]["tags"]["value"]["foreign"] = "value"
        with self.assertRaises(lifecycle.PlanRejected):
            lifecycle.validate_owned_plan(
                plan, lifecycle.GROUP, operation="create", owner=self.owner
            )

    def test_interrupted_endpoint_delete_or_partial_import_can_finish(self):
        plan = self.owned_plan("destroy", {"azurerm_private_endpoint.vault"})
        for record in plan["prior_state"]["values"]["root_module"]["resources"]:
            if record["mode"] == "managed":
                record["values"]["private_dns_zone_group"] = []
        change = next(
            record for record in plan["resource_changes"] if record["mode"] == "managed"
        )
        change["change"]["before"]["private_dns_zone_group"] = []
        lifecycle.validate_owned_plan(
            plan, lifecycle.GROUP, operation="destroy", owner=self.owner
        )
        change["change"]["before"]["private_dns_zone_group"] = [
            {
                "name": "foreign",
                "private_dns_zone_ids": ["/subscriptions/foreign"],
            }
        ]
        with self.assertRaises(lifecycle.PlanRejected):
            lifecycle.validate_owned_plan(
                plan, lifecycle.GROUP, operation="destroy", owner=self.owner
            )
        create = self.owned_plan()
        endpoint = next(
            record
            for record in create["resource_changes"]
            if record.get("address") == "azurerm_private_endpoint.vault"
        )
        endpoint["change"]["after"]["private_dns_zone_group"] = []
        with self.assertRaises(lifecycle.PlanRejected):
            lifecycle.validate_owned_plan(
                create, lifecycle.GROUP, operation="create", owner=self.owner
            )

    def test_empty_refreshed_destroy_can_persist_reconciled_state(self):
        plan = self.owned_plan("destroy", set())
        plan.pop("resource_changes")
        lifecycle.validate_owned_plan(
            plan, lifecycle.GROUP, operation="destroy", owner=self.owner
        )
        with self.assertRaises(lifecycle.PlanRejected):
            lifecycle.validate_owned_plan(
                plan, lifecycle.GROUP, operation="create", owner=self.owner
            )
        stale = self.owned_plan("destroy", {"azurerm_container_registry.shared"})
        stale.pop("resource_changes")
        with self.assertRaises(lifecycle.PlanRejected):
            lifecycle.validate_owned_plan(
                stale, lifecycle.GROUP, operation="destroy", owner=self.owner
            )

    def test_blob_calls_are_oauth_fixed_and_conditional(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(lifecycle, "az") as call,
        ):
            lifecycle.write_owner(Path(directory), self.owner, etag=None)
            arguments = call.call_args.args
            self.assertIn("--auth-mode", arguments)
            self.assertIn("login", arguments)
            self.assertIn("--if-none-match", arguments)
            self.assertIn("*", arguments)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(lifecycle, "az") as call,
        ):
            lifecycle.write_owner(
                Path(directory), {**self.owner, "status": "cleaned"}, etag='"expected"'
            )
            self.assertIn("--if-match", call.call_args.args)
            self.assertIn('"expected"', call.call_args.args)
        for operation, key in (
            ("delete", lifecycle.STATE_KEY),
            ("upload", lifecycle.STATE_KEY),
            ("show", "foreign.json"),
        ):
            with self.assertRaises(lifecycle.SharedError):
                lifecycle.blob(operation, key)
        with (
            patch.object(lifecycle, "az", return_value={"exists": "false"}),
            self.assertRaises(lifecycle.SharedError),
        ):
            lifecycle.blob_exists(lifecycle.STATE_KEY)

    def test_foreign_inventory_or_missing_owner_never_adopted(self):
        registry = {
            "id": lifecycle.scope.RESOURCES["azurerm_container_registry.shared"]["id"],
            "tags": {**lifecycle.scope.TAGS, **lifecycle.owner_tags(self.owner)},
        }
        with patch.object(lifecycle, "az", return_value=[registry]):
            self.assertEqual(
                set(lifecycle.inventory(self.owner)),
                {"azurerm_container_registry.shared"},
            )
            with self.assertRaises(lifecycle.SharedError):
                lifecycle.inventory(None)
        for resource in (
            {**registry, "tags": {}},
            {
                "id": f"{lifecycle.scope.ROOT}/providers/Microsoft.Storage/storageAccounts/foreign"
            },
        ):
            with (
                patch.object(lifecycle, "az", return_value=[resource]),
                self.assertRaises(lifecycle.SharedError),
            ):
                lifecycle.inventory(self.owner)

    def test_native_terraform_isolated_and_failures_explicit(self):
        environment = {
            "ARM_CLIENT_SECRET": "never",
            "ARM_USE_MSI": "true",
            "TF_CLI_ARGS_apply": "-auto-approve",
            "TF_LOG": "TRACE",
            "TF_WORKSPACE": "foreign",
            "TF_DATA_DIR": "/foreign",
            "AZURE_STORAGE_CONNECTION_STRING": "never",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.invalid",
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, environment, clear=True),
            patch.object(lifecycle.subprocess, "run") as call,
        ):
            call.return_value.returncode = 0
            lifecycle.terraform(Path(directory), ["init"], Path(directory) / "init.log")
            used = call.call_args.kwargs["env"]
            for key in (
                "ARM_CLIENT_SECRET",
                "TF_CLI_ARGS_apply",
                "TF_LOG",
                "TF_WORKSPACE",
                "TF_DATA_DIR",
                "AZURE_STORAGE_CONNECTION_STRING",
            ):
                self.assertNotIn(key, used)
            self.assertEqual(used["ARM_USE_MSI"], "false")
            self.assertEqual(used["ARM_USE_CLI"], "false")
            self.assertEqual(
                used["ACTIONS_ID_TOKEN_REQUEST_URL"],
                environment["ACTIONS_ID_TOKEN_REQUEST_URL"],
            )
            call.return_value.returncode = 1
            with self.assertRaises(lifecycle.SharedError):
                lifecycle.terraform(
                    Path(directory), ["apply"], Path(directory) / "apply.log"
                )

    def test_active_dependencies_refuse_cleanup(self):
        with (
            patch.object(
                lifecycle, "az", return_value=[{"id": "an-active-dependency"}]
            ),
            self.assertRaises(lifecycle.SharedError),
        ):
            lifecycle.dependencies_absent()

    def test_existing_owner_or_state_blocks_creator(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(lifecycle, "new_owner", return_value=self.owner),
            patch.object(lifecycle, "validate_scope"),
            patch.object(lifecycle, "dependencies_absent"),
            patch.object(lifecycle, "inventory"),
            patch.object(lifecycle, "blob_exists", return_value=True),
            patch.object(lifecycle, "write_owner") as write,
        ):
            with self.assertRaises(lifecycle.SharedError):
                lifecycle.create(Path(directory))
            write.assert_not_called()

    def test_unowned_state_blocks_cleanup(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(lifecycle, "validate_scope"),
            patch.object(lifecycle, "read_owner", return_value=None),
            patch.object(lifecycle, "inventory"),
            patch.object(lifecycle, "blob_exists", return_value=True),
            patch.object(lifecycle, "terraform") as execute,
        ):
            with self.assertRaises(lifecycle.SharedError):
                lifecycle.cleanup(Path(directory))
            execute.assert_not_called()

    def test_partial_cleanup_recovers_only_fixed_owned_primary_and_tombstones(self):
        address = "azurerm_container_registry.shared"
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}, clear=True),
            patch.object(lifecycle, "validate_scope"),
            patch.object(
                lifecycle, "read_owner", return_value=(self.owner, '"original"')
            ),
            patch.object(
                lifecycle,
                "validate_owner",
                return_value={**self.run, "conclusion": "cancelled"},
            ),
            patch.object(lifecycle, "dependencies_absent"),
            patch.object(lifecycle, "inventory", side_effect=[{address: {}}, {}]),
            patch.object(lifecycle, "stage_module"),
            patch.object(lifecycle, "terraform") as execute,
            patch.object(
                lifecycle, "state_resources", side_effect=[set(), {address}, set()]
            ),
            patch.object(lifecycle, "execute_plan") as plan,
            patch.object(lifecycle, "write_owner") as owner_write,
        ):
            lifecycle.cleanup(Path(directory))
            self.assertEqual(execute.call_count, 2)
            imported = execute.call_args.args[1]
            self.assertEqual(imported[0], "import")
            self.assertEqual(
                imported[-2:], [address, lifecycle.scope.RESOURCES[address]["id"]]
            )
            self.assertEqual(plan.call_args.kwargs["operation"], "destroy")
            self.assertEqual(owner_write.call_args.args[1]["status"], "cleaned")
            self.assertEqual(owner_write.call_args.kwargs["etag"], '"original"')

    def test_import_failure_preserves_owner_and_never_destroys(self):
        address = "azurerm_container_registry.shared"
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}, clear=True),
            patch.object(lifecycle, "validate_scope"),
            patch.object(
                lifecycle, "read_owner", return_value=(self.owner, '"original"')
            ),
            patch.object(
                lifecycle,
                "validate_owner",
                return_value={**self.run, "conclusion": "failure"},
            ),
            patch.object(lifecycle, "dependencies_absent"),
            patch.object(lifecycle, "inventory", return_value={address: {}}),
            patch.object(lifecycle, "stage_module"),
            patch.object(
                lifecycle,
                "terraform",
                side_effect=[None, lifecycle.SharedError("native import failed")],
            ),
            patch.object(lifecycle, "state_resources", return_value=set()),
            patch.object(lifecycle, "execute_plan") as plan,
            patch.object(lifecycle, "write_owner") as owner_write,
            self.assertRaises(lifecycle.SharedError),
        ):
            try:
                lifecycle.cleanup(Path(directory))
            finally:
                plan.assert_not_called()
                owner_write.assert_not_called()

    def test_state_is_verified_before_any_destroy_refresh(self):
        plan = self.owned_plan("destroy", {"azurerm_container_registry.shared"})
        values = plan["prior_state"]["values"]
        for record in values["root_module"]["resources"]:
            record["provider_name"] = "registry.terraform.io/hashicorp/azurerm"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)

            def show(module, arguments, log):
                lifecycle.private_json(log, {"format_version": "1.0", "values": values})

            with patch.object(lifecycle, "terraform", side_effect=show):
                self.assertEqual(
                    lifecycle.state_resources(path, path, "valid", self.owner),
                    {"azurerm_container_registry.shared"},
                )
                managed = next(
                    record
                    for record in values["root_module"]["resources"]
                    if record["mode"] == "managed"
                )
                managed["values"][
                    "id"
                ] = "/subscriptions/foreign/resourceGroups/foreign"
                with self.assertRaises(lifecycle.PlanRejected):
                    lifecycle.state_resources(path, path, "foreign", self.owner)

    def test_owner_download_checks_size_and_etag_before_read(self):
        for properties in (
            {"etag": '"version"', "contentLength": 8193},
            {"etag": "bad\nheader", "contentLength": 512},
            {"etag": '"version"', "contentLength": True},
        ):
            with (
                tempfile.TemporaryDirectory() as directory,
                patch.object(lifecycle, "blob_exists", return_value=True),
                patch.object(
                    lifecycle, "blob", return_value={"properties": properties}
                ) as call,
                self.assertRaises(lifecycle.SharedError),
            ):
                try:
                    lifecycle.read_owner(Path(directory))
                finally:
                    self.assertEqual(call.call_count, 1)

    def test_foreign_vnet_child_blocks_cascade_delete(self):
        identifier = lifecycle.scope.RESOURCES["azurerm_virtual_network.shared"]["id"]
        resource = {
            "id": identifier,
            "tags": {**lifecycle.scope.TAGS, **lifecycle.owner_tags(self.owner)},
        }
        with (
            patch.object(lifecycle, "az", return_value=[resource]),
            patch.object(
                lifecycle,
                "arm",
                return_value={
                    "properties": {"subnets": [{"id": f"{identifier}/subnets/foreign"}]}
                },
            ),
            self.assertRaises(lifecycle.SharedError),
        ):
            lifecycle.inventory(self.owner)

    def test_live_storage_security_is_management_plane_only(self):
        account = {
            "id": lifecycle.FALLBACK_TARGET.subscription,
            "tenantId": lifecycle.FALLBACK_TARGET.tenant,
            "user": {
                "type": "servicePrincipal",
                "name": lifecycle.FALLBACK_TARGET.client,
            },
        }

        def metadata(*arguments):
            if arguments[:2] == ("account", "show"):
                return account
            group = arguments[-1]
            return {
                "id": f"/subscriptions/{lifecycle.FALLBACK_TARGET.subscription}/resourceGroups/{group}",
                "name": group,
                "tags": lifecycle.FALLBACK_TARGET.group_tags,
            }

        properties = {
            "provisioningState": "Succeeded",
            "allowSharedKeyAccess": False,
            "allowBlobPublicAccess": False,
            "supportsHttpsTrafficOnly": True,
            "defaultToOAuthAuthentication": True,
            "minimumTlsVersion": "TLS1_2",
            "publicNetworkAccess": "Disabled",
        }
        storage = {
            "name": lifecycle.ACCOUNT,
            "location": lifecycle.REGION,
            "kind": "StorageV2",
            "sku": {"name": "Standard_LRS"},
            "tags": lifecycle.FALLBACK_TARGET.group_tags,
            "properties": properties,
        }
        service = {
            "properties": {
                "isVersioningEnabled": True,
                "deleteRetentionPolicy": {"enabled": True, "days": 7},
                "containerDeleteRetentionPolicy": {"enabled": True, "days": 7},
            }
        }
        with (
            patch.object(lifecycle, "az", side_effect=metadata),
            patch.object(
                lifecycle,
                "arm",
                side_effect=[
                    storage,
                    service,
                    {"properties": {"publicAccess": "None"}},
                ],
            ),
            patch.object(lifecycle, "blob") as data,
            patch.object(lifecycle, "validate_private_state_route") as route,
        ):
            lifecycle.validate_scope()
            data.assert_not_called()
            route.assert_called_once_with(properties)
        properties["allowSharedKeyAccess"] = True
        with (
            patch.object(lifecycle, "az", side_effect=metadata),
            patch.object(lifecycle, "arm", return_value=storage),
            self.assertRaises(lifecycle.SharedError),
        ):
            lifecycle.validate_scope()

    def test_disabled_main_never_calls_azure_or_terraform(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(sys, "argv", ["lifecycle", "create"]),
            patch.object(lifecycle, "command") as command,
            self.assertRaises(SystemExit),
        ):
            try:
                lifecycle.main()
            finally:
                command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
