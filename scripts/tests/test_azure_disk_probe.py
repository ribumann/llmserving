from __future__ import annotations

import contextlib
import copy
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import azure_disk_probe as probe


class DiskProbeTests(unittest.TestCase):
    def price(self):
        return {
            "Currency": "USD",
            "NextPageLink": None,
            "Items": [
                {
                    "armRegionName": probe.REGION,
                    "productName": "Standard HDD Managed Disks",
                    "skuName": "S4 LRS",
                    "type": "Consumption",
                    "currencyCode": "USD",
                    "unitOfMeasure": "1/Month",
                    "isPrimaryMeterRegion": True,
                    "effectiveStartDate": "2025-01-01T00:00:00Z",
                    "retailPrice": 1.75,
                }
            ],
        }

    def test_exact_live_price_and_current_monthly_ceiling(self):
        self.assertEqual(probe.validate_price(self.price()), 1.75)
        for key in self.price()["Items"][0]:
            value = copy.deepcopy(self.price())
            value["Items"][0][key] = "unexpected"
            with self.subTest(key=key), self.assertRaises(probe.ProbeError):
                probe.validate_price(value)
        for price in (None, True, 0, -1, 10.01, float("nan"), float("inf")):
            value = self.price()
            value["Items"][0]["retailPrice"] = price
            with self.subTest(price=price), self.assertRaises(probe.ProbeError):
                probe.validate_price(value)
        for changed in (
            {"Currency": "EUR"},
            {"NextPageLink": "https://next.example"},
            {"Items": []},
            {"Items": self.price()["Items"] * 2},
        ):
            with self.subTest(changed=changed), self.assertRaises(probe.ProbeError):
                probe.validate_price({**self.price(), **changed})
        value = self.price()
        value["Items"][0]["effectiveStartDate"] = "9999-01-01T00:00:00Z"
        with self.assertRaises(probe.ProbeError):
            probe.validate_price(value)

    def test_price_failure_prevents_all_azure_calls(self):
        with patch.dict(os.environ, self.environment(), clear=True), patch.object(
            probe, "quote", side_effect=probe.ProbeError("Price unavailable.")
        ), patch.object(probe, "az") as azure, self.assertRaises(probe.ProbeError):
            probe.create()
        azure.assert_not_called()

    def environment(self, cleanup=False):
        return {
            "AZURE_CLIENT_ID": probe.FALLBACK_TARGET.client,
            "AZURE_TENANT_ID": probe.FALLBACK_TARGET.tenant,
            "AZURE_SUBSCRIPTION_ID": probe.FALLBACK_TARGET.subscription,
            "GITHUB_REPOSITORY": probe.REPOSITORY,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_run" if cleanup else "workflow_dispatch",
            "GITHUB_WORKFLOW_REF": (
                f"{probe.REPOSITORY}/"
                f"{probe.CLEANUP_WORKFLOW if cleanup else probe.CREATE_WORKFLOW}"
                "@refs/heads/main"
            ),
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_SHA": "a" * 40,
            **({"EXPECTED_RUN_ID": "123"} if cleanup else {}),
        }

    def record(self):
        return {
            "id": f"{probe.group_id()}/providers/Microsoft.Compute/disks/{probe.DISK}",
            "name": probe.DISK,
            "type": "Microsoft.Compute/disks",
            "location": probe.REGION,
            "diskSizeGb": 4,
            "sku": {"name": "Standard_LRS"},
            "managedBy": None,
            "diskState": "Unattached",
            "creationData": {"createOption": "Empty"},
            "networkAccessPolicy": "DenyAll",
            "publicNetworkAccess": "Disabled",
            "tags": {
                **probe.fixed_tags(),
                "runId": "123",
                "runAttempt": "1",
                "sourceSha": "a" * 40,
                "expiresAt": "2026-11-05T13:00:00Z",
            },
        }

    def azure(self, *arguments):
        if arguments[:2] == ("account", "show"):
            return {
                "id": probe.FALLBACK_TARGET.subscription,
                "tenantId": probe.FALLBACK_TARGET.tenant,
                "user": {
                    "type": "servicePrincipal",
                    "name": probe.FALLBACK_TARGET.client,
                },
            }
        if arguments[:2] == ("group", "show"):
            self.assertEqual(arguments[-1], probe.GROUP)
            return {
                "id": probe.group_id(),
                "name": probe.GROUP,
                "tags": probe.FALLBACK_TARGET.group_tags,
            }
        if arguments[:2] == ("disk", "list"):
            return [self.record()]
        raise AssertionError(arguments)

    def owner(self):
        return {
            "repository": {"full_name": probe.REPOSITORY},
            "head_repository": {"full_name": probe.REPOSITORY},
            "path": probe.CREATE_WORKFLOW,
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "run_attempt": 1,
            "status": "completed",
        }

    def test_each_configuration_mismatch_rejected_before_cloud_calls(self):
        for cleanup in (False, True):
            operation = probe.cleanup if cleanup else probe.create
            for key in self.environment(cleanup):
                if (
                    key in {"GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA"}
                    and cleanup
                ):
                    continue
                with self.subTest(cleanup=cleanup, key=key):
                    environment = {**self.environment(cleanup), key: "unexpected"}
                    with patch.dict(os.environ, environment, clear=True), patch.object(
                        probe, "az"
                    ) as azure, self.assertRaises(probe.ProbeError):
                        operation()
                    azure.assert_not_called()

    def test_live_principal_and_exact_group_ownership_are_mandatory(self):
        for operation, key in (
            (("account", "show"), "id"),
            (("account", "show"), "tenantId"),
            (("account", "show"), "user"),
            (("group", "show"), "id"),
            (("group", "show"), "name"),
            (("group", "show"), "tags"),
        ):

            def changed(*arguments, operation=operation, key=key):
                result = self.azure(*arguments)
                if arguments[:2] == operation:
                    result[key] = "wrong"
                return result

            with self.subTest(operation=operation, key=key), patch.object(
                probe, "az", side_effect=changed
            ), self.assertRaises(probe.ProbeError):
                probe.validate_scope()

    def test_fixed_disk_shape_and_exact_tags_fail_closed(self):
        record = self.record()
        for key in record:
            changed = copy.deepcopy(record)
            changed[key] = None if key != "managedBy" else "/another/owner"
            with self.subTest(key=key), patch.object(
                probe, "az", return_value=[changed]
            ), self.assertRaises(probe.ProbeError):
                probe.disk()
        for key in record["tags"]:
            changed = copy.deepcopy(record)
            changed["tags"][key] = "wrong"
            with self.subTest(tag=key), patch.object(
                probe, "az", return_value=[changed]
            ), self.assertRaises(probe.ProbeError):
                probe.disk()

    def test_duplicate_and_malformed_inventory_rejected(self):
        for inventory in ({}, [None], [self.record(), self.record()]):
            with patch.object(probe, "az", return_value=inventory), self.assertRaises(
                probe.ProbeError
            ):
                probe.disk()

    def test_create_does_not_adopt_an_existing_owned_disk(self):
        with patch.dict(os.environ, self.environment(), clear=True), patch.object(
            probe, "az", side_effect=self.azure
        ) as azure, patch.object(probe, "quote", return_value=1.75), self.assertRaises(
            probe.ProbeError
        ):
            probe.create()
        self.assertNotIn(
            ("disk", "create"), [call.args[:2] for call in azure.call_args_list]
        )

    def test_creation_is_one_empty_four_gib_disk_and_verifies_exact_run(self):
        created = None

        def azure(*arguments):
            nonlocal created
            if arguments[:2] == ("disk", "list"):
                return [created] if created else []
            if arguments[:2] == ("disk", "create"):
                self.assertEqual(arguments[arguments.index("--size-gb") + 1], "4")
                self.assertEqual(
                    arguments[arguments.index("--sku") + 1], "Standard_LRS"
                )
                self.assertEqual(
                    arguments[arguments.index("--resource-group") + 1], probe.GROUP
                )
                created = self.record()
                created["tags"] = dict(
                    item.split("=", 1)
                    for item in arguments[arguments.index("--tags") + 1 :]
                )
                return created
            return self.azure(*arguments)

        with patch.dict(os.environ, self.environment(), clear=True), patch.object(
            probe, "az", side_effect=azure
        ) as calls, patch.object(
            probe, "quote", return_value=1.75
        ), contextlib.redirect_stdout(
            io.StringIO()
        ):
            probe.create()
        self.assertEqual(
            sum(call.args[:2] == ("disk", "create") for call in calls.call_args_list), 1
        )

    def cleanup(self, owner=None, environment=None):
        deleted = False

        def azure(*arguments):
            nonlocal deleted
            if arguments[:2] == ("disk", "list"):
                return [] if deleted else [self.record()]
            if arguments[:2] == ("disk", "delete"):
                self.assertEqual(
                    arguments,
                    (
                        "disk",
                        "delete",
                        "--resource-group",
                        probe.GROUP,
                        "--name",
                        probe.DISK,
                        "--yes",
                    ),
                )
                deleted = True
                return None
            return self.azure(*arguments)

        with patch.dict(
            os.environ, environment or self.environment(True), clear=True
        ), patch.object(probe, "az", side_effect=azure), patch.object(
            probe, "command", return_value=self.owner() if owner is None else owner
        ) as owner_lookup, contextlib.redirect_stdout(
            io.StringIO()
        ):
            try:
                probe.cleanup()
            except probe.ProbeError:
                self.assertFalse(deleted)
                raise
        owner_lookup.assert_called_once_with(
            [
                "gh",
                "api",
                f"repos/{probe.REPOSITORY}/actions/runs/123/attempts/1",
            ]
        )
        return deleted

    def test_cleanup_deletes_exact_completed_run_disk_and_preserves_group(self):
        self.assertTrue(self.cleanup())
        scheduled = self.environment(True)
        scheduled["GITHUB_EVENT_NAME"] = "schedule"
        scheduled.pop("EXPECTED_RUN_ID")
        self.assertTrue(self.cleanup(environment=scheduled))

    def test_foreign_pending_mismatched_and_untrusted_runs_preserved(self):
        for key in self.owner():
            owner = self.owner()
            owner[key] = "unexpected"
            with self.subTest(key=key), self.assertRaises(probe.ProbeError):
                self.cleanup(owner=owner)
        with self.assertRaises(probe.ProbeError):
            self.cleanup(
                environment={**self.environment(True), "EXPECTED_RUN_ID": "999"}
            )

    def test_absence_is_verified_without_delete_or_run_lookup(self):
        def azure(*arguments):
            return [] if arguments[:2] == ("disk", "list") else self.azure(*arguments)

        with patch.dict(os.environ, self.environment(True), clear=True), patch.object(
            probe, "az", side_effect=azure
        ) as calls, patch.object(
            probe, "command"
        ) as command, contextlib.redirect_stdout(
            io.StringIO()
        ):
            probe.cleanup()
        command.assert_not_called()
        self.assertNotIn(
            ("disk", "delete"), [call.args[:2] for call in calls.call_args_list]
        )

    def test_cli_errors_do_not_publish_service_stderr(self):
        result = subprocess.CompletedProcess(
            ["az"], 1, "", "sensitive-private-diagnostic"
        )
        with patch.object(
            probe.subprocess, "run", return_value=result
        ), self.assertRaises(probe.ProbeError) as error:
            probe.command(["az", "disk", "list"])
        self.assertNotIn("sensitive-private", str(error.exception))

    def test_every_azure_command_has_fixed_explicit_subscription(self):
        with patch.object(probe, "command", return_value={}) as command:
            probe.az("disk", "list", "--resource-group", probe.GROUP)
        arguments = command.call_args.args[0]
        self.assertEqual(
            arguments[arguments.index("--subscription") + 1],
            probe.FALLBACK_TARGET.subscription,
        )

    def test_workflows_are_fixed_protected_and_independent(self):
        create = (ROOT / probe.CREATE_WORKFLOW).read_text()
        cleanup = (ROOT / probe.CLEANUP_WORKFLOW).read_text()
        for workflow in (create, cleanup):
            self.assertIn("environment: azure-e2e-fallback", workflow)
            self.assertIn("github.ref == 'refs/heads/main'", workflow)
            self.assertIn("persist-credentials: false", workflow)
            self.assertIn("group: azure-fallback-billable-disk-probe", workflow)
            self.assertLess(
                workflow.index("validate-"), workflow.index("uses: azure/login@")
            )
            self.assertNotIn("role assignment", workflow)
            self.assertNotIn("artifact", workflow)
        self.assertIn("workflow_run:", cleanup)
        self.assertIn("schedule:", cleanup)
        self.assertIn("ref: main", cleanup)
        self.assertIn("actions: read", cleanup)
        self.assertNotIn("run: python scripts/azure_disk_probe.py cleanup", create)
