from __future__ import annotations

import base64
import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import validate_operator_access_plan as guard


class OperatorAccessPlanTests(unittest.TestCase):
    def setUp(self):
        public = b"synthetic public certificate fixture, not a private key"
        self.target = {
            "root_certificate_public_data": base64.b64encode(public).decode(),
            "root_certificate_sha256": hashlib.sha256(public).hexdigest(),
            "expires_at": "2026-11-05T20:00:00Z",
        }

    def plan(self, operation="create", selected=None):
        selected = set(guard.RESOURCES) if selected is None else selected
        configuration = []
        records = []
        changes = []
        tags = {
            **guard.shared.TAGS,
            "component": "operator-access",
            "cleanupAfter": self.target["expires_at"],
            "rootCertificate": self.target["root_certificate_sha256"],
        }
        for address, expected in guard.RESOURCES.items():
            configuration.append(
                {
                    "address": address,
                    "provider_config_key": "azurerm",
                    "expressions": {},
                }
            )
            if address not in selected:
                continue
            values = copy.deepcopy(expected)
            if address != "azurerm_private_dns_resolver_inbound_endpoint.operator":
                values["resource_group_name"] = guard.shared.GROUP
            if not address.startswith("azurerm_subnet."):
                values.update(
                    {"location": guard.shared.REGION, "tags": copy.deepcopy(tags)}
                )
            if address == "azurerm_subnet.dns":
                values["delegation"] = [
                    {
                        "name": "dns-resolver",
                        "service_delegation": [
                            {
                                "name": "Microsoft.Network/dnsResolvers",
                                "actions": [
                                    "Microsoft.Network/virtualNetworks/subnets/join/action"
                                ],
                            }
                        ],
                    }
                ]
            if address == "azurerm_virtual_network_gateway.operator":
                values["ip_configuration"] = [
                    {
                        "name": "operator-vpn",
                        "private_ip_address_allocation": "Dynamic",
                        "subnet_id": guard.RESOURCES["azurerm_subnet.gateway"]["id"],
                        "public_ip_address_id": guard.RESOURCES[
                            "azurerm_public_ip.gateway"
                        ]["id"],
                    }
                ]
                values["vpn_client_configuration"] = [
                    {
                        "address_space": ["172.29.240.0/24"],
                        "vpn_auth_types": ["Certificate"],
                        "vpn_client_protocols": ["OpenVPN"],
                        "root_certificate": [
                            {
                                "name": "llmrelease-operator-root",
                                "public_cert_data": self.target[
                                    "root_certificate_public_data"
                                ],
                            }
                        ],
                    }
                ]
            if address == "azurerm_private_dns_resolver_inbound_endpoint.operator":
                values["private_dns_resolver_id"] = guard.RESOURCES[
                    "azurerm_private_dns_resolver.operator"
                ]["id"]
                values["ip_configurations"] = [
                    {
                        "private_ip_allocation_method": "Static",
                        "private_ip_address": "10.20.31.4",
                        "subnet_id": guard.RESOURCES["azurerm_subnet.dns"]["id"],
                    }
                ]
            if address == "azurerm_private_endpoint.state":
                values["private_service_connection"] = [
                    {
                        "name": "llmrelease-state-blob",
                        "private_connection_resource_id": guard.ACCOUNT,
                        "subresource_names": ["blob"],
                        "is_manual_connection": False,
                    }
                ]
                values["private_dns_zone_group"] = [
                    {
                        "name": "state-blob-zone-group",
                        "private_dns_zone_ids": [guard.ZONE],
                    }
                ]
            record = {
                "address": address,
                "type": address.split(".")[0],
                "mode": "managed",
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
                "address": address,
                "mode": "data",
                "type": address.split(".")[1],
                "values": {"id": identifier},
            }
            for address, identifier in guard.DATA.items()
        ] + [
            {
                "address": "data.azurerm_client_config.current",
                "mode": "data",
                "type": "azurerm_client_config",
                "values": {
                    "subscription_id": guard.shared.FALLBACK_TARGET.subscription,
                    "tenant_id": guard.shared.FALLBACK_TARGET.tenant,
                },
            }
        ]
        configuration.extend(
            {
                "address": item["address"],
                "provider_config_key": "azurerm",
                "expressions": {},
            }
            for item in data
        )
        plan = {
            "format_version": "1.2",
            "variables": {
                key: {"value": value}
                for key, value in {
                    "subscription_id": guard.shared.FALLBACK_TARGET.subscription,
                    "existing_resource_group_name": guard.shared.GROUP,
                    **self.target,
                }.items()
            },
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
            "planned_values": {
                "root_module": {
                    "resources": (records if operation == "create" else [])
                    + copy.deepcopy(data)
                }
            },
            "resource_changes": changes,
        }
        if operation == "destroy":
            plan["prior_state"] = {
                "values": {"root_module": {"resources": records + data}}
            }
        return plan

    def test_exact_seven_creates_and_partial_destroy(self):
        guard.validate(
            self.plan(), guard.shared.GROUP, operation="create", target=self.target
        )
        guard.validate(
            self.plan("destroy", {"azurerm_private_endpoint.state"}),
            guard.shared.GROUP,
            operation="destroy",
            target=self.target,
        )

    def test_fingerprint_mismatch_and_unexpected_private_input_rejected(self):
        for target in (
            {**self.target, "root_certificate_sha256": "a" * 64},
            {**self.target, "private_key": "forbidden"},
            {
                **self.target,
                "root_certificate_public_data": "-----BEGIN PRIVATE KEY-----",
            },
        ):
            with self.assertRaises(guard.PlanRejected):
                guard.validate(
                    self.plan(), guard.shared.GROUP, operation="create", target=target
                )

    def test_foreign_bindings_unknown_security_extra_auth_rejected(self):
        for address, field, value in (
            ("azurerm_private_endpoint.state", "subnet_id", "/subscriptions/foreign"),
            ("azurerm_virtual_network_gateway.operator", "sku", "VpnGw5"),
            ("azurerm_subnet.gateway", "address_prefixes", ["10.0.0.0/8"]),
            (
                "azurerm_private_dns_resolver.operator",
                "virtual_network_id",
                "/subscriptions/foreign",
            ),
        ):
            plan = self.plan()
            next(
                record
                for record in plan["planned_values"]["root_module"]["resources"]
                if record["address"] == address
            )["values"][field] = value
            with self.subTest(address=address), self.assertRaises(guard.PlanRejected):
                guard.validate(
                    plan, guard.shared.GROUP, operation="create", target=self.target
                )
        plan = self.plan()
        gateway = next(
            record
            for record in plan["resource_changes"]
            if record["address"] == "azurerm_virtual_network_gateway.operator"
        )
        gateway["change"]["after"]["vpn_client_configuration"][0][
            "radius_server_secret"
        ] = "forbidden"
        with self.assertRaises(guard.PlanRejected):
            guard.validate(
                plan, guard.shared.GROUP, operation="create", target=self.target
            )

    def test_updates_roles_aliases_and_missing_resources_rejected(self):
        plan = self.plan()
        plan["resource_changes"][0]["change"]["actions"] = ["update"]
        with self.assertRaises(guard.PlanRejected):
            guard.validate(
                plan, guard.shared.GROUP, operation="create", target=self.target
            )
        plan = self.plan()
        plan["configuration"]["root_module"]["resources"][0][
            "provider_config_key"
        ] = "azurerm.foreign"
        with self.assertRaises(guard.PlanRejected):
            guard.validate(
                plan, guard.shared.GROUP, operation="create", target=self.target
            )
        with self.assertRaises(guard.PlanRejected):
            guard.validate(
                self.plan(selected={"azurerm_subnet.gateway"}),
                guard.shared.GROUP,
                operation="create",
                target=self.target,
            )
        plan = self.plan()
        plan["configuration"]["root_module"]["resources"].append(
            {
                "address": "azurerm_role_assignment.extra",
                "provider_config_key": "azurerm",
            }
        )
        with self.assertRaises(guard.PlanRejected):
            guard.validate(
                plan, guard.shared.GROUP, operation="create", target=self.target
            )

    def test_missing_endpoint_dns_allowed_only_owned_delete(self):
        plan = self.plan("destroy", {"azurerm_private_endpoint.state"})
        plan["prior_state"]["values"]["root_module"]["resources"][0]["values"][
            "private_dns_zone_group"
        ] = []
        plan["resource_changes"][0]["change"]["before"]["private_dns_zone_group"] = []
        guard.validate(
            plan, guard.shared.GROUP, operation="destroy", target=self.target
        )
        plan = self.plan()
        next(
            record
            for record in plan["resource_changes"]
            if record["address"] == "azurerm_private_endpoint.state"
        )["change"]["after"]["private_dns_zone_group"] = []
        with self.assertRaises(guard.PlanRejected):
            guard.validate(
                plan, guard.shared.GROUP, operation="create", target=self.target
            )


if __name__ == "__main__":
    unittest.main()
