from __future__ import annotations

from scripts.tests import operator_fixture  # noqa: F401

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import azure_shared_bridge as bridge
import test_shared_plan as fixture


class SharedBridgeTests(unittest.TestCase):
    def test_windows_checkpoint_inherits_then_verifies_parent_acl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / "module"
            second = root / "second"
            module.mkdir()
            second.mkdir()
            with patch.object(bridge.os, "name", "nt"), patch.object(
                bridge, "private_directory"
            ) as verify, patch.object(Path, "mkdir") as mkdir:
                # Abort after the new child's ACL check, before any file write.
                verify.side_effect = [
                    None,
                    bridge.shared.SharedError("verified-test-stop"),
                ]
                with self.assertRaisesRegex(
                    bridge.shared.SharedError, "verified-test-stop"
                ):
                    bridge.backup(module, second, "checkpoint")
                mkdir.assert_called_once_with(mode=0o777, exist_ok=False)
                self.assertEqual(verify.call_args_list[0].args, (second,))
                self.assertEqual(
                    verify.call_args_list[1].args, (second / "checkpoint",)
                )

    def test_deadline_and_arming_are_independent_of_blob_access(self):
        future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

        def metadata(arguments):
            name = arguments[-1].split("/")[-1]
            return {"name": name, "value": "true" if name == bridge.ARMED else future}

        with patch.dict(os.environ, {}, clear=True), patch.object(
            bridge, "command", side_effect=metadata
        ), patch.object(bridge.shared, "blob") as blob:
            bridge.configuration(creating=True)
            blob.assert_not_called()
        for value in ("false", ""):
            with patch.dict(
                os.environ,
                {
                    "GITHUB_ACTIONS": "true",
                    bridge.ARMED: value,
                    bridge.DEADLINE: future,
                },
                clear=True,
            ), self.assertRaises(bridge.shared.SharedError):
                bridge.configuration()
        expired = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        with patch.dict(
            os.environ,
            {"GITHUB_ACTIONS": "true", bridge.ARMED: "true", bridge.DEADLINE: expired},
            clear=True,
        ):
            bridge.configuration()
            with self.assertRaises(bridge.shared.SharedError):
                bridge.configuration(creating=True)

    def test_backups_have_hash_lineage_serial_and_private_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / "module"
            second = root / "second"
            module.mkdir(mode=0o700)
            second.mkdir(mode=0o700)
            payload = json.dumps(
                {"lineage": "synthetic-lineage", "serial": 12, "resources": []}
            ).encode()
            (module / "terraform.tfstate").write_bytes(payload)
            (module / "main.tf").write_text("# source\n")
            (module / "release_override.tf.json").write_text(
                json.dumps(bridge.PROVIDER_OVERRIDE)
            )
            before = bridge.backup(module, second, "before")
            self.assertEqual(
                before["state"],
                {
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "lineage": "synthetic-lineage",
                    "serial": 12,
                },
            )
            self.assertEqual(
                (second / "before/terraform.tfstate").read_bytes(), payload
            )
            self.assertEqual(
                (second / "before/terraform.tfstate").stat().st_mode & 0o077, 0
            )
            (module / "terraform.tfstate").write_text("changed")
            self.assertEqual(
                (second / "before/terraform.tfstate").read_bytes(), payload
            )
            with self.assertRaises(FileExistsError):
                bridge.backup(module, second, "before")
            with self.assertRaises(bridge.shared.SharedError):
                bridge.backup(module, module, "nested")

    def test_backup_rejects_broad_directory_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            with self.assertRaises(bridge.shared.SharedError):
                bridge.private_directory(root)
            root.chmod(0o700)
            source = root / "source"
            source.mkdir(mode=0o700)
            (source / "terraform.tfstate").symlink_to(root / "foreign")
            with self.assertRaises(bridge.shared.SharedError):
                bridge.backup(source, root, "snapshot")

    def test_attached_foreign_subnet_resource_blocks_cascade(self):
        for field in (
            "ipConfigurations",
            "privateEndpoints",
            "serviceAssociationLinks",
            "resourceNavigationLinks",
        ):
            record = {"properties": {field: [{"id": "/foreign"}]}}
            with self.subTest(field=field), self.assertRaises(
                bridge.shared.SharedError
            ):
                bridge.reject_attached_children({"azurerm_subnet.gpu": record})
        bridge.reject_attached_children(
            {
                "azurerm_subnet.private_endpoints": {
                    "properties": {
                        "privateEndpoints": [
                            {
                                "id": bridge.scope.RESOURCES[
                                    "azurerm_private_endpoint.vault"
                                ]["id"]
                            }
                        ],
                    }
                }
            }
        )

    def test_predeadline_arm_checks_without_deletion_or_blob(self):
        with patch.object(
            bridge, "configuration", return_value=datetime.now(UTC) + timedelta(hours=1)
        ), patch.object(bridge, "identity"), patch.object(
            bridge.shared, "dependencies_absent"
        ), patch.object(
            bridge.shared, "inventory", return_value={}
        ), patch.object(
            bridge, "az"
        ) as mutate, patch.object(
            bridge.shared, "blob"
        ) as blob, contextlib.redirect_stdout(
            io.StringIO()
        ):
            bridge.emergency_cleanup(force=False)
            mutate.assert_not_called()
            blob.assert_not_called()

    def test_arm_cleanup_deletes_exact_resource_and_preserves_bootstrap(self):
        address = "azurerm_container_registry.shared"
        with patch.object(
            bridge,
            "configuration",
            return_value=datetime.now(UTC) - timedelta(minutes=1),
        ), patch.object(bridge, "identity"), patch.object(
            bridge.shared, "dependencies_absent"
        ), patch.object(
            bridge.shared, "inventory"
        ) as inventory, patch.object(
            bridge, "az"
        ) as mutate, contextlib.redirect_stdout(
            io.StringIO()
        ):
            present = True

            def resources(*args, **kwargs):
                return {address: {}} if present else {}

            def delete(*args, **kwargs):
                nonlocal present
                self.assertEqual(args[:3], ("rest", "--method", "DELETE"))
                self.assertIn(bridge.scope.RESOURCES[address]["id"], args[-1])
                self.assertNotIn("storageAccounts", args[-1])
                present = False

            inventory.side_effect = resources
            mutate.side_effect = delete
            bridge.emergency_cleanup(force=False)
            self.assertEqual(mutate.call_count, 1)

    def test_pending_deletion_is_not_claimed_complete(self):
        address = "azurerm_container_registry.shared"
        with patch.object(
            bridge,
            "configuration",
            return_value=datetime.now(UTC) - timedelta(minutes=1),
        ), patch.object(bridge, "identity"), patch.object(
            bridge.shared, "dependencies_absent"
        ), patch.object(
            bridge.shared, "inventory", return_value={address: {}}
        ), patch.object(
            bridge, "az"
        ) as mutate, self.assertRaisesRegex(
            bridge.shared.SharedError, "pending"
        ):
            try:
                bridge.emergency_cleanup(force=False)
            finally:
                self.assertEqual(mutate.call_count, 1)

    def test_foreign_inventory_or_dependencies_prevent_any_delete(self):
        for method in ("inventory", "dependencies_absent"):
            with patch.object(
                bridge,
                "configuration",
                return_value=datetime.now(UTC) - timedelta(minutes=1),
            ), patch.object(bridge, "identity"), patch.object(
                bridge.shared, "inventory", return_value={}
            ) as inventory, patch.object(
                bridge.shared, "dependencies_absent"
            ) as dependencies, patch.object(
                bridge, "az"
            ) as mutate, self.assertRaises(
                bridge.shared.SharedError
            ):
                (inventory if method == "inventory" else dependencies).side_effect = (
                    bridge.shared.SharedError("unverified")
                )
                try:
                    bridge.emergency_cleanup(force=False)
                finally:
                    mutate.assert_not_called()

    def test_all_primary_roots_have_cleanup_order_no_bootstrap_or_role(self):
        subnets = {
            key for key in bridge.scope.RESOURCES if key.startswith("azurerm_subnet.")
        }
        self.assertEqual(
            set(bridge.DELETE_ORDER), set(bridge.scope.RESOURCES) - subnets
        )
        self.assertEqual(len(bridge.DELETE_ORDER), len(set(bridge.DELETE_ORDER)))
        self.assertLess(
            bridge.DELETE_ORDER.index("azurerm_private_endpoint.vault"),
            bridge.DELETE_ORDER.index("azurerm_virtual_network.shared"),
        )
        self.assertLess(
            bridge.DELETE_ORDER.index("azurerm_virtual_network.shared"),
            bridge.DELETE_ORDER.index("azurerm_nat_gateway.shared"),
        )
        self.assertLess(
            bridge.DELETE_ORDER.index("azurerm_nat_gateway.shared"),
            bridge.DELETE_ORDER.index("azurerm_public_ip.nat"),
        )

    def test_no_local_apply_without_recent_arming_run(self):
        with patch.object(bridge, "configuration"), patch.object(
            bridge, "command", return_value={"id": 123}
        ), patch.object(bridge, "run_saved_plan") as execute, self.assertRaises(
            bridge.shared.SharedError
        ):
            try:
                bridge.local_apply(Path("plan"), Path("log"), Path("backup"), "123")
            finally:
                execute.assert_not_called()

    def test_dns_foreign_records_and_incomplete_enumeration_block_zone_delete(self):
        address = "azurerm_private_dns_zone.vault"
        identifier = bridge.scope.RESOURCES[address]["id"]
        soa = {
            "id": f"{identifier}/SOA/@",
            "type": "Microsoft.Network/privateDnsZones/SOA",
            "name": "@",
        }
        with patch.object(bridge, "az", return_value={"value": [soa]}):
            bridge.verify_dns_records({address: {}})
        for response in (
            {"value": [soa, {"id": f"{identifier}/A/foreign", "name": "foreign"}]},
            {"value": [soa], "nextLink": "https://more"},
            {"value": []},
        ):
            with patch.object(bridge, "az", return_value=response), self.assertRaises(
                bridge.shared.SharedError
            ):
                bridge.verify_dns_records({address: {}})

    def test_local_apply_checkpoints_success_and_partial_failure_without_retry(self):
        run = {
            "id": 123,
            "run_attempt": 1,
            "path": bridge.WORKFLOW,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "head_repository": {"full_name": bridge.shared.REPOSITORY},
            "created_at": datetime.now(UTC).isoformat(),
        }
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                module = root / "module"
                second = root / "second"
                module.mkdir(mode=0o700)
                second.mkdir(mode=0o700)
                (module / "main.tf").write_text("# source\n")
                (module / "release_override.tf.json").write_text(
                    json.dumps(bridge.PROVIDER_OVERRIDE)
                )

                def apply(*args, module=module, fail=fail, **kwargs):
                    kwargs["validator"](
                        fixture.SharedPlanTests().plan(), bridge.shared.GROUP
                    )
                    (module / "terraform.tfstate").write_text(
                        json.dumps(
                            {
                                "lineage": "synthetic-only",
                                "serial": 1,
                                "resources": [],
                            }
                        )
                    )
                    if fail:
                        raise bridge.PlanRejected("simulated partial failure")

                with patch.object(bridge, "configuration"), patch.object(
                    bridge,
                    "command",
                    side_effect=[run, {"terraform_version": "1.16.6"}],
                ), patch.object(bridge, "identity"), patch.object(
                    bridge.shared, "dependencies_absent"
                ), patch.object(
                    bridge.shared, "inventory"
                ), patch.object(
                    bridge, "az", return_value=[]
                ), patch.object(
                    Path, "cwd", return_value=module
                ), patch.object(
                    bridge, "run_saved_plan", side_effect=apply
                ) as execute, contextlib.redirect_stdout(
                    io.StringIO()
                ):
                    if fail:
                        with self.assertRaises(bridge.PlanRejected):
                            bridge.local_apply(
                                root / "plan", root / "log", second, "123"
                            )
                    else:
                        bridge.local_apply(root / "plan", root / "log", second, "123")
                    self.assertEqual(execute.call_count, 1)
                checkpoints = sorted(second.iterdir())
                self.assertEqual(len(checkpoints), 2)
                after = next(
                    path for path in checkpoints if path.name.endswith("-after")
                )
                metadata = json.loads((after / "checkpoint.json").read_text())
                self.assertEqual(metadata["state"]["lineage"], "synthetic-only")
                self.assertEqual(metadata["state"]["serial"], 1)
                self.assertTrue((after / "terraform.tfstate").is_file())

    def test_persisted_nondefault_workspace_rejected_before_apply(self):
        run = {
            "id": 123,
            "run_attempt": 1,
            "path": bridge.WORKFLOW,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "head_repository": {"full_name": bridge.shared.REPOSITORY},
            "created_at": datetime.now(UTC).isoformat(),
        }
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory)
            (module / ".terraform").mkdir()
            (module / ".terraform/environment").write_text("foreign")
            (module / "release_override.tf.json").write_text(
                json.dumps(bridge.PROVIDER_OVERRIDE)
            )
            with patch.object(bridge, "configuration"), patch.object(
                bridge, "command", return_value=run
            ), patch.object(bridge, "identity"), patch.object(
                bridge.shared, "dependencies_absent"
            ), patch.object(
                bridge.shared, "inventory"
            ), patch.object(
                bridge, "az", return_value=[]
            ), patch.object(
                Path, "cwd", return_value=module
            ), patch.object(
                bridge, "run_saved_plan"
            ) as execute, self.assertRaisesRegex(
                bridge.shared.SharedError, "default workspace"
            ):
                try:
                    bridge.local_apply(
                        module / "plan", module / "log", module / "second", "123"
                    )
                finally:
                    execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
