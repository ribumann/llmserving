from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import azure_shared_bridge as bridge
import test_shared_plan as fixture
import validate_shared_reconcile as guard


class SharedReconcileTests(unittest.TestCase):
    def test_exact_native_refresh_normalizations_and_reject_other_deltas(self):
        examples = [
            ("azurerm_nat_gateway.shared", "zones", None, []),
            ("azurerm_private_dns_zone.vault", "number_of_record_sets", 1, 2),
        ]
        examples.extend(
            (f"azurerm_subnet.{label}", field, None, [])
            for label in (
                "containerapps",
                "gpu",
                "private_endpoints",
                "functions",
                "data",
            )
            for field in ("service_endpoints", "service_endpoint_policy_ids")
        )
        entries = [
            {
                "id": guard.scope.RESOURCES[f"azurerm_subnet.{label}"]["id"],
                "name": guard.scope.RESOURCES[f"azurerm_subnet.{label}"]["name"],
                "address_prefix": prefix,
                "security_group": (
                    guard.scope.RESOURCES["azurerm_network_security_group.gpu"]["id"]
                    if label == "gpu"
                    else ""
                ),
            }
            for label, prefix in {
                "containerapps": "10.20.1.0/24",
                "gpu": "10.20.10.0/24",
                "private_endpoints": "10.20.2.0/24",
                "functions": "10.20.3.0/24",
                "data": "10.20.4.0/26",
            }.items()
        ]
        examples.append(("azurerm_virtual_network.shared", "subnet", [], entries))
        for address, field, before, after in examples:
            with self.subTest(address=address, field=field):
                guard.refreshed_values(address, {field: before}, {field: after})
                for bad in (
                    "foreign",
                    ["/foreign"],
                    None if after is not None else "foreign",
                ):
                    if bad == before:
                        continue
                    with self.assertRaises(guard.PlanRejected):
                        guard.refreshed_values(address, {field: before}, {field: bad})
                with self.assertRaises(guard.PlanRejected):
                    guard.refreshed_values(
                        address, {field: before}, {field: after, "foreign": True}
                    )

    def test_refresh_must_match_native_drift_and_canonical_snapshot(self):
        plan, canonical = self.recovery()
        address = "azurerm_nat_gateway.shared"
        prior = guard.managed(plan["prior_state"]["values"]["root_module"])
        current = guard.managed(canonical["values"]["root_module"])
        future = guard.managed(plan["planned_values"]["root_module"])
        current[address]["values"]["zones"] = None
        prior[address]["values"]["zones"] = []
        current[address]["sensitive_values"] = {}
        prior[address]["sensitive_values"] = {"zones": []}
        future[address]["values"]["zones"] = []
        change = next(
            item for item in plan["resource_changes"] if item["address"] == address
        )["change"]
        change["before"]["zones"] = []
        change["after"]["zones"] = []
        plan["resource_drift"] = [
            {
                "address": address,
                "mode": "managed",
                "type": "azurerm_nat_gateway",
                "change": {
                    "actions": ["update"],
                    "before": copy.deepcopy(current[address]["values"]),
                    "after": copy.deepcopy(prior[address]["values"]),
                    "after_unknown": {},
                },
            }
        ]
        guard.validate_reconcile(plan, guard.scope.GROUP, canonical)
        for sensitivity in (
            {"zones": True},
            {"zones": [True]},
            {"zones": [], "foreign": False},
        ):
            altered = copy.deepcopy(plan)
            guard.managed(altered["prior_state"]["values"]["root_module"])[address][
                "sensitive_values"
            ] = sensitivity
            with self.assertRaises(guard.PlanRejected):
                guard.validate_reconcile(altered, guard.scope.GROUP, canonical)
        for kind in ("missing", "duplicate", "mismatch"):
            altered = copy.deepcopy(plan)
            if kind == "missing":
                altered["resource_drift"] = []
            elif kind == "duplicate":
                altered["resource_drift"] *= 2
            else:
                altered["resource_drift"][0]["change"]["after"]["zones"] = ["foreign"]
            with self.assertRaises(guard.PlanRejected):
                guard.validate_reconcile(altered, guard.scope.GROUP, canonical)

    def recovery(self):
        source = fixture.SharedPlanTests()
        plan = source.plan("create")
        old = source.plan("destroy", selected=guard.EXISTING)
        plan["prior_state"] = copy.deepcopy(old["prior_state"])
        prior = guard.managed(plan["prior_state"]["values"]["root_module"])
        future = guard.managed(plan["planned_values"]["root_module"])
        for record in plan["resource_changes"]:
            address = record["address"]
            if address in guard.EXISTING:
                values = copy.deepcopy(prior[address]["values"])
                record["change"].update(
                    actions=["no-op"], before=values, after=copy.deepcopy(values)
                )
                future[address]["values"] = copy.deepcopy(values)
        canonical = copy.deepcopy(plan["prior_state"])
        return plan, canonical

    def test_exact_two_creates_and_27_noops(self):
        plan, canonical = self.recovery()
        guard.validate_reconcile(plan, guard.scope.GROUP, canonical)
        with self.assertRaises(guard.PlanRejected):
            guard.scope.validate_fixed_shared(
                plan, guard.scope.GROUP, operation="create"
            )

    def test_native_prior_only_data_context_preserved_in_projection(self):
        plan, canonical = self.recovery()
        plan["planned_values"]["root_module"]["resources"] = [
            record
            for record in plan["planned_values"]["root_module"]["resources"]
            if record["mode"] == "managed"
        ]
        plan["resource_changes"] = [
            record for record in plan["resource_changes"] if record["mode"] == "managed"
        ]
        guard.validate_reconcile(plan, guard.scope.GROUP, canonical)
        for context, field in (
            ("data.azurerm_client_config.current", "subscription_id"),
            ("data.azurerm_resource_group.shared[0]", "id"),
        ):
            altered = copy.deepcopy(plan)
            next(
                record
                for record in altered["prior_state"]["values"]["root_module"][
                    "resources"
                ]
                if record["address"] == context
            )["values"][field] = "foreign"
            with self.assertRaises(guard.PlanRejected):
                guard.validate_reconcile(altered, guard.scope.GROUP, canonical)

    def test_rejects_each_nonnoop_and_changed_existing_values(self):
        for address in guard.EXISTING:
            for action in (["update"], ["delete"], ["delete", "create"]):
                plan, canonical = self.recovery()
                next(
                    item
                    for item in plan["resource_changes"]
                    if item["address"] == address
                )["change"]["actions"] = action
                with self.subTest(address=address, action=action), self.assertRaises(
                    guard.PlanRejected
                ):
                    guard.validate_reconcile(plan, guard.scope.GROUP, canonical)
        plan, canonical = self.recovery()
        plan["resource_changes"][0]["change"]["after"]["foreign"] = True
        with self.assertRaises(guard.PlanRejected):
            guard.validate_reconcile(plan, guard.scope.GROUP, canonical)

    def test_rejects_wrong_snapshot_prior_missing_duplicate_and_drift(self):
        for kind in ("canonical", "prior", "missing", "duplicate", "drift"):
            plan, canonical = self.recovery()
            if kind == "canonical":
                next(iter(guard.managed(canonical["values"]["root_module"]).values()))[
                    "values"
                ]["id"] = "/foreign"
            elif kind == "prior":
                plan["prior_state"]["values"]["root_module"]["resources"][0]["values"][
                    "id"
                ] = "/foreign"
            elif kind == "missing":
                plan["resource_changes"].pop(0)
            elif kind == "duplicate":
                plan["resource_changes"].append(
                    copy.deepcopy(plan["resource_changes"][0])
                )
            else:
                plan["resource_drift"] = [{"address": "foreign"}]
            with self.subTest(kind=kind), self.assertRaises(guard.PlanRejected):
                guard.validate_reconcile(plan, guard.scope.GROUP, canonical)

    def test_rejects_foreign_new_pip_and_existing_auth_weakening(self):
        for address, field, value in (
            ("azurerm_public_ip.nat", "resource_group_name", "foreign"),
            ("azurerm_key_vault.shared", "public_network_access_enabled", True),
        ):
            plan, canonical = self.recovery()
            for container in (
                guard.managed(plan["planned_values"]["root_module"]),
                guard.managed(plan["prior_state"]["values"]["root_module"]),
                guard.managed(canonical["values"]["root_module"]),
            ):
                if address in container:
                    container[address]["values"][field] = value
            change = next(
                item for item in plan["resource_changes"] if item["address"] == address
            )["change"]
            change["after"][field] = value
            if change["before"] is not None:
                change["before"][field] = value
            with self.assertRaises(guard.PlanRejected):
                guard.validate_reconcile(plan, guard.scope.GROUP, canonical)

    def test_recovery_state_never_accepts_arbitrary_metadata(self):
        for metadata in (None, {}, {"lineage": guard.LINEAGE, "serial": 30}):
            with self.assertRaises(bridge.shared.SharedError):
                bridge.recovery_state(metadata)

    def test_recovery_inventory_fails_closed_before_mutation(self):
        from datetime import UTC, datetime

        with patch.object(
            bridge, "configuration", return_value=datetime(2026, 11, 5, 22, tzinfo=UTC)
        ), patch.object(bridge, "az") as azure:
            with self.assertRaises(bridge.shared.SharedError):
                bridge.recovery_inventory()
            azure.assert_not_called()
        with patch.object(
            bridge, "configuration", return_value=datetime(2026, 11, 5, 21, tzinfo=UTC)
        ), patch.object(
            bridge, "az", return_value={"properties": {"state": "NotRegistered"}}
        ), patch.object(
            bridge.shared, "inventory"
        ) as inventory:
            with self.assertRaises(bridge.shared.SharedError):
                bridge.recovery_inventory()
            inventory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
