from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_operator_reconcile as guard
from test_operator_access_plan import OperatorAccessPlanTests


class OperatorReconcileTests(unittest.TestCase):
    def fixture(self):
        source = OperatorAccessPlanTests()
        source.setUp()
        source.target["expires_at"] = guard.DEADLINE
        # Only the public root digest is substituted for synthetic fixture bytes.
        plan = source.plan()
        records = plan["planned_values"]["root_module"]["resources"]
        prior = copy.deepcopy(
            [item for item in records if item["address"] != guard.GATEWAY]
        )
        plan["prior_state"] = {"values": {"root_module": {"resources": prior}}}
        canonical = {"values": {"root_module": {"resources": copy.deepcopy(prior)}}}
        for item in plan["resource_changes"]:
            if item["address"] != guard.GATEWAY:
                item["change"]["actions"] = ["no-op"]
                item["change"]["before"] = copy.deepcopy(item["change"]["after"])
        return plan, canonical, source.target

    def validate(self, plan, canonical, target):
        with patch.object(guard, "ROOT_SHA256", target["root_certificate_sha256"]):
            guard.validate_reconcile(plan, guard.scope.shared.GROUP, canonical, target)

    def test_exact_native_shape_and_prior_only_data(self):
        plan, canonical, target = self.fixture()
        plan["planned_values"]["root_module"]["resources"] = [
            item
            for item in plan["planned_values"]["root_module"]["resources"]
            if item["mode"] == "managed"
        ]
        self.validate(plan, canonical, target)

    def test_actions_drift_canonical_metadata_and_scope_fail_closed(self):
        for mutation in (
            "update",
            "replace",
            "missing",
            "drift",
            "metadata",
            "values",
            "deadline",
            "sku",
        ):
            plan, canonical, target = self.fixture()
            existing = next(
                item
                for item in plan["resource_changes"]
                if item["address"] != guard.GATEWAY
            )
            if mutation in ("update", "replace"):
                existing["change"]["actions"] = (
                    ["update"] if mutation == "update" else ["delete", "create"]
                )
            elif mutation == "missing":
                plan["resource_changes"].remove(existing)
            elif mutation == "drift":
                plan["resource_drift"] = [{"address": existing["address"]}]
            elif mutation in ("metadata", "values"):
                item = next(
                    item
                    for item in canonical["values"]["root_module"]["resources"]
                    if item["mode"] == "managed"
                )
                if mutation == "metadata":
                    item["schema_version"] = 999
                else:
                    item["values"]["name"] = "foreign"
            elif mutation == "deadline":
                target["expires_at"] = "2026-11-06T21:55:55Z"
            else:
                next(
                    item
                    for item in plan["resource_changes"]
                    if item["address"] == guard.GATEWAY
                )["change"]["after"]["sku"] = "VpnGw1"
            with self.subTest(mutation=mutation), self.assertRaises(guard.PlanRejected):
                self.validate(plan, canonical, target)


if __name__ == "__main__":
    unittest.main()
