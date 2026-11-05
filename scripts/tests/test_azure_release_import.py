from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import azure_release_import as consumer


class ReleaseImportTests(unittest.TestCase):
    def test_windows_command_resolves_cmd_without_shell_and_keeps_redaction(self):
        private = "private-service-diagnostic"
        with patch.object(consumer.os, "name", "nt"), patch.object(
            consumer.shutil, "which", return_value=r"C:\Azure CLI\az.cmd"
        ), patch.object(
            consumer.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, '{"id":"expected"}', ""),
        ) as run:
            self.assertEqual(
                consumer.command(["az", "account", "show"]), {"id": "expected"}
            )
            self.assertEqual(
                run.call_args.args[0], [r"C:\Azure CLI\az.cmd", "account", "show"]
            )
            self.assertNotIn("shell", run.call_args.kwargs)
        with patch.object(consumer.os, "name", "nt"), patch.object(
            consumer.shutil, "which", return_value=None
        ), patch.object(consumer.subprocess, "run") as run, self.assertRaises(
            consumer.ReleaseImportError
        ):
            try:
                consumer.command(["az", "account", "show"])
            finally:
                run.assert_not_called()
        with patch.object(consumer.os, "name", "nt"), patch.object(
            consumer.shutil, "which", return_value=r"C:\Azure CLI\az.cmd"
        ), patch.object(
            consumer.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, "", private),
        ), self.assertRaises(
            consumer.ReleaseImportError
        ) as error:
            consumer.command(["az", "account", "show"])
        self.assertNotIn(private, str(error.exception))

    def setUp(self):
        self.environment = {
            "GITHUB_REPOSITORY": consumer.bundle.REPOSITORY,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_WORKFLOW_REF": f"{consumer.bundle.REPOSITORY}/{consumer.WORKFLOW}@refs/heads/main",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "999",
            "GITHUB_RUN_ATTEMPT": "3",
            "AZURE_SUBSCRIPTION_ID": consumer.FALLBACK_TARGET.subscription,
            "AZURE_TENANT_ID": consumer.FALLBACK_TARGET.tenant,
            "AZURE_CLIENT_ID": consumer.FALLBACK_TARGET.client,
        }
        environment = patch.dict(os.environ, self.environment, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = {
            "kind": "checked-release-candidate",
            "artifacts": [],
        }
        with consumer.candidate_identity():
            self.manifest.update(consumer.bundle.context())
            for component in consumer.bundle.COMPONENTS:
                path = self.root / consumer.bundle.archive_name(component)
                path.write_bytes(f"synthetic archive {component}".encode())
                self.manifest["artifacts"].append(
                    consumer.bundle.record_archive(
                        component,
                        path,
                        self.digest() if component in consumer.bundle.IMAGES else None,
                    )
                )
        self.write_manifest()
        checksum = patch.object(
            consumer,
            "CANDIDATE_MANIFEST_SHA256",
            consumer.bundle.file_hash(self.root / "release-manifest.json"),
        )
        checksum.start()
        self.addCleanup(checksum.stop)

    @staticmethod
    def digest(character="b"):
        return "sha256:" + character * 64

    def write_manifest(self):
        (self.root / "release-manifest.json").write_text(json.dumps(self.manifest))

    @staticmethod
    def candidate():
        return {
            "repository": {"full_name": consumer.bundle.REPOSITORY},
            "head_repository": {"full_name": consumer.bundle.REPOSITORY},
            "path": ".github/workflows/runtime-ci.yml",
            "id": int(consumer.CANDIDATE_RUN),
            "run_attempt": 1,
            "head_sha": consumer.CANDIDATE_SHA,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
        }

    def registry_responses(self):
        group_id = f"/subscriptions/{consumer.FALLBACK_TARGET.subscription}/resourceGroups/{consumer.GROUP}"
        return [
            {
                "id": consumer.FALLBACK_TARGET.subscription,
                "tenantId": consumer.FALLBACK_TARGET.tenant,
                "user": {
                    "type": "servicePrincipal",
                    "name": consumer.FALLBACK_TARGET.client,
                },
            },
            {
                "id": group_id,
                "name": consumer.GROUP,
                "tags": consumer.FALLBACK_TARGET.group_tags,
            },
            {
                "id": f"{group_id}/providers/Microsoft.ContainerRegistry/registries/{consumer.REGISTRY}",
                "name": consumer.REGISTRY,
                "loginServer": consumer.LOGIN_SERVER,
                "location": consumer.REGION,
                "sku": {"name": "Basic"},
                "adminUserEnabled": False,
                "provisioningState": "Succeeded",
                "tags": {
                    **consumer.FALLBACK_TARGET.group_tags,
                    "feature": "azure-llm-serving-demo",
                    "component": "shared",
                    "stage": "release",
                },
            },
        ]

    def metadata(self, locked=False):
        return {
            "digest": self.digest("c"),
            "changeableAttributes": {
                "writeEnabled": not locked,
                "deleteEnabled": not locked,
            },
        }

    def test_fixed_main_manual_workflow_required(self):
        consumer.validate_config()
        for field in (
            "GITHUB_REPOSITORY",
            "GITHUB_REF",
            "GITHUB_EVENT_NAME",
            "GITHUB_WORKFLOW_REF",
            "GITHUB_SHA",
        ):
            for value in ("", "unexpected"):
                with self.subTest(field=field, value=value), patch.dict(
                    os.environ, {field: value}
                ), self.assertRaises(consumer.ReleaseImportError):
                    consumer.validate_config()

    def test_candidate_exact_attempt_success_and_trusted_source_required(self):
        with patch.object(
            consumer, "command", return_value=self.candidate()
        ) as execute:
            consumer.validate_candidate()
        self.assertIn(
            f"/attempts/{consumer.CANDIDATE_ATTEMPT}", execute.call_args.args[0][-1]
        )
        for field in self.candidate():
            value = self.candidate()
            value[field] = (
                None if field in ("repository", "head_repository") else "unexpected"
            )
            with self.subTest(field=field), patch.object(
                consumer, "command", return_value=value
            ), self.assertRaises(consumer.ReleaseImportError):
                consumer.validate_candidate()
        for value in (None, [], {}):
            with patch.object(
                consumer, "command", return_value=value
            ), self.assertRaises(consumer.ReleaseImportError):
                consumer.validate_candidate()

    def test_identity_restored_after_success_failure_and_previously_unset_values(self):
        original = dict(os.environ)
        self.assertEqual(consumer.verify_archives(self.root), self.manifest)
        self.assertEqual(dict(os.environ), original)
        with self.assertRaisesRegex(
            RuntimeError, "test failure"
        ), consumer.candidate_identity():
            self.assertEqual(os.environ["GITHUB_RUN_ID"], consumer.CANDIDATE_RUN)
            raise RuntimeError("test failure")
        self.assertEqual(dict(os.environ), original)
        os.environ.pop("GITHUB_RUN_ATTEMPT")
        with consumer.candidate_identity():
            self.assertEqual(os.environ["GITHUB_RUN_ATTEMPT"], "1")
        self.assertNotIn("GITHUB_RUN_ATTEMPT", os.environ)

    def test_manifest_cannot_select_other_source_and_actual_changed_archive_refused(
        self,
    ):
        original = dict(os.environ)
        self.manifest["runId"] = "999"
        self.write_manifest()
        with self.assertRaises(consumer.ReleaseImportError):
            consumer.verify_archives(self.root)
        with patch.object(
            consumer,
            "CANDIDATE_MANIFEST_SHA256",
            consumer.bundle.file_hash(self.root / "release-manifest.json"),
        ), self.assertRaises(ValueError):
            consumer.verify_archives(self.root)
        self.assertEqual(dict(os.environ), original)
        self.manifest["runId"] = consumer.CANDIDATE_RUN
        self.write_manifest()
        (self.root / "backend.tar.gz").write_bytes(b"changed")
        with patch.object(consumer, "validate_candidate"), patch.object(
            consumer, "command"
        ) as execute, self.assertRaises(ValueError):
            consumer.consume(self.root, push=False)
        execute.assert_not_called()
        self.assertEqual(dict(os.environ), original)

    def test_manifest_symlink_refused(self):
        path = self.root / "release-manifest.json"
        path.unlink()
        path.symlink_to(self.root / "functions.zip")
        with self.assertRaises(consumer.ReleaseImportError):
            consumer.verify_archives(self.root)

    def test_verify_only_loads_all_seven_and_never_uses_azure(self):
        with patch.object(consumer, "validate_candidate"), patch.object(
            consumer, "command"
        ) as execute, patch.object(consumer, "inspect_image") as inspect, patch.object(
            consumer, "az"
        ) as azure:
            result = consumer.consume(self.root, push=False)
        self.assertTrue(result["downloadHashesAndDockerLoadVerified"])
        self.assertFalse(result["registryImportVerified"])
        self.assertFalse(result["resourcesOrRolesCreated"])
        self.assertEqual(len(result["images"]), 7)
        self.assertTrue(all("image" not in record for record in result["images"]))
        self.assertEqual(inspect.call_count, 7)
        loads = [
            call.args[0]
            for call in execute.call_args_list
            if call.args[0][:2] == ["docker", "load"]
        ]
        self.assertEqual(len(loads), 7)
        azure.assert_not_called()

    def test_image_inspection_rejects_mismatch_and_wrong_platform(self):
        good = {"Id": self.digest(), "Os": "linux", "Architecture": "amd64"}
        with patch.object(consumer, "command", return_value=[good]):
            consumer.inspect_image("fixed", self.digest())
        for field, value in (
            ("Id", self.digest("c")),
            ("Os", "windows"),
            ("Architecture", "arm64"),
        ):
            with self.subTest(field=field), patch.object(
                consumer, "command", return_value=[{**good, field: value}]
            ), self.assertRaises(consumer.ReleaseImportError):
                consumer.inspect_image("fixed", self.digest())
        for value in (None, {}, [], [good, good], ["invalid"]):
            with patch.object(
                consumer, "command", return_value=value
            ), self.assertRaises(consumer.ReleaseImportError):
                consumer.inspect_image("fixed", self.digest())

    def test_registry_exact_existing_owner_shape_and_principal(self):
        with patch.object(consumer, "az", side_effect=self.registry_responses()):
            consumer.validate_registry()
        for index, field in (
            (0, "id"),
            (0, "tenantId"),
            (0, "user"),
            (1, "id"),
            (1, "name"),
            (1, "tags"),
            (2, "id"),
            (2, "name"),
            (2, "loginServer"),
            (2, "location"),
            (2, "sku"),
            (2, "adminUserEnabled"),
            (2, "provisioningState"),
            (2, "tags"),
        ):
            responses = self.registry_responses()
            responses[index][field] = "foreign"
            with self.subTest(index=index, field=field), patch.object(
                consumer, "az", side_effect=responses
            ), self.assertRaises(consumer.ReleaseImportError):
                consumer.validate_registry()
        for field in ("AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID", "AZURE_CLIENT_ID"):
            with patch.dict(os.environ, {field: "foreign"}), patch.object(
                consumer, "az"
            ) as execute, self.assertRaises(consumer.ReleaseImportError):
                consumer.validate_registry()
            execute.assert_not_called()

    def test_push_refuses_already_present_different_image_without_overwrite(self):
        with patch.object(
            consumer, "az", side_effect=[["backend"], [consumer.TAG]]
        ) as azure, patch.object(consumer, "command") as execute, patch.object(
            consumer,
            "inspect_image",
            side_effect=consumer.ReleaseImportError("different image"),
        ), self.assertRaises(
            consumer.ReleaseImportError
        ):
            consumer.push_image("backend", self.digest())
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0][:2], ["docker", "pull"])
        self.assertEqual(azure.call_count, 2)

    def test_new_push_records_real_pull_digest_and_verifies_lock(self):
        with patch.object(
            consumer, "az", side_effect=[[], None, None, None, None]
        ) as azure, patch.object(consumer, "command") as execute, patch.object(
            consumer, "inspect_image"
        ) as inspect, patch.object(
            consumer,
            "image_metadata",
            side_effect=[self.metadata()] * 4 + [self.metadata(locked=True)] * 2,
        ):
            result = consumer.push_image("backend", self.digest())
        expected = f"{consumer.LOGIN_SERVER}/backend@{self.digest('c')}"
        self.assertEqual(result["image"], expected)
        self.assertEqual(result["imageConfigDigest"], self.digest())
        self.assertNotEqual(result["image"].split("@")[1], result["imageConfigDigest"])
        self.assertEqual(
            execute.call_args_list[-1].args[0], ["docker", "pull", expected]
        )
        self.assertEqual(inspect.call_count, 2)
        self.assertTrue(
            all(
                call.args == (expected, self.digest())
                for call in inspect.call_args_list
            )
        )
        promotion = azure.call_args_list[1].args
        self.assertEqual(promotion[:2], ("acr", "import"))
        self.assertNotIn("--force", promotion)
        self.assertIn(expected, promotion)
        self.assertIn(f"backend:{consumer.TAG}", promotion)
        for call in execute.call_args_list:
            if call.args[0][:2] == ["docker", "push"]:
                self.assertIn(f":{consumer.TAG}-upload-", call.args[0][-1])
                self.assertNotEqual(
                    call.args[0][-1], f"{consumer.LOGIN_SERVER}/backend:{consumer.TAG}"
                )
        lock = azure.call_args_list[-1].args
        self.assertIn("--write-enabled", lock)
        self.assertIn("--delete-enabled", lock)
        self.assertEqual(
            lock[-4:], ("--write-enabled", "false", "--delete-enabled", "false")
        )
        self.assertIn(f"backend@{self.digest('c')}", azure.call_args_list[-2].args)

    def test_concurrent_source_tag_creation_fails_no_force_without_overwrite_or_cleanup(
        self,
    ):
        conflict = consumer.ReleaseImportError("server-side NoForce conflict")
        with patch.object(
            consumer, "az", side_effect=[[], conflict]
        ) as azure, patch.object(consumer, "command") as execute, patch.object(
            consumer, "inspect_image"
        ), patch.object(
            consumer, "image_metadata", return_value=self.metadata()
        ), self.assertRaisesRegex(
            consumer.ReleaseImportError, "NoForce conflict"
        ):
            consumer.push_image("backend", self.digest())
        self.assertEqual(azure.call_count, 2)
        self.assertEqual(azure.call_args.args[:2], ("acr", "import"))
        self.assertNotIn("--force", azure.call_args.args)
        self.assertFalse(
            any(
                call.args[0][:2] == ["docker", "push"]
                and call.args[0][-1]
                == f"{consumer.LOGIN_SERVER}/backend:{consumer.TAG}"
                for call in execute.call_args_list
            )
        )

    def test_existing_identical_tag_is_pulled_verified_and_not_pushed(self):
        with patch.object(
            consumer, "az", side_effect=[["backend"], [consumer.TAG], None, None]
        ), patch.object(consumer, "command") as execute, patch.object(
            consumer, "inspect_image"
        ) as inspect, patch.object(
            consumer,
            "image_metadata",
            side_effect=[
                self.metadata(),
                self.metadata(locked=True),
                self.metadata(locked=True),
            ],
        ):
            consumer.push_image("backend", self.digest())
        self.assertFalse(
            any(
                call.args[0][:2] == ["docker", "push"]
                for call in execute.call_args_list
            )
        )
        self.assertEqual(inspect.call_count, 2)

    def test_changed_digest_or_missing_write_delete_lock_refused(self):
        for changed in (
            {**self.metadata(locked=True), "digest": self.digest("d")},
            self.metadata(),
            {"digest": self.digest("c"), "changeableAttributes": {}},
        ):
            with self.subTest(changed=changed), patch.object(
                consumer, "az", side_effect=[["backend"], [consumer.TAG], None, None]
            ), patch.object(consumer, "command"), patch.object(
                consumer, "inspect_image"
            ), patch.object(
                consumer,
                "image_metadata",
                side_effect=[self.metadata(), changed, self.metadata(locked=True)],
            ), self.assertRaises(
                consumer.ReleaseImportError
            ):
                consumer.push_image("backend", self.digest())
            with self.subTest(manifest=changed), patch.object(
                consumer, "az", side_effect=[["backend"], [consumer.TAG], None, None]
            ), patch.object(consumer, "command"), patch.object(
                consumer, "inspect_image"
            ), patch.object(
                consumer,
                "image_metadata",
                side_effect=[self.metadata(), self.metadata(locked=True), changed],
            ), self.assertRaises(
                consumer.ReleaseImportError
            ):
                consumer.push_image("backend", self.digest())

    def test_push_mode_requires_preloaded_exact_images_and_never_loads_after_login(
        self,
    ):
        with patch.object(consumer, "validate_candidate"), patch.object(
            consumer, "command"
        ) as execute, patch.object(consumer, "inspect_image") as inspect, patch.object(
            consumer, "validate_registry"
        ) as registry, patch.object(
            consumer, "az"
        ) as azure, patch.object(
            consumer, "push_image", return_value={"image": "synthetic"}
        ) as push:
            result = consumer.consume(self.root, push=True)
        self.assertEqual(inspect.call_count, 7)
        registry.assert_called_once()
        azure.assert_called_once_with(
            "acr", "login", "--name", consumer.REGISTRY, decode=False
        )
        self.assertEqual(push.call_count, 7)
        self.assertTrue(result["registryImportVerified"])
        self.assertFalse(
            any(
                call.args[0][:2] == ["docker", "load"]
                for call in execute.call_args_list
            )
        )

    def test_service_errors_are_explicit_and_never_print_raw_credentials(self):
        private = "synthetic-private-diagnostic-not-for-public-log"
        with patch.object(
            consumer.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, "", private),
        ), self.assertRaises(consumer.ReleaseImportError) as error:
            consumer.command(["az", "acr", "show"])
        self.assertNotIn(private, str(error.exception))
        for value in ("not json", ""):
            with patch.object(
                consumer.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, value, ""),
            ), self.assertRaises(consumer.ReleaseImportError):
                consumer.command(["az", "acr", "show"])

    def test_workflow_download_and_load_precede_opt_in_login_no_cloud_creation(self):
        source = (
            ROOT / ".github/workflows/azure-fallback-release-import.yml"
        ).read_text()
        self.assertEqual(consumer.CANDIDATE_RUN, "42081580674")
        self.assertEqual(consumer.CANDIDATE_ATTEMPT, "1")
        self.assertEqual(
            consumer.CANDIDATE_SHA, "8348c1b2af70b2607158811fc61c3d4ef6f53c29"
        )
        implementation = ast.parse(
            (ROOT / "scripts/azure_release_import.py").read_text()
        )
        manifest_pin = next(
            node.value
            for node in implementation.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "CANDIDATE_MANIFEST_SHA256"
                for target in node.targets
            )
        )
        self.assertEqual(
            ast.literal_eval(manifest_pin),
            "b3011dc15db6823c87cde660bd2f3dc1690ac710a008f3c4f72f393d1973b0ef",
        )
        self.assertIn("default: false", source)
        self.assertIn("environment: azure-e2e-fallback", source)
        self.assertIn("persist-credentials: false", source)
        self.assertIn("cancel-in-progress: false", source)
        self.assertIn(f"run-id: {consumer.CANDIDATE_RUN}", source)
        self.assertIn("name: release-manifest-1", source)
        self.assertIn("pattern: release-image-*-1", source)
        self.assertIn(f"name: functions-{consumer.CANDIDATE_SHA}", source)
        self.assertLess(
            source.index("Docker-load/config IDs without Azure access"),
            source.index("uses: azure/login@"),
        )
        self.assertIn("if: inputs.push_to_registry\n        uses: azure/login@", source)
        self.assertNotIn("pull_request:", source)
        self.assertNotIn("docker build", source)
        for forbidden in (
            "role assignment create",
            "acr create",
            "group delete",
            "get-access-token",
            "--expose-token",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
