from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import azure_operator_access as operator


class OperatorCleanupTests(unittest.TestCase):
    def setUp(self):
        self.selected = {
            "expires_at": "2026-11-05T20:00:00Z",
            "root_certificate_sha256": "a" * 64,
        }
        self.tags = {
            **operator.scope.shared.TAGS,
            "component": "operator-access",
            "cleanupAfter": self.selected["expires_at"],
            "rootCertificate": "a" * 64,
        }
        self.vnet = {
            "id": operator.scope.VNET,
            "tags": operator.scope.shared.TAGS,
            "properties": {"subnets": []},
        }

    def test_exact_operator_resources_only_and_shared_roots_preserved(self):
        address = "azurerm_public_ip.gateway"
        records = [
            {"id": operator.scope.RESOURCES[address]["id"], "tags": self.tags},
            {"id": operator.scope.ACCOUNT},
            {
                "id": operator.scope.shared.RESOURCES[
                    "azurerm_container_registry.shared"
                ]["id"]
            },
        ]
        with patch.object(operator, "az", return_value=records), patch.object(
            operator.lifecycle, "arm", return_value=self.vnet
        ):
            self.assertEqual(set(operator.inventory(self.selected)), {address})
        records[0]["tags"] = {}
        with patch.object(operator, "az", return_value=records), self.assertRaises(
            operator.lifecycle.SharedError
        ):
            operator.inventory(self.selected)

    def test_unknown_shared_resource_stops_instead_of_adopting(self):
        with patch.object(
            operator,
            "az",
            return_value=[
                {
                    "id": f"{operator.scope.ROOT}/providers/Microsoft.Compute/virtualMachines/foreign"
                }
            ],
        ), patch.object(
            operator.lifecycle, "arm", return_value=self.vnet
        ), self.assertRaises(
            operator.lifecycle.SharedError
        ):
            operator.inventory(self.selected)

    def test_subnet_requires_owned_parent_exact_range_and_no_foreign_attachment(self):
        address = "azurerm_subnet.gateway"
        subnet = {
            "id": operator.scope.RESOURCES[address]["id"],
            "properties": {
                "addressPrefix": "10.20.30.0/27",
                "ipConfigurations": [
                    {
                        "id": f"{operator.scope.RESOURCES['azurerm_virtual_network_gateway.operator']['id']}/ipConfigurations/operator-vpn",
                    }
                ],
            },
        }
        vnet = {**self.vnet, "properties": {"subnets": [subnet]}}
        with patch.object(operator, "az", return_value=[]), patch.object(
            operator.lifecycle, "arm", return_value=vnet
        ):
            self.assertEqual(set(operator.inventory(self.selected)), {address})
        subnet["properties"]["ipConfigurations"] = [{"id": "/foreign"}]
        with patch.object(operator, "az", return_value=[]), patch.object(
            operator.lifecycle, "arm", return_value=vnet
        ), self.assertRaises(operator.lifecycle.SharedError):
            operator.inventory(self.selected)

    def test_all_seven_delete_addresses_exactly_once_in_reverse_dependencies(self):
        self.assertEqual(set(operator.ORDER), set(operator.scope.RESOURCES))
        self.assertEqual(len(operator.ORDER), 7)
        self.assertLess(
            operator.ORDER.index("azurerm_virtual_network_gateway.operator"),
            operator.ORDER.index("azurerm_public_ip.gateway"),
        )
        self.assertLess(
            operator.ORDER.index(
                "azurerm_private_dns_resolver_inbound_endpoint.operator"
            ),
            operator.ORDER.index("azurerm_private_dns_resolver.operator"),
        )

    def test_predeadline_does_not_mutate_and_pending_delete_stops(self):
        selected = {
            **self.selected,
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
        with patch.object(operator, "target", return_value=selected), patch.object(
            operator, "identity"
        ), patch.object(operator, "inventory", return_value={}), patch.object(
            operator, "az"
        ) as mutate:
            operator.cleanup(now=False)
            mutate.assert_not_called()
        selected["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        with patch.object(operator, "target", return_value=selected), patch.object(
            operator, "identity"
        ), patch.object(
            operator,
            "inventory",
            return_value={"azurerm_virtual_network_gateway.operator": {}},
        ), patch.object(
            operator, "az"
        ) as mutate, self.assertRaisesRegex(
            operator.lifecycle.SharedError, "pending"
        ):
            try:
                operator.cleanup(now=False)
            finally:
                self.assertEqual(mutate.call_count, 1)
                self.assertIn(
                    "virtualNetworkGateways/llmrelease-operator-vpn",
                    mutate.call_args.args[-1],
                )

    def test_unarmed_or_foreign_environment_rejected_before_azure(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            operator, "az"
        ) as call, self.assertRaises(operator.lifecycle.SharedError):
            try:
                operator.cleanup(now=False)
            finally:
                call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
