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

    def test_actual_azure_region_casing_preserves_exact_sku_and_zone_restrictions(self):
        sku = self.sku()
        sku["locations"] = ["ItalyNorth"]
        sku["restrictions"][0]["restrictionInfo"]["locations"] = ["ItalyNorth"]
        sku["restrictions"][0]["values"] = ["ItalyNorth"]
        sku["locationInfo"][0]["location"] = "ItalyNorth"
        report = preflight.summarize_sku([sku])
        self.assertEqual(report["name"], preflight.SKU)
        self.assertEqual(report["region"], "italynorth")
        self.assertEqual(report["restrictions"], sku["restrictions"])
        self.assertEqual(report["locationInfo"], sku["locationInfo"])
        self.assertIn("unknown", report["unzonedEligibility"])

    def test_case_matching_cannot_accept_similar_names_wrong_types_or_regions(self):
        for field, value in (
            ("name", preflight.SKU + "_other"),
            ("resourceType", "disks"),
            ("locations", ["ItalyNorthOther"]),
            ("locations", "ItalyNorth"),
            ("locations", None),
        ):
            sku = self.sku()
            sku[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(
                preflight.PreflightError
            ):
                preflight.summarize_sku([sku])
        sku = self.sku()
        sku["locations"] = ["ItalyNorth"]
        with self.assertRaises(preflight.PreflightError):
            preflight.summarize_sku([sku, copy.deepcopy(sku)])

    def test_missing_duplicate_or_malformed_quota_cannot_be_a_success_report(self):
        complete = self.azure("vm", "list-usage")
        malformed = copy.deepcopy(complete)
        malformed[0]["limit"] = "8.0"
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

    def test_actual_cli_string_counts_and_exact_spaced_family_are_normalized(self):
        family = "Standard NCASv3_T4 Family"
        rows = [
            {
                "name": {
                    "value": "lowPriorityCores",
                    "localizedValue": "Total Regional Low-priority vCPUs",
                },
                "currentValue": "0",
                "limit": "100",
            },
            {
                "name": {"value": "cores", "localizedValue": "Total Regional vCPUs"},
                "currentValue": "0",
                "limit": "108",
            },
            {
                "name": {"value": family, "localizedValue": family + " vCPUs"},
                "currentValue": "0",
                "limit": "8",
            },
        ]

        def changed(*arguments):
            if arguments[:2] == ("vm", "list-usage"):
                return rows
            result = self.azure(*arguments)
            if arguments[:2] == ("vm", "list-skus"):
                result[0]["family"] = family
                result[0]["locations"] = ["ItalyNorth"]
            return result

        report = self.inspect(changed)
        self.assertEqual(
            report["quota"],
            [
                {"name": "lowPriorityCores", "current": 0, "limit": 100},
                {"name": "cores", "current": 0, "limit": 108},
                {"name": family, "current": 0, "limit": 8},
            ],
        )
        self.assertFalse(report["deploymentAuthorizedByThisReport"])
        rows[2]["name"]["value"] = "anotherFamily"
        with self.assertRaises(preflight.PreflightError):
            self.inspect(changed)

    def test_quota_count_only_accepts_nonnegative_int_or_bounded_ascii_decimal(self):
        for raw, expected in ((0, 0), (8, 8), ("0", 0), ("8", 8), ("0008", 8)):
            with self.subTest(raw=raw):
                self.assertEqual(preflight.quota_count(raw), expected)
        for raw in (
            None,
            True,
            False,
            -1,
            8.0,
            {},
            [],
            "",
            " ",
            " 8",
            "8 ",
            "-1",
            "+8",
            "8.0",
            "1e2",
            "８",
            "٨",
            "9" * 21,
        ):
            with self.subTest(raw=raw), self.assertRaises(preflight.PreflightError):
                preflight.quota_count(raw)

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
        self.assertIn("workflow_dispatch:", source)
        self.assertIn("inspect_bootstrap:", source)
        self.assertIn("default: false", source)
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

    def permissions(self):
        return {
            "value": [
                {
                    "actions": ["*"],
                    "notActions": ["Microsoft.Authorization/*/write"],
                    "dataActions": [],
                    "notDataActions": [],
                }
            ],
            "nextLink": None,
        }

    def app(self):
        return {
            "appId": preflight.SSO_CLIENT,
            "signInAudience": "AzureADMyOrg",
            "web": {"redirectUris": []},
            "passwordCredentials": [],
            "requiredResourceAccess": [],
        }

    def test_permission_rules_exclusions_and_union_are_not_deployment_proof(self):
        rules = self.permissions()
        summary = preflight.permission_summary(rules)
        self.assertTrue(summary["reportedAllowRules"]["containerAppEnvironmentWrite"])
        self.assertFalse(summary["reportedAllowRules"]["roleAssignmentWrite"])
        self.assertFalse(summary["reportedAllowRules"]["stateBlobWrite"])
        self.assertFalse(summary["denyAssignmentsVerified"])
        self.assertFalse(summary["platformCreateDeleteBehaviorVerified"])
        rules["value"].append(
            {
                "actions": ["MICROSOFT.AUTHORIZATION/ROLEASSIGNMENTS/WRITE"],
                "notActions": [],
                "dataActions": [
                    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/*"
                ],
                "notDataActions": ["*/delete"],
            }
        )
        summary = preflight.permission_summary(rules)
        self.assertTrue(summary["reportedAllowRules"]["roleAssignmentWrite"])
        self.assertTrue(summary["reportedAllowRules"]["stateBlobWrite"])
        rules["value"] = []
        self.assertFalse(
            any(preflight.permission_summary(rules)["reportedAllowRules"].values())
        )

    def test_missing_malformed_or_partial_permission_metadata_fails_closed(self):
        for field in ("actions", "notActions", "dataActions", "notDataActions"):
            for value in (None, {}, "*", [None]):
                rules = self.permissions()
                rules["value"][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(
                    preflight.PreflightError
                ):
                    preflight.permission_summary(rules)
        for rules in (
            None,
            {},
            {"value": [None]},
            {**self.permissions(), "nextLink": "next"},
        ):
            with self.assertRaises(preflight.PreflightError):
                preflight.permission_summary(rules)

    def test_exact_existing_app_summary_never_claims_secret_or_browser_acceptance(self):
        summary = preflight.app_summary(self.app())
        self.assertTrue(summary["exactExistingAppVerified"])
        self.assertEqual(summary["redirectUriCount"], 0)
        self.assertEqual(summary["activePasswordCredentialCount"], 0)
        self.assertEqual(summary["requestedResourceCount"], 0)
        self.assertFalse(summary["secretValueRead"])
        self.assertFalse(summary["exactNewTargetCallbacksVerified"])
        self.assertFalse(summary["consentAssignmentsAndBrowserTokenFlowVerified"])
        app = self.app()
        app["passwordCredentials"] = [
            {
                "startDateTime": "2020-01-01T00:00:00Z",
                "endDateTime": "2050-01-01T00:00:00Z",
                "secretText": "DO_NOT_LOG_CREDENTIAL",
            }
        ]
        summary = preflight.app_summary(app)
        self.assertEqual(summary["activePasswordCredentialCount"], 1)
        self.assertNotIn("DO_NOT_LOG", json.dumps(summary))
        for key in app:
            changed = copy.deepcopy(app)
            changed[key] = None
            with self.subTest(key=key), self.assertRaises(preflight.PreflightError):
                preflight.app_summary(changed)
        for date in (None, "invalid", "2020-01-01T00:00:00", "2010-01-01T00:00:00Z"):
            changed = copy.deepcopy(app)
            changed["passwordCredentials"][0]["endDateTime"] = date
            with self.subTest(date=date), self.assertRaises(preflight.PreflightError):
                preflight.app_summary(changed)

    def bootstrap(self, fail_scopes=(), *, provider_overrides=None):
        def azure(*arguments):
            if arguments[:2] == ("account", "show"):
                return self.azure(*arguments)
            if arguments[:2] == ("provider", "show"):
                namespace = arguments[arguments.index("--namespace") + 1]
                if namespace in fail_scopes:
                    raise preflight.PreflightError("Sanitized read failure.")
                return (provider_overrides or {}).get(
                    namespace,
                    {"namespace": namespace, "registrationState": "Registered"},
                )
            self.assertEqual(arguments[:4], ("rest", "--method", "GET", "--url"))
            url = arguments[-1]
            alias = next(
                (
                    name
                    for name, value in preflight.PERMISSION_URLS.items()
                    if value == url
                ),
                "existingTestApp",
            )
            if alias in fail_scopes:
                raise preflight.PreflightError("Sanitized read failure.")
            if url == preflight.APP_URL:
                return self.app()
            self.assertIn(url, preflight.PERMISSION_URLS.values())
            return self.permissions()

        with patch.dict(os.environ, self.environment(), clear=True), patch.object(
            preflight, "read_azure", side_effect=azure
        ):
            return preflight.inspect_bootstrap()

    def test_all_bootstrap_reads_succeed_without_claiming_bootstrap_or_extra_permissions(
        self,
    ):
        report = self.bootstrap()
        self.assertTrue(report["allReadsSucceeded"])
        self.assertEqual(set(report["permissions"]), set(preflight.PERMISSION_URLS))
        self.assertEqual(set(report["providers"]), set(preflight.PROVIDERS))
        self.assertFalse(report["deploymentReady"])
        self.assertFalse(report["resourcesOrRolesChanged"])
        self.assertFalse(report["subscriptionLevelGroupCreationVerified"])
        self.assertFalse(report["vaultCredentialAccessVerified"])
        self.assertEqual(report["testApp"]["activePasswordCredentialCount"], 0)
        for identifier in (
            preflight.FALLBACK_TARGET.subscription,
            preflight.FALLBACK_TARGET.client,
            preflight.FALLBACK_TARGET.tenant,
            preflight.SSO_CLIENT,
        ):
            self.assertNotIn(identifier, json.dumps(report))

    def test_denied_or_unread_scopes_explicitly_remain_unverified(self):
        report = self.bootstrap(
            ("acaInfrastructure", "existingTestApp", "Microsoft.App")
        )
        self.assertFalse(report["allReadsSucceeded"])
        self.assertIsNone(report["testApp"])
        self.assertNotIn("acaInfrastructure", report["permissions"])
        self.assertEqual(
            {row["scope"] for row in report["readErrors"]},
            {
                "acaInfrastructure",
                "existingTestApp",
                "Microsoft.App",
            },
        )
        with patch.object(
            preflight, "inspect_bootstrap", return_value=report
        ), patch.object(sys, "argv", ["preflight", "inspect-bootstrap"]), patch(
            "builtins.print"
        ) as output, self.assertRaises(
            SystemExit
        ) as error:
            preflight.main()
        self.assertIn("unread/unverified", str(error.exception))
        self.assertFalse(json.loads(output.call_args.args[0])["allReadsSucceeded"])

    def test_actual_lowercase_insights_namespace_is_the_exact_registered_provider(self):
        actual = {"namespace": "microsoft.insights", "registrationState": "Registered"}
        report = self.bootstrap(provider_overrides={"Microsoft.Insights": actual})
        self.assertTrue(report["allReadsSucceeded"])
        self.assertEqual(report["providers"]["Microsoft.Insights"], "Registered")
        self.assertFalse(report["deploymentReady"])
        report = self.bootstrap(
            ("existingTestApp",), provider_overrides={"Microsoft.Insights": actual}
        )
        self.assertFalse(report["allReadsSucceeded"])
        self.assertEqual(
            {item["scope"] for item in report["readErrors"]}, {"existingTestApp"}
        )
        self.assertEqual(report["providers"]["Microsoft.Insights"], "Registered")

    def test_provider_case_normalization_preserves_exact_target_and_state_guards(self):
        invalid = [
            {"namespace": value, "registrationState": "Registered"}
            for value in (
                None,
                False,
                1,
                [],
                "",
                " Microsoft.Insights",
                "Microsoft.Insights.extra",
                "Microsoft.App",
            )
        ] + [
            {"namespace": "microsoft.insights", "registrationState": value}
            for value in (None, True, 1, "registered", "invalid")
        ]
        for value in invalid:
            with self.subTest(value=value):
                report = self.bootstrap(
                    provider_overrides={"Microsoft.Insights": value}
                )
                self.assertFalse(report["allReadsSucceeded"])
                self.assertNotIn("Microsoft.Insights", report["providers"])
                self.assertEqual(
                    {item["scope"] for item in report["readErrors"]},
                    {"Microsoft.Insights"},
                )
        report = self.bootstrap(
            provider_overrides={
                "Microsoft.KeyVault": {
                    "namespace": "Microsoft.\u212aeyVault",
                    "registrationState": "Registered",
                }
            }
        )
        self.assertFalse(report["allReadsSucceeded"])
        self.assertNotIn("Microsoft.KeyVault", report["providers"])

    def test_rest_rejects_mutation_arbitrary_urls_and_additional_arguments(self):
        forbidden = (
            ("rest", "--method", "POST", "--url", preflight.APP_URL),
            ("rest", "--method", "PATCH", "--url", preflight.APP_URL),
            (
                "rest",
                "--method",
                "GET",
                "--url",
                "https://management.azure.com/arbitrary",
            ),
            ("rest", "--method", "GET", "--url", preflight.APP_URL, "--body", "{}"),
        )
        for arguments in forbidden:
            with self.subTest(arguments=arguments), patch.object(
                subprocess, "run"
            ) as run, self.assertRaises(preflight.PreflightError):
                preflight.read_azure(*arguments)
            run.assert_not_called()
        result = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        for url in (*preflight.PERMISSION_URLS.values(), preflight.APP_URL):
            with patch.object(subprocess, "run", return_value=result) as run:
                preflight.read_azure("rest", "--method", "GET", "--url", url)
            self.assertEqual(
                run.call_args.args[0][1:6], ["rest", "--method", "GET", "--url", url]
            )
            self.assertIn("--subscription", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
