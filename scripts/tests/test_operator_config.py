from __future__ import annotations

from scripts.tests import operator_fixture

import ast
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

import operator_config as config


class OperatorConfigurationTests(unittest.TestCase):
    def setUp(self):
        config._configuration.cache_clear()
        self.addCleanup(config._configuration.cache_clear)
        environment = patch.dict(
            os.environ,
            {"LLM_SERVING_OPERATOR_CONFIG": json.dumps(operator_fixture.CONFIG)},
        )
        environment.start()
        self.addCleanup(environment.stop)

    def test_explicit_config_is_frozen_for_the_process(self):
        self.assertEqual(config.setting("subscription_id"), operator_fixture.CONFIG["subscription_id"])
        os.environ["LLM_SERVING_OPERATOR_CONFIG"] = "{}"
        self.assertEqual(config.setting("subscription_id"), operator_fixture.CONFIG["subscription_id"])

    def test_workflow_masks_identifiers_without_masking_single_digit_counters(self):
        output = StringIO()
        stdout = StringIO()
        with (
            patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}),
            redirect_stderr(output),
            redirect_stdout(stdout),
        ):
            config.setting("subscription_id")
        self.assertEqual(stdout.getvalue(), "")
        lines = output.getvalue().splitlines()
        self.assertIn("::add-mask::" + operator_fixture.CONFIG["subscription_id"], lines)
        for key in ("candidate_attempt", "shared_serial", "operator_serial"):
            self.assertNotIn("::add-mask::" + operator_fixture.CONFIG[key], lines)

    def test_missing_unknown_malformed_and_duplicate_inputs_fail_closed(self):
        for raw in (
            "", "null", "[]", "{", '{"repository": "example/demo", "repository": "other/demo"}',
            '{"unknown": "value"}', '{"subscription_id": null}',
            '{"subscription_id": "not-a-uuid"}', '{"resource_prefix": "../outside"}',
            '{"candidate_run": "1; shell"}', '{"shared_serial": -1}',
        ):
            with self.subTest(raw=raw):
                config._configuration.cache_clear()
                os.environ["LLM_SERVING_OPERATOR_CONFIG"] = raw
                with self.assertRaises(config.OperatorConfigurationError):
                    config.setting("subscription_id")
        os.environ["LLM_SERVING_OPERATOR_CONFIG"] = "{}"
        config._configuration.cache_clear()
        with self.assertRaisesRegex(config.OperatorConfigurationError, "Missing operator configuration field"):
            config.setting("subscription_id")

    def test_cli_imports_fail_before_any_cloud_command_without_configuration(self):
        scripts = Path(__file__).resolve().parents[1]
        environment = {key: value for key, value in os.environ.items()
                       if key != "LLM_SERVING_OPERATOR_CONFIG"}
        for name in (
            "app_bootstrap.py", "azure_canary.py", "azure_disk_probe.py",
            "azure_release_import.py", "azure_shared_lifecycle.py",
            "azure_operator_access.py", "validate_shared_reconcile.py",
            "validate_operator_reconcile.py",
        ):
            with self.subTest(script=name):
                result = subprocess.run(
                    [sys.executable, str(scripts / name), "--help"],
                    env=environment, capture_output=True, text=True, timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Missing LLM_SERVING_OPERATOR_CONFIG", result.stderr)

    def test_new_process_derives_resources_from_a_different_reviewed_target(self):
        selected = {
            **operator_fixture.CONFIG,
            "repository": "second/example",
            "subscription_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "resource_prefix": "secondexample",
            "shared_group": "rg-second-shared",
            "control_group": "rg-second-control",
            "registry_name": "secondexampleacr",
            "state_account": "secondexamplestate",
        }
        environment = {
            **os.environ,
            "LLM_SERVING_OPERATOR_CONFIG": json.dumps(selected),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "GITHUB_ACTIONS": "false",
        }
        result = subprocess.run(
            [sys.executable, "-c",
             "import json, app_bootstrap as b, validate_operator_access_plan as o; "
             "print(json.dumps([b.SUBSCRIPTION, b.ENVIRONMENT, o.ACCOUNT, o.VNET]))"],
            env=environment, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        subscription, control, account, network = json.loads(result.stdout)
        root = f"/subscriptions/{selected['subscription_id']}/resourceGroups/"
        self.assertEqual(subscription, selected["subscription_id"])
        self.assertEqual(control, root + "rg-second-control/providers/Microsoft.App/managedEnvironments/secondexample-cae")
        self.assertEqual(account, root + "rg-second-shared/providers/Microsoft.Storage/storageAccounts/secondexamplestate")
        self.assertEqual(network, root + "rg-second-shared/providers/Microsoft.Network/virtualNetworks/secondexample-shared-vnet")

    def test_production_scripts_do_not_embed_literal_cloud_identity_uuids(self):
        pattern = re.compile(config.UUID)
        for path in Path(__file__).resolve().parents[1].glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(pattern.search(node.value), path.name)

    def test_all_azure_operator_workflows_are_opt_in_and_use_protected_config(self):
        root = Path(__file__).resolve().parents[2]
        for path in (root / ".github" / "workflows").glob("azure-*.yml"):
            source = path.read_text()
            with self.subTest(workflow=path.name):
                self.assertIn("github.repository == vars.AZURE_OPERATOR_REPOSITORY", source)
                self.assertIn("vars.ENABLE_AZURE_OPERATOR_WORKFLOWS == 'true'", source)
                self.assertIn("LLM_SERVING_OPERATOR_CONFIG: ${{ secrets.LLM_SERVING_OPERATOR_CONFIG }}", source)
                if path.name in {"azure-fallback-shared.yml", "azure-fallback-shared-cleanup.yml"}:
                    self.assertIn('runs-on: [self-hosted, linux, x64, "${{ vars.AZURE_OPERATOR_RUNNER_LABEL }}"]', source)
                    self.assertIn("vars.AZURE_OPERATOR_RUNNER_LABEL != ''", source)

    def test_dependency_lockfiles_use_public_registry_tarballs(self):
        root = Path(__file__).resolve().parents[2]
        for directory in ("frontend", "e2e"):
            lock = json.loads((root / directory / "package-lock.json").read_text())
            for name, package in lock["packages"].items():
                if "resolved" in package:
                    with self.subTest(directory=directory, package=name):
                        self.assertTrue(package["resolved"].startswith("https://registry.npmjs.org/"))

    def test_proxy_offline_fixture_hosts_are_consistent(self):
        root = Path(__file__).resolve().parents[2]
        proxy = root / "tools" / "private_proxy"
        hosts = (proxy / "hosts.txt").read_text().splitlines()
        self.assertEqual(hosts, [
            "examplestate123abc.blob.core.windows.net",
            "llmexample-kv-123abc.vault.azure.net",
            "examplefunc456def.blob.core.windows.net",
        ])
        for path in (
            proxy / "smoke.py",
            root / ".github" / "workflows" / "private-proxy-ci.yml",
        ):
            for host in hosts:
                self.assertIn(host, path.read_text())
        self.assertIn(hosts[1], (proxy / "vault_fixture.go").read_text())
