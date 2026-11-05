from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "release_preflight", ROOT / "scripts/azure_release_preflight.py"
)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class ReadOnlyPreflightTests(unittest.TestCase):
    def environment(self):
        target = preflight.FALLBACK_TARGET
        return {
            "AZURE_SUBSCRIPTION_ID": target.subscription,
            "AZURE_TENANT_ID": target.tenant,
            "AZURE_CLIENT_ID": target.client,
            "GITHUB_REPOSITORY": "ribumann/llmserving",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_WORKFLOW_REF": f"ribumann/llmserving/{preflight.WORKFLOW}@refs/heads/main",
            "GITHUB_SHA": "a" * 40,
        }

    def sku(self):
        return {
            "name": preflight.SKU,
            "resourceType": "virtualMachines",
            "locations": [preflight.REGION],
            "family": "standardNCASv3_T4Family",
            "capabilities": [
                {"name": "vCPUs", "value": "4"},
                {"name": "LowPriorityCapable", "value": "False"},
            ],
            "restrictions": [
                {
                    "type": "Zone",
                    "reasonCode": "NotAvailableForSubscription",
                    "restrictionInfo": {
                        "locations": [preflight.REGION],
                        "zones": ["1", "2", "3"],
                    },
                }
            ],
            "locationInfo": [{"location": preflight.REGION, "zones": ["2", "1"]}],
        }

    def azure(self, *arguments):
        target = preflight.FALLBACK_TARGET
        operation = arguments[:2]
        if operation == ("account", "show"):
            return {
                "id": target.subscription,
                "tenantId": target.tenant,
                "user": {"type": "servicePrincipal", "name": target.client},
            }
        if operation == ("group", "show"):
            name = arguments[-1]
            return {
                "id": f"/subscriptions/{target.subscription}/resourceGroups/{name}",
                "name": name,
                "tags": target.group_tags,
            }
        if operation == ("resource", "list"):
            return []
        if operation == ("vm", "list-skus"):
            self.assertIn("--all", arguments)
            self.assertEqual(arguments[arguments.index("--location") + 1], "italynorth")
            return [self.sku()]
        if operation == ("vm", "list-usage"):
            return [
                {
                    "name": {"value": "standardNCASv3_T4Family"},
                    "currentValue": 0,
                    "limit": 8,
                },
                {"name": {"value": "cores"}, "currentValue": 0, "limit": 108},
                {
                    "name": {"value": "lowPriorityCores"},
                    "currentValue": 0,
                    "limit": 100,
                },
                {"name": {"value": "unrelatedFamily"}, "currentValue": 0, "limit": 999},
            ]
        raise AssertionError(arguments)

    def inspect(self, handler=None):
        with patch.dict(os.environ, self.environment(), clear=True), patch.object(
            preflight, "read_azure", side_effect=handler or self.azure
        ):
            return preflight.inspect()

    def test_fixed_environment_and_each_mismatch_rejected_before_cloud_reads(self):
        environment = self.environment()
        for key in environment:
            if key == "GITHUB_SHA":
                continue
            for value in (None, "unexpected"):
                with self.subTest(key=key, value=value):
                    changed = dict(environment)
                    if value is None:
                        changed.pop(key)
                    else:
                        changed[key] = value
                    with patch.dict(os.environ, changed, clear=True), patch.object(
                        preflight, "read_azure"
                    ) as azure:
                        with self.assertRaises(preflight.PreflightError):
                            preflight.inspect()
                        azure.assert_not_called()

    def test_read_only_report_preserves_zone_uncertainty_and_exact_quota(self):
        report = self.inspect()
        self.assertEqual(report["sku"]["restrictions"], self.sku()["restrictions"])
        self.assertEqual(report["sku"]["locationInfo"], self.sku()["locationInfo"])
        self.assertEqual(report["sku"]["capabilities"]["LowPriorityCapable"], "False")
        self.assertIn("unknown", report["sku"]["unzonedEligibility"])
        self.assertFalse(report["sku"]["allocationVerified"])
        self.assertFalse(report["resourcesCreated"])
        self.assertFalse(report["billableCleanupVerified"])
        self.assertFalse(report["deploymentAuthorizedByThisReport"])
        self.assertEqual(len(report["quota"]), 3)
        self.assertEqual(set(report["groups"]), set(preflight.GROUPS))
        for identifier in (
            preflight.FALLBACK_TARGET.subscription,
            preflight.FALLBACK_TARGET.tenant,
            preflight.FALLBACK_TARGET.client,
        ):
            self.assertNotIn(identifier, json.dumps(report))

    def test_wrong_live_account_or_identity_rejected(self):
        for key in ("id", "tenantId", "user"):

            def changed(*arguments, key=key):
                result = self.azure(*arguments)
                if arguments[:2] == ("account", "show"):
                    result[key] = "wrong"
                return result

            with self.subTest(key=key), self.assertRaises(preflight.PreflightError):
                self.inspect(changed)

    def test_group_scope_and_every_ownership_tag_are_required(self):
        for key in ("id", "name", *preflight.FALLBACK_TARGET.group_tags):

            def changed(*arguments, key=key):
                result = self.azure(*arguments)
                if arguments[:2] == ("group", "show"):
                    if key in ("id", "name"):
                        result[key] = "wrong"
                    else:
                        result["tags"][key] = "wrong"
                return result

            with self.subTest(key=key), self.assertRaises(preflight.PreflightError):
                self.inspect(changed)

    def test_inventory_cannot_escape_group_or_dump_resource_identifiers(self):
        def changed(*arguments):
            if arguments[:2] == ("resource", "list"):
                return [
                    {
                        "id": "/subscriptions/other/resourceGroups/foreign/vm",
                        "type": "vm",
                    }
                ]
            return self.azure(*arguments)

        with self.assertRaises(preflight.PreflightError):
            self.inspect(changed)

    def test_nonempty_inventory_is_reported_not_deleted_or_adopted(self):
        def changed(*arguments):
            if arguments[:2] == ("resource", "list"):
                return [
                    {
                        "id": f"/subscriptions/{preflight.FALLBACK_TARGET.subscription}/resourceGroups/{arguments[-1]}/providers/Microsoft.Compute/virtualMachines/example",
                        "type": "Microsoft.Compute/virtualMachines",
                    }
                ]
            return self.azure(*arguments)

        report = self.inspect(changed)
        self.assertEqual(report["groups"]["demo"]["resourceCount"], 1)
        self.assertNotIn("example", json.dumps(report))
        self.assertFalse(report["deploymentAuthorizedByThisReport"])

    def test_missing_ambiguous_or_wrong_region_sku_is_not_success(self):
        wrong = copy.deepcopy(self.sku())
        wrong["locations"] = ["other-region"]
        for records in (None, [], [wrong], [self.sku(), self.sku()]):
            with self.subTest(records=records), self.assertRaises(
                preflight.PreflightError
            ):
                preflight.summarize_sku(records)

    def test_missing_duplicate_or_malformed_quota_cannot_be_a_success_report(self):
        complete = self.azure("vm", "list-usage")
        malformed = copy.deepcopy(complete)
        malformed[0]["limit"] = "8"
        boolean = copy.deepcopy(complete)
        boolean[0]["currentValue"] = False
        negative = copy.deepcopy(complete)
        negative[0]["limit"] = -1
        for rows in (
            None,
            [],
            complete[1:],
            complete[:1],
            complete + [complete[0]],
            malformed,
            boolean,
            negative,
        ):

            def changed(*arguments, rows=rows):
                if arguments[:2] == ("vm", "list-usage"):
                    return rows
                return self.azure(*arguments)

            with self.subTest(rows=rows), self.assertRaises(preflight.PreflightError):
                self.inspect(changed)

    def test_missing_family_cannot_silently_drop_family_quota(self):
        for family in (None, "", " "):

            def changed(*arguments, family=family):
                result = self.azure(*arguments)
                if arguments[:2] == ("vm", "list-skus"):
                    result[0]["family"] = family
                return result

            with self.subTest(family=family), self.assertRaises(
                preflight.PreflightError
            ):
                self.inspect(changed)

    def test_command_allowlist_refuses_mutation_and_cli_defaults(self):
        for operation in (("vm", "create"), ("group", "delete"), ("account", "set")):
            with self.subTest(operation=operation), patch.object(
                subprocess, "run"
            ) as run:
                with self.assertRaises(preflight.PreflightError):
                    preflight.read_azure(*operation)
                run.assert_not_called()

    def test_every_read_uses_explicit_subscription_and_no_shell(self):
        result = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        with patch.object(subprocess, "run", return_value=result) as run:
            preflight.read_azure("account", "show")
        args, kwargs = run.call_args
        self.assertEqual(
            args[0],
            [
                "az",
                "account",
                "show",
                "--subscription",
                preflight.FALLBACK_TARGET.subscription,
                "--only-show-errors",
                "--output",
                "json",
            ],
        )
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], 120)

    def test_cli_errors_and_malformed_json_do_not_leak_private_stderr(self):
        results = (
            subprocess.CompletedProcess([], 1, stdout="", stderr="PRIVATE credential"),
            subprocess.CompletedProcess([], 0, stdout="PRIVATE invalid", stderr=""),
        )
        for result in results:
            with patch.object(
                subprocess, "run", return_value=result
            ), self.assertRaises(preflight.PreflightError) as raised:
                preflight.read_azure("account", "show")
            self.assertNotIn("PRIVATE", str(raised.exception))
        with patch.object(
            subprocess, "run", side_effect=subprocess.TimeoutExpired("az", 120)
        ), self.assertRaises(preflight.PreflightError):
            preflight.read_azure("account", "show")

    def test_workflow_is_protected_main_dispatch_only_without_mutating_commands(self):
        source = (ROOT / preflight.WORKFLOW).read_text()
        self.assertIn("workflow_dispatch: {}", source)
        self.assertNotIn("pull_request:", source)
        self.assertIn("github.ref == 'refs/heads/main'", source)
        self.assertIn("environment: azure-e2e-fallback", source)
        self.assertIn("persist-credentials: false", source)
        self.assertIn("azure/login@a457da9ea143d694b1b9c7c869ebb04ebe844ef5", source)
        self.assertLess(
            source.index("validate-config"), source.index("uses: azure/login@")
        )
        for operation in (
            "create",
            "delete",
            "register",
            "assign",
            "terraform",
            "--validate",
        ):
            self.assertNotIn(operation, source)


if __name__ == "__main__":
    unittest.main()
