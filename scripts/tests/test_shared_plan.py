from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_shared_plan as guard


class SharedPlanTests(unittest.TestCase):
    def plan(self, operation="create", selected=None):
        selected = guard.ADDRESSES if selected is None else selected
        configuration = []
        records = []
        changes = []
        for address in sorted(selected):
            if address in guard.RESOURCES:
                values = copy.deepcopy(guard.RESOURCES[address])
                values["resource_group_name"] = guard.GROUP
                references = {}
                if operation == "create":
                    values.pop("id")
                    for field in ("workspace_id", "virtual_network_id", "subnet_id"):
                        if field in values:
                            target = next(
                                name
                                for name, value in guard.RESOURCES.items()
                                if value["id"] == values[field]
                            )
                            references[field] = target
                            values.pop(field)
            else:
                references = guard.ASSOCIATIONS[address]
                values = {
                    field: guard.RESOURCES[target]["id"]
                    for field, target in references.items()
                }
                if "subnet_id" in values:
                    values["id"] = values["subnet_id"]
                else:
                    values["id"] = (
                        f"{values['nat_gateway_id']}|{values['public_ip_address_id']}"
                    )
                if operation == "create":
                    values = {}
            configuration.append(
                {
                    "address": address,
                    "provider_config_key": "azurerm",
                    "expressions": {
                        field: {"references": [f"{target}.id", target]}
                        for field, target in references.items()
                    },
                }
            )
            if address == "azurerm_private_endpoint.vault":
                values["private_service_connection"] = [
                    {
                        "name": "llmrelease-vault-psc",
                        "is_manual_connection": False,
                        "subresource_names": ["vault"],
                        "private_connection_resource_id": (
                            None
                            if operation == "create"
                            else guard.RESOURCES["azurerm_key_vault.shared"]["id"]
                        ),
                    }
                ]
                values["private_dns_zone_group"] = [
                    {
                        "name": "vault-zone-group",
                        "private_dns_zone_ids": (
                            [None]
                            if operation == "create"
                            else [
                                guard.RESOURCES["azurerm_private_dns_zone.vault"]["id"]
                            ]
                        ),
                    }
                ]
                configuration[-1]["expressions"].update(
                    {
                        "private_service_connection": [
                            {
                                "is_manual_connection": {"constant_value": False},
                                "name": {"references": ["var.name_prefix"]},
                                "subresource_names": {"constant_value": ["vault"]},
                                "private_connection_resource_id": {
                                    "references": [
                                        "azurerm_key_vault.shared.id",
                                        "azurerm_key_vault.shared",
                                    ]
                                },
                            }
                        ],
                        "private_dns_zone_group": [
                            {
                                "name": {"constant_value": "vault-zone-group"},
                                "private_dns_zone_ids": {
                                    "references": [
                                        "azurerm_private_dns_zone.vault.id",
                                        "azurerm_private_dns_zone.vault",
                                    ]
                                },
                            }
                        ],
                    }
                )
            record = {
                "address": address,
                "mode": "managed",
                "type": address.split(".")[0],
                "values": values,
            }
            records.append(record)
            changes.append(
                {key: value for key, value in record.items() if key != "values"}
                | {
                    "change": {
                        "actions": ["create" if operation == "create" else "delete"],
                        "before": (
                            None if operation == "create" else copy.deepcopy(values)
                        ),
                        "after": (
                            copy.deepcopy(values) if operation == "create" else None
                        ),
                        "after_unknown": {},
                    }
                }
            )
        data = [
            {
                "address": "data.azurerm_resource_group.shared[0]",
                "mode": "data",
                "type": "azurerm_resource_group",
                "values": {
                    "id": guard.ROOT,
                    "name": guard.GROUP,
                    "tags": guard.FALLBACK_TARGET.group_tags,
                },
            },
            {
                "address": "data.azurerm_client_config.current",
                "mode": "data",
                "type": "azurerm_client_config",
                "values": {
                    "subscription_id": guard.FALLBACK_TARGET.subscription,
                    "tenant_id": guard.FALLBACK_TARGET.tenant,
                },
            },
        ]
        configuration.extend(
            {"address": address, "provider_config_key": "azurerm", "expressions": {}}
            for address in sorted(guard.ADDRESSES - set(selected))
        )
        configuration.extend(
            [
                {
                    "address": address,
                    "provider_config_key": "azurerm",
                    "expressions": {},
                }
                for address in (
                    "data.azurerm_resource_group.shared",
                    "data.azurerm_client_config.current",
                )
            ]
        )
        return {
            "format_version": "1.2",
            "complete": True,
            "errored": False,
            "variables": {
                name: {"value": value}
                for name, value in {
                    "subscription_id": guard.FALLBACK_TARGET.subscription,
                    "existing_resource_group_name": guard.GROUP,
                    "location": guard.REGION,
                    "stage": "release",
                    "name_prefix": "llmrelease",
                    "tags": guard.FALLBACK_TARGET.group_tags,
                    "key_vault_allowed_ip_ranges": [],
                }.items()
            },
            "prior_state": {
                "values": {
                    "root_module": {
                        "resources": copy.deepcopy(
                            data + (records if operation == "destroy" else [])
                        )
                    }
                }
            },
            "planned_values": {
                "root_module": {
                    "resources": copy.deepcopy(
                        data + (records if operation == "create" else [])
                    )
                }
            },
            "resource_changes": changes,
            "configuration": {
                "provider_config": {
                    "azurerm": {
                        "full_name": "registry.terraform.io/hashicorp/azurerm",
                        "expressions": {
                            "subscription_id": {"references": ["var.subscription_id"]}
                        },
                    }
                },
                "root_module": {"resources": configuration},
            },
        }

    def validate(self, plan, operation="create"):
        guard.validate_fixed_shared(plan, guard.GROUP, operation=operation)

    def test_exact_29_creates_and_complete_or_partial_owned_destroy(self):
        self.assertEqual(len(guard.ADDRESSES), 29)
        self.validate(self.plan())
        self.validate(self.plan("destroy"), "destroy")
        for selected in (
            set(),
            {"azurerm_nat_gateway.shared"},
            set(guard.ASSOCIATIONS),
        ):
            self.validate(self.plan("destroy", selected), "destroy")

    def test_every_fixed_variable_is_required_and_no_network_exception(self):
        for name in self.plan()["variables"]:
            plan = self.plan()
            plan["variables"][name]["value"] = "foreign"
            with self.subTest(name=name), self.assertRaises(guard.PlanRejected):
                self.validate(plan)

    def test_initial_create_rejects_missing_or_duplicate_managed_change(self):
        for mutation in ("missing", "duplicate", "extra"):
            plan = self.plan()
            if mutation == "missing":
                plan["resource_changes"].pop()
            elif mutation == "duplicate":
                plan["resource_changes"].append(plan["resource_changes"][0])
            else:
                record = copy.deepcopy(plan["resource_changes"][0])
                record.update(
                    address="azurerm_storage_account.state",
                    type="azurerm_storage_account",
                )
                plan["resource_changes"].append(record)
            with self.subTest(mutation=mutation), self.assertRaises(guard.PlanRejected):
                self.validate(plan)

    def test_updates_replacements_and_opposite_actions_never_pass(self):
        for operation in ("create", "destroy"):
            for actions in (
                ["no-op"],
                ["read"],
                ["update"],
                ["delete", "create"],
                ["create", "delete"],
                ["delete" if operation == "create" else "create"],
            ):
                plan = self.plan(operation)
                plan["resource_changes"][0]["change"]["actions"] = actions
                with self.subTest(
                    operation=operation, actions=actions
                ), self.assertRaises(guard.PlanRejected):
                    self.validate(plan, operation)

    def test_every_primary_destroy_id_name_tag_and_scope_is_exact(self):
        for address, expected in guard.RESOURCES.items():
            fields = {*expected, "resource_group_name"}
            for field in fields:
                plan = self.plan("destroy", {address})
                plan["resource_changes"][0]["change"]["before"][field] = "foreign"
                with self.subTest(address=address, field=field), self.assertRaises(
                    guard.PlanRejected
                ):
                    self.validate(plan, "destroy")

    def test_each_association_id_and_target_is_exact(self):
        for address, fields in guard.ASSOCIATIONS.items():
            for field in {*fields, "id"}:
                plan = self.plan("destroy", {address})
                plan["resource_changes"][0]["change"]["before"][
                    field
                ] = f"{guard.ROOT}/providers/Microsoft.Network/virtualNetworks/original"
                with self.subTest(address=address, field=field), self.assertRaises(
                    guard.PlanRejected
                ):
                    self.validate(plan, "destroy")

    def test_unknown_create_associations_require_exact_native_references(self):
        for address, fields in guard.ASSOCIATIONS.items():
            for field in fields:
                plan = self.plan()
                config = next(
                    item
                    for item in plan["configuration"]["root_module"]["resources"]
                    if item["address"] == address
                )
                for references in (
                    [],
                    ["azurerm_subnet.original.id"],
                    [fields[field], "data.azurerm_subnet.original.id"],
                ):
                    config["expressions"][field]["references"] = references
                    with self.subTest(
                        address=address, field=field, references=references
                    ), self.assertRaises(guard.PlanRejected):
                        self.validate(plan)

    def test_foreign_or_unknown_known_targets_rejected(self):
        for address, fields in guard.ASSOCIATIONS.items():
            field = next(iter(fields))
            plan = self.plan()
            record = next(
                item for item in plan["resource_changes"] if item["address"] == address
            )
            record["change"]["after"][
                field
            ] = f"{guard.ROOT}/providers/Microsoft.Network/virtualNetworks/original"
            with self.subTest(address=address), self.assertRaises(guard.PlanRejected):
                self.validate(plan)

    def test_prior_managed_state_cannot_be_adopted_by_initial_create(self):
        plan = self.plan()
        plan["prior_state"]["values"]["root_module"]["resources"].append(
            self.plan("destroy", {"azurerm_nat_gateway.shared"})["prior_state"][
                "values"
            ]["root_module"]["resources"][-1]
        )
        with self.assertRaises(guard.PlanRejected):
            self.validate(plan)

    def test_destroy_must_cover_every_prior_resource_and_leave_none(self):
        plan = self.plan("destroy")
        plan["resource_changes"].pop()
        with self.assertRaises(guard.PlanRejected):
            self.validate(plan, "destroy")
        plan = self.plan("destroy")
        plan["planned_values"]["root_module"]["resources"].append(
            plan["prior_state"]["values"]["root_module"]["resources"][-1]
        )
        with self.assertRaises(guard.PlanRejected):
            self.validate(plan, "destroy")

    def test_child_modules_and_forged_data_context_are_rejected(self):
        for key in ("planned_values", "prior_state"):
            plan = self.plan()
            module = (
                plan[key]["root_module"]
                if key == "planned_values"
                else plan[key]["values"]["root_module"]
            )
            module["child_modules"] = [{"resources": []}]
            with self.subTest(key=key), self.assertRaises(guard.PlanRejected):
                self.validate(plan)
        for index, field in (
            (0, "id"),
            (0, "name"),
            (0, "tags"),
            (1, "subscription_id"),
            (1, "tenant_id"),
        ):
            plan = self.plan()
            plan["planned_values"]["root_module"]["resources"][index]["values"][
                field
            ] = "foreign"
            with self.subTest(index=index, field=field), self.assertRaises(
                guard.PlanRejected
            ):
                self.validate(plan)

    def test_no_other_campaign_or_operation_can_select_the_guard(self):
        for group, operation in (("original", "create"), (guard.GROUP, "update")):
            with self.assertRaises(guard.PlanRejected):
                guard.validate_fixed_shared(self.plan(), group, operation=operation)

    def test_foreign_provider_aliases_and_missing_context_never_pass(self):
        for selected in (
            "azurerm_private_endpoint.vault",
            "data.azurerm_client_config.current",
        ):
            plan = self.plan()
            record = next(
                item
                for item in plan["configuration"]["root_module"]["resources"]
                if item["address"] == selected
            )
            record["provider_config_key"] = "azurerm.foreign"
            with self.subTest(selected=selected), self.assertRaises(guard.PlanRejected):
                self.validate(plan)
        plan = self.plan()
        plan["configuration"]["provider_config"]["azurerm.foreign"] = {}
        with self.assertRaises(guard.PlanRejected):
            self.validate(plan)
        plan = self.plan()
        plan["configuration"]["provider_config"]["azurerm"]["expressions"][
            "subscription_id"
        ] = {"constant_value": "foreign"}
        with self.assertRaises(guard.PlanRejected):
            self.validate(plan)
        plan = self.plan()
        for module in (
            plan["prior_state"]["values"]["root_module"],
            plan["planned_values"]["root_module"],
        ):
            module["resources"] = [
                item
                for item in module["resources"]
                if item["address"] != "data.azurerm_client_config.current"
            ]
        with self.assertRaises(guard.PlanRejected):
            self.validate(plan)

    def test_endpoint_nested_vault_and_dns_targets_are_fixed_or_exactly_bound(self):
        for block, field, array in (
            ("private_service_connection", "private_connection_resource_id", False),
            ("private_dns_zone_group", "private_dns_zone_ids", True),
        ):
            for operation in ("create", "destroy"):
                plan = self.plan(operation)
                record = next(
                    item
                    for item in plan["resource_changes"]
                    if item["address"] == "azurerm_private_endpoint.vault"
                )
                values = record["change"][
                    "after" if operation == "create" else "before"
                ]
                foreign = "/subscriptions/foreign/resourceGroups/original/providers/Microsoft.KeyVault/vaults/original"
                values[block][0][field] = [foreign] if array else foreign
                with self.subTest(block=block, operation=operation), self.assertRaises(
                    guard.PlanRejected
                ):
                    self.validate(plan, operation)
            plan = self.plan()
            config = next(
                item
                for item in plan["configuration"]["root_module"]["resources"]
                if item["address"] == "azurerm_private_endpoint.vault"
            )
            config["expressions"][block][0][field] = {
                "references": ["data.azurerm_key_vault.original.id"]
            }
            with self.subTest(block=block, unknown=True), self.assertRaises(
                guard.PlanRejected
            ):
                self.validate(plan)


if __name__ == "__main__":
    unittest.main()
