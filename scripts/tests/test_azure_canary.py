from __future__ import annotations

import copy
import os
import subprocess
import unittest
from unittest.mock import patch

from scripts import azure_canary as canary


class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "AZURE_SUBSCRIPTION_ID": "test-subscription",
            "AZURE_TENANT_ID": "test-tenant",
            "AZURE_CANARY_REGION": "polandcentral",
            "AZURE_CANARY_RESOURCE_GROUP": canary.RESOURCE_GROUP,
            "GITHUB_REPOSITORY": "ribumann/llmserving",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_SHA": "a" * 40,
        }
        self.env_patch = patch.dict(os.environ, self.environment, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.context = canary.Context.from_environment()
        self.account = {"id": "test-subscription", "tenantId": "test-tenant"}
        self.group = {
            "id": f"/subscriptions/test-subscription/resourceGroups/{canary.RESOURCE_GROUP}",
            "name": canary.RESOURCE_GROUP,
            "location": "polandcentral",
            "tags": dict(canary.GROUP_TAGS),
        }
        self.tags = {
            **canary.GROUP_TAGS,
            "purpose": canary.PURPOSE,
            "repository": "ribumann/llmserving",
            "runId": "123",
            "runAttempt": "1",
            "sourceSha": "a" * 40,
        }
        self.owned_identity = {
            "id": f"{self.group['id']}/providers/{canary.IDENTITY_TYPE}/{canary.IDENTITY_NAME}",
            "name": canary.IDENTITY_NAME,
            "type": canary.IDENTITY_TYPE,
            "location": "polandcentral",
            "tags": self.tags,
        }
        self.identity = copy.deepcopy(self.owned_identity)
        self.run = {
            "repository": {"full_name": "ribumann/llmserving"},
            "head_repository": {"full_name": "ribumann/llmserving"},
            "path": canary.WORKFLOW_PATH,
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "run_attempt": 1,
            "status": "completed",
        }
        self.calls = []
        self.keep_after_delete = False
        self.command_patch = patch.object(canary, "command_json", side_effect=self.command)
        self.command_patch.start()
        self.addCleanup(self.command_patch.stop)

    def command(self, arguments):
        self.calls.append(arguments)
        if arguments[0] == "gh":
            return self.run
        self.assertIn("--subscription", arguments)
        self.assertEqual(arguments[arguments.index("--subscription") + 1], "test-subscription")
        operation = arguments[1:3]
        if operation == ["account", "show"]:
            return self.account
        if operation == ["group", "show"]:
            return self.group
        if operation == ["identity", "list"]:
            return [self.identity] if self.identity else []
        if operation == ["identity", "create"]:
            self.identity = copy.deepcopy(self.owned_identity)
            return self.identity
        if operation == ["identity", "delete"]:
            self.assertEqual(arguments[arguments.index("--name") + 1], canary.IDENTITY_NAME)
            if not self.keep_after_delete:
                self.identity = None
            return None
        self.fail(f"Unexpected command: {arguments}")

    def assert_no_mutations(self):
        self.assertFalse(
            any(
                call[1:3] in (["identity", "delete"], ["identity", "create"]) for call in self.calls
            )
        )

    def test_create_and_verify(self):
        self.identity = None
        canary.create(self.context)
        self.assertEqual(self.identity["tags"], self.tags)

    def test_existing_canary_is_not_overwritten(self):
        with self.assertRaises(canary.CanaryError):
            canary.create(self.context)
        self.assert_no_mutations()

    def test_cleanup_deletes_exact_identity_then_verifies_absence(self):
        canary.cleanup(self.context, "123")
        self.assertIsNone(self.identity)
        self.assertEqual(self.calls[-1][1:3], ["identity", "list"])

    def test_scheduled_cleanup_validates_resource_run(self):
        canary.cleanup(self.context, "")
        self.assertTrue(any(call[0] == "gh" for call in self.calls))
        self.assertIsNone(self.identity)

    def test_explicit_main_ref_in_workflow_path_is_supported(self):
        self.run["path"] = f"{canary.WORKFLOW_PATH}@main"
        canary.cleanup(self.context, "123")
        self.assertIsNone(self.identity)

    def test_absence_is_idempotent(self):
        self.identity = None
        canary.cleanup(self.context, "123")
        self.assert_no_mutations()

    def test_different_run_is_preserved(self):
        with self.assertRaises(canary.CanaryError):
            canary.cleanup(self.context, "999")
        self.assert_no_mutations()

    def test_incomplete_or_untrusted_owning_run_is_preserved(self):
        mutations = [
            {"status": "in_progress"},
            {"status": "queued"},
            {"head_branch": "feature"},
            {"event": "pull_request"},
            {"head_sha": "b" * 40},
            {"run_attempt": 2},
            {"path": ".github/workflows/other.yml"},
            {"path": f"{canary.WORKFLOW_PATH}@feature"},
            {"repository": {"full_name": "someone/other"}},
            {"head_repository": {"full_name": "someone/other"}},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                original = self.run.copy()
                self.run.update(mutation)
                with self.assertRaises(canary.CanaryError):
                    canary.cleanup(self.context, "123")
                self.assert_no_mutations()
                self.run = original

    def test_scope_mismatch_prevents_all_mutation(self):
        for target, key, value in [
            (self.account, "id", "other"),
            (self.account, "tenantId", "other"),
            (self.group, "id", "/different"),
            (self.group, "name", "different"),
            (self.group, "location", "other"),
            (self.group, "tags", {}),
            (self.group, "tags", {**canary.GROUP_TAGS, "unexpected": "tag"}),
        ]:
            with self.subTest(key=key, value=value):
                original = target[key]
                target[key] = value
                with self.assertRaises(canary.CanaryError):
                    canary.cleanup(self.context, "123")
                self.assert_no_mutations()
                target[key] = original

    def test_identity_mismatch_prevents_deletion(self):
        for key, value in [
            ("id", "/different"),
            ("type", "Microsoft.Compute/virtualMachines"),
            ("location", "other"),
            ("tags", {}),
            ("tags", {**self.tags, "purpose": "other"}),
            ("tags", {**self.tags, "runId": "../123"}),
            ("tags", {**self.tags, "runAttempt": "0"}),
            ("tags", {**self.tags, "sourceSha": "not-a-sha"}),
        ]:
            with self.subTest(key=key, value=value):
                self.identity = {**self.owned_identity, key: value}
                with self.assertRaises(canary.CanaryError):
                    canary.cleanup(self.context, "123")
                self.assert_no_mutations()

    def test_delete_must_verify_absence(self):
        self.keep_after_delete = True
        with self.assertRaisesRegex(canary.CanaryError, "did not verify"):
            canary.cleanup(self.context, "123")

    def test_creation_requires_explicit_dispatch(self):
        os.environ["GITHUB_EVENT_NAME"] = "pull_request"
        with self.assertRaises(canary.CanaryError):
            canary.create(self.context)
        self.assert_no_mutations()

    def test_environment_is_main_and_fixed_scope_only(self):
        for key, value in [
            ("GITHUB_REF", "refs/heads/feature"),
            ("GITHUB_REPOSITORY", "someone/other"),
            ("AZURE_CANARY_RESOURCE_GROUP", "production"),
            ("AZURE_SUBSCRIPTION_ID", ""),
        ]:
            with self.subTest(key=key):
                with patch.dict(os.environ, {key: value}):
                    with self.assertRaises(canary.CanaryError):
                        canary.Context.from_environment()
                self.assert_no_mutations()

    def test_command_error_is_not_treated_as_absence(self):
        self.command_patch.stop()
        with patch.object(
            subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["az"], returncode=1, stdout="", stderr="authorization denied"
            ),
        ):
            with self.assertRaisesRegex(canary.CanaryError, "authorization denied"):
                canary.command_json(["az", "identity", "list"])

    def test_successful_empty_delete_response_is_supported(self):
        self.command_patch.stop()
        with patch.object(
            subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["az"], returncode=0, stdout="", stderr=""
            ),
        ):
            self.assertIsNone(canary.command_json(["az", "identity", "delete"]))


if __name__ == "__main__":
    unittest.main()
