import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "retained_group_plan",
    Path(__file__).resolve().parents[1] / "validate_retained_group_plan.py",
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def resource(kind="azurerm_virtual_network", group="rg-owned"):
    return {
        "address": f"{kind}.shared",
        "mode": "managed",
        "type": kind,
        "values": {"resource_group_name": group},
    }


def plan():
    item = resource()
    return {
        "format_version": "1.2",
        "complete": True,
        "errored": False,
        "variables": {"existing_resource_group_name": {"value": "rg-owned"}},
        "planned_values": {"root_module": {"resources": [item]}},
        "prior_state": {"values": {"root_module": {}}},
        "resource_changes": [
            {
                **{key: item[key] for key in ("address", "mode", "type")},
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": item["values"],
                    "after_unknown": {"id": True},
                },
            }
        ],
    }


class PlanGuardTests(unittest.TestCase):
    def test_valid_and_case_insensitive_group(self):
        guard.validate_plan(plan(), "RG-OWNED")

    def test_nested_prior_group_ownership_rejected(self):
        data = plan()
        data["prior_state"]["values"]["root_module"] = {
            "child_modules": [{"resources": [resource("azurerm_resource_group")]}],
        }
        with self.assertRaises(guard.PlanRejected):
            guard.validate_plan(data, "rg-owned")

    def test_any_managed_group_rejected_even_noop(self):
        data = plan()
        data["resource_changes"][0]["type"] = "azurerm_resource_group"
        data["resource_changes"][0]["change"]["actions"] = ["no-op"]
        with self.assertRaises(guard.PlanRejected):
            guard.validate_plan(data, "rg-owned")

    def test_foreign_before_delete_and_replace(self):
        for actions in (["delete"], ["delete", "create"], ["create", "delete"]):
            with self.subTest(actions=actions):
                data = plan()
                change = data["resource_changes"][0]["change"]
                change["actions"] = actions
                change["before"] = {"resource_group_name": "rg-original-do-not-touch"}
                change["after"] = (
                    None
                    if actions == ["delete"]
                    else {"resource_group_name": "rg-owned"}
                )
                with self.assertRaises(guard.PlanRejected):
                    guard.validate_plan(data, "rg-owned")

    def test_foreign_planned_or_unknown_group(self):
        for value in (None, "", "foreign"):
            data = plan()
            data["planned_values"]["root_module"]["resources"][0]["values"][
                "resource_group_name"
            ] = value
            with self.assertRaises(guard.PlanRejected):
                guard.validate_plan(data, "rg-owned")
        data = plan()
        data["resource_changes"][0]["change"]["after_unknown"][
            "resource_group_name"
        ] = True
        with self.assertRaises(guard.PlanRejected):
            guard.validate_plan(data, "rg-owned")

    def test_malformed_structures_fail_closed(self):
        samples = [None, {}, {"format_version": "2.0"}]
        for path, value in (
            (("prior_state",), None),
            (("planned_values", "root_module", "resources"), {}),
            (("planned_values", "root_module", "child_modules"), "invalid"),
            (("resource_changes",), {}),
            (("resource_changes", 0, "change", "after_unknown"), None),
            (("resource_changes", 0, "change", "actions"), ["forget"]),
            (("variables", "existing_resource_group_name", "value"), None),
            (("complete",), False),
        ):
            data = copy.deepcopy(plan())
            target = data
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            samples.append(data)
        for data in samples:
            with self.subTest(data_type=type(data).__name__):
                with self.assertRaises(guard.PlanRejected):
                    guard.validate_plan(data, "rg-owned")

    def test_exact_private_copy_applied_and_log_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "source.tfplan"
            original.write_bytes(b"native private plan")
            log = Path(directory) / "private.log"
            paths = []

            def invoke(command, **kwargs):
                saved = Path(command[-1])
                paths.append(saved)
                self.assertNotEqual(saved, original)
                self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
                self.assertEqual(saved.read_bytes(), b"native private plan")
                if command[1] == "show":
                    original.write_bytes(b"replaced after validation")
                    return subprocess.CompletedProcess(command, 0, json.dumps(plan()))
                kwargs["stdout"].write("PRIVATE OUTPUT")
                return subprocess.CompletedProcess(command, 0)

            with patch.object(guard.subprocess, "run", side_effect=invoke):
                guard.run_saved_plan(
                    original, "rg-owned", log, terraform="terraform", apply=True
                )
            self.assertEqual(paths[0], paths[1])
            self.assertFalse(paths[0].exists())
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            self.assertEqual(log.read_text(), "PRIVATE OUTPUT")

    def test_rejection_never_applies_and_show_error_is_private(self):
        for result in (
            subprocess.CompletedProcess([], 0, json.dumps({"secret": "PRIVATE"})),
            subprocess.CompletedProcess([], 0, "malformed PRIVATE"),
            subprocess.CompletedProcess([], 1, ""),
        ):
            with tempfile.TemporaryDirectory() as directory:
                native = Path(directory) / "plan"
                native.write_bytes(b"native")
                log = Path(directory) / "log"
                with patch.object(
                    guard.subprocess, "run", return_value=result
                ) as runner:
                    with self.assertRaises(guard.PlanRejected) as raised:
                        guard.run_saved_plan(
                            native, "rg-owned", log, terraform="terraform", apply=True
                        )
                self.assertEqual(runner.call_count, 1)
                self.assertNotIn("PRIVATE", str(raised.exception))

    def test_existing_log_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            native = Path(directory) / "plan"
            native.write_bytes(b"native")
            log = Path(directory) / "log"
            log.write_text("existing private evidence")
            with self.assertRaises(FileExistsError):
                guard.run_saved_plan(
                    native, "rg-owned", log, terraform="terraform", apply=False
                )
            self.assertEqual(log.read_text(), "existing private evidence")


if __name__ == "__main__":
    unittest.main()
