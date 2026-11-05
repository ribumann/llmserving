from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
LOGIN = "azure/login@a457da9ea143d694b1b9c7c869ebb04ebe844ef5"
COMMON_KEYS = (
    "AZURE_CLIENT_ID",
    "AZURE_TENANT_ID",
    "AZURE_SUBSCRIPTION_ID",
    "RESOURCE_GROUP",
    "ACR_NAME",
    "CONTAINER_APP_NAME",
)


class DeploymentWorkflowTests(unittest.TestCase):
    def deployments(self):
        for name in ("backend", "frontend"):
            source = (ROOT / ".github" / "workflows" / f"{name}.yml").read_text()
            read_only, deployment = source.split("\n  deploy:\n", 1)
            keys = COMMON_KEYS + (("BACKEND_CONTAINER_APP_NAME",) if name == "frontend" else ())
            yield name, read_only, deployment, keys

    def mask_script(self, deployment):
        script = deployment.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
        return textwrap.dedent(script)

    def execute(self, deployment, environment):
        return subprocess.run(
            [sys.executable, "-c", self.mask_script(deployment)],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_privileged_actions_pinned_and_checkout_credentials_not_persisted(self):
        for name, _, deployment, _ in self.deployments():
            with self.subTest(workflow=name):
                self.assertIn(CHECKOUT, deployment)
                self.assertIn(LOGIN, deployment)
                self.assertNotIn("uses: azure/login@v", deployment)
                self.assertIn("persist-credentials: false", deployment)
                self.assertLess(deployment.index("python - <<'PY'"), deployment.index(LOGIN))
                for identifier in (
                    "AZURE_RESOURCE_GROUP",
                    "AZURE_ACR_NAME",
                    "AZURE_BACKEND_APP_NAME",
                    *(("AZURE_FRONTEND_APP_NAME",) if name == "frontend" else ()),
                ):
                    self.assertIn("${{ secrets." + identifier + " }}", deployment)
                    self.assertNotIn("${{ vars." + identifier + " }}", deployment)

    def test_deployment_remains_protected_opt_in_and_pr_checks_have_no_credentials(self):
        for name, read_only, deployment, _ in self.deployments():
            with self.subTest(workflow=name):
                self.assertIn("github.event_name == 'workflow_dispatch'", deployment)
                self.assertIn("github.ref == 'refs/heads/main'", deployment)
                self.assertIn("inputs.deploy", deployment)
                self.assertIn("vars.ENABLE_AZURE_DEPLOYMENT == 'true'", deployment)
                self.assertIn("environment: azure-deployment", deployment)
                self.assertNotIn("id-token: write", read_only)
                self.assertNotIn("secrets.AZURE_", read_only)

    def test_all_protected_identifiers_are_masked_before_login(self):
        for name, _, deployment, keys in self.deployments():
            environment = {key: f"test-{key.lower()}" for key in keys}
            with self.subTest(workflow=name):
                result = self.execute(deployment, environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.splitlines(),
                    [f"::add-mask::{environment[key]}" for key in keys],
                )
                self.assertEqual(result.stderr, "")
                for key in COMMON_KEYS[:3]:
                    self.assertIn("${{ env." + key + " }}", deployment)

    def test_each_missing_identifier_stops_before_login_without_dumping_values(self):
        for name, _, deployment, keys in self.deployments():
            for missing in keys:
                with self.subTest(workflow=name, missing=missing):
                    environment = {key: f"test-{key.lower()}" for key in keys if key != missing}
                    result = self.execute(deployment, environment)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        f"Missing protected deployment configuration: {missing}", result.stderr
                    )
                    self.assertEqual(
                        result.stdout.splitlines(),
                        [f"::add-mask::{environment[key]}" for key in keys if key != missing],
                    )
                    for value in environment.values():
                        self.assertNotIn(value, result.stderr)

    def test_mask_command_escapes_line_breaks_and_percent_signs(self):
        for name, _, deployment, keys in self.deployments():
            with self.subTest(workflow=name):
                environment = dict.fromkeys(keys, "test-value")
                environment[keys[0]] = "test%\r\n::warning::not-a-workflow-command"
                result = self.execute(deployment, environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.splitlines()[0],
                    "::add-mask::test%25%0D%0A::warning::not-a-workflow-command",
                )
                self.assertEqual(len(result.stdout.splitlines()), len(keys))

    def test_resolved_backend_hostname_is_masked_before_later_step_environment(self):
        frontend = next(
            deployment for name, _, deployment, _ in self.deployments() if name == "frontend"
        )
        self.assertLess(
            frontend.index('echo "::add-mask::$fqdn"'), frontend.index('echo "fqdn=$fqdn"')
        )


if __name__ == "__main__":
    unittest.main()
