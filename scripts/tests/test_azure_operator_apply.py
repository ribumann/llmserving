from __future__ import annotations

from scripts.tests import operator_fixture  # noqa: F401

import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import azure_operator_apply as apply


class OperatorApplyTests(unittest.TestCase):
    def test_exact_cleanup_arming_and_wrong_run_rejected(self):
        now = datetime.now(UTC)
        selected = {
            "root_certificate_sha256": "a" * 64,
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
        variables = {
            "OPERATOR_ACCESS_CLEANUP_ARMED": "true",
            "OPERATOR_ACCESS_EXPIRES_AT": selected["expires_at"],
            "OPERATOR_ACCESS_ROOT_SHA256": selected["root_certificate_sha256"],
        }
        run = {
            "id": 123,
            "run_attempt": 1,
            "path": apply.cleanup.WORKFLOW,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "head_repository": {"full_name": apply.bridge.shared.REPOSITORY},
            "created_at": now.isoformat(),
        }
        jobs = {
            "total_count": 1,
            "jobs": [
                {
                    "name": "cleanup",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": name, "status": "completed", "conclusion": "success"}
                        for name in (
                            "Run azure/login@a457da9ea143d694b1b9c7c869ebb04ebe844ef5",
                            "Verify fixed ARM cleanup and remove only eligible operator resources",
                        )
                    ],
                }
            ],
        }
        with (
            patch.object(apply, "variable", side_effect=variables.__getitem__),
            patch.object(
                apply.bridge, "configuration", return_value=now + timedelta(hours=2)
            ),
            patch.object(apply, "command", side_effect=[run, jobs]),
        ):
            apply.arming(selected, "123")
            for changed_jobs in (
                {"total_count": 0, "jobs": []},
                {
                    "total_count": 1,
                    "jobs": [{**jobs["jobs"][0], "conclusion": "skipped"}],
                },
                {"total_count": 1, "jobs": [{**jobs["jobs"][0], "steps": []}]},
            ):
                with (
                    patch.object(apply, "command", side_effect=[run, changed_jobs]),
                    self.assertRaises(apply.bridge.shared.SharedError),
                ):
                    apply.arming(selected, "123")
            for key, value in (
                ("run_attempt", 2),
                ("conclusion", "failure"),
                ("head_branch", "foreign"),
                ("created_at", (now - timedelta(hours=1)).isoformat()),
            ):
                changed = {**run, key: value}
                with (
                    patch.object(apply, "command", return_value=changed),
                    self.assertRaises(apply.bridge.shared.SharedError),
                ):
                    apply.arming(selected, "123")
        for name, value in (
            ("OPERATOR_ACCESS_CLEANUP_ARMED", "false"),
            ("OPERATOR_ACCESS_ROOT_SHA256", "b" * 64),
        ):
            changed = {**variables, name: value}
            with (
                patch.object(apply, "variable", side_effect=changed.__getitem__),
                self.assertRaises(apply.bridge.shared.SharedError),
            ):
                apply.arming(selected, "123")

    def test_local_context_rejects_redirected_workspace_and_backend(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {}, clear=True),
            patch.object(apply.bridge, "private_directory"),
            patch.object(
                apply, "command", return_value={"terraform_version": "1.16.6"}
            ),
        ):
            module = Path(temporary)
            data = module / ".terraform"
            data.mkdir()
            apply.local_context(module)
            (data / "environment").write_text("foreign")
            with self.assertRaises(apply.bridge.shared.SharedError):
                apply.local_context(module)
            (data / "environment").write_text("default")
            for backend in (
                {"type": "azurerm"},
                {"type": "local", "config": {"path": "/elsewhere"}},
                {"type": "local", "config": {"workspace_dir": "/elsewhere"}},
            ):
                (data / "terraform.tfstate").write_text(
                    json.dumps({"backend": backend})
                )
                with self.assertRaises(apply.bridge.shared.SharedError):
                    apply.local_context(module)

    def test_failed_apply_still_retains_after_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = {
                "root_certificate_public_data": "public",
                "root_certificate_sha256": "a" * 64,
                "expires_at": "2030-01-01T00:00:00Z",
            }
            target = root / "target.json"
            target.write_text(json.dumps(selected))
            for failure in (False, True):
                with (
                    patch.object(apply, "local_context"),
                    patch.object(apply, "arming"),
                    patch.object(apply, "live"),
                    patch.object(
                        apply.bridge, "backup", return_value={"state": None}
                    ) as backup,
                    patch.object(
                        apply,
                        "run_saved_plan",
                        side_effect=apply.PlanRejected("failure") if failure else None,
                    ),
                ):
                    if failure:
                        with self.assertRaises(apply.PlanRejected):
                            apply.local_apply(
                                root / "plan",
                                root / "log",
                                target,
                                root / "backup",
                                "123",
                            )
                    else:
                        with self.assertRaises(apply.bridge.shared.SharedError):
                            apply.local_apply(
                                root / "plan",
                                root / "log",
                                target,
                                root / "backup",
                                "123",
                            )
                    self.assertEqual(backup.call_count, 2)

    def test_existing_operator_state_blocks_apply(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            target.write_text(
                json.dumps(
                    {
                        "root_certificate_public_data": "public",
                        "root_certificate_sha256": "a" * 64,
                        "expires_at": "2030-01-01T00:00:00Z",
                    }
                )
            )
            with (
                patch.object(apply, "local_context"),
                patch.object(apply, "arming"),
                patch.object(apply, "live"),
                patch.object(
                    apply.bridge, "backup", return_value={"state": {"serial": 1}}
                ),
                patch.object(apply, "run_saved_plan") as execute,
            ):
                with self.assertRaises(apply.bridge.shared.SharedError):
                    apply.local_apply(
                        root / "plan", root / "log", target, root / "backup", "123"
                    )
                execute.assert_not_called()

    def test_recovery_exact_inventory_and_checkpoint_on_failure(self):
        selected = {
            "root_certificate_public_data": "public",
            "root_certificate_sha256": apply.reconcile.ROOT_SHA256,
            "expires_at": apply.reconcile.DEADLINE,
        }
        with (
            patch.object(apply.bridge, "identity"),
            patch.object(apply.bridge.shared, "dependencies_absent"),
            patch.object(
                apply, "az", return_value={"properties": {"state": "Registered"}}
            ),
            patch.object(
                apply.cleanup,
                "inventory",
                return_value=dict.fromkeys(apply.reconcile.EXISTING),
            ),
        ):
            apply.live(selected, recovering=True)
            for existing in ({}, dict.fromkeys(apply.scope.RESOURCES)):
                with patch.object(
                    apply.cleanup, "inventory", return_value=existing
                ), self.assertRaises(apply.bridge.shared.SharedError):
                    apply.live(selected, recovering=True)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            target.write_text(json.dumps(selected))
            state = {
                "sha256": apply.reconcile.STATE_SHA256,
                "serial": 8,
                "lineage": apply.reconcile.LINEAGE,
            }
            with (
                patch.object(apply, "local_context"),
                patch.object(apply, "arming"),
                patch.object(apply, "live"),
                patch.object(
                    apply.bridge, "backup", return_value={"state": state}
                ) as backup,
                patch.object(apply.reconcile, "snapshot") as snapshot,
                patch.object(apply.reconcile, "canonical_state", return_value={}),
                patch.object(apply.reconcile, "validate_reconcile") as validate,
                patch.object(apply, "run_saved_plan") as execute,
            ):

                def failure(*args, **kwargs):
                    self.assertTrue(kwargs["require_canonical_local"])
                    kwargs["validator"]({}, apply.scope.shared.GROUP)
                    raise apply.PlanRejected("apply failure")

                execute.side_effect = failure
                with self.assertRaises(apply.PlanRejected):
                    apply.local_apply(
                        root / "plan",
                        root / "log",
                        target,
                        root / "backup",
                        "123",
                        recovering=True,
                    )
                self.assertEqual(backup.call_count, 2)
                self.assertEqual(snapshot.call_count, 2)
                validate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
