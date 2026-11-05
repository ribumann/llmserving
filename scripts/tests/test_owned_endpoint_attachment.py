import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import azure_shared_bridge as bridge


class OwnedEndpointAttachmentTests(unittest.TestCase):
    def fixture(self):
        subnet = bridge.scope.RESOURCES["azurerm_subnet.private_endpoints"]["id"]
        endpoint = bridge.scope.RESOURCES["azurerm_private_endpoint.vault"]["id"]
        nic = f"{bridge.scope.ROOT}/providers/Microsoft.Network/networkInterfaces/llmrelease-vault-pe.nic.2e3ebfb3-4c17-457c-afb8-882a9cdb1753"
        ipconfig = f"{nic}/ipConfigurations/privateendpointipconfig.e04a600a-ca43-4e7a-9a26-9d5bdbbdedee"
        records = {
            "azurerm_subnet.private_endpoints": {
                "properties": {
                    "privateEndpoints": [{"id": endpoint}],
                    "ipConfigurations": [{"id": ipconfig.upper()}],
                }
            }
        }
        pe = {
            "id": endpoint,
            "tags": bridge.scope.TAGS,
            "properties": {
                "subnet": {"id": subnet},
                "networkInterfaces": [{"id": nic}],
            },
        }
        network = {
            "id": nic.upper(),
            "properties": {
                "privateEndpoint": {"id": endpoint.upper()},
                "ipConfigurations": [
                    {
                        "id": ipconfig,
                        "name": ipconfig.split("/")[-1],
                        "properties": {"subnet": {"id": subnet}},
                    }
                ],
            },
        }
        return records, pe, network

    def test_exact_owned_chain_and_arm_case_variations_pass(self):
        records, endpoint, nic = self.fixture()
        with patch.object(bridge.shared, "arm", side_effect=[endpoint, nic]) as read:
            bridge.reject_attached_children(records)
            self.assertEqual(read.call_count, 2)

    def test_wrong_subnet_parent_nic_configuration_or_duplicate_rejected(self):
        for kind in (
            "pe-subnet",
            "pe-tags",
            "nic-parent",
            "nic-subnet",
            "nic-id",
            "ip-id",
            "duplicate",
            "foreign",
            "other-subnet",
            "virtual-machine",
        ):
            records, endpoint, nic = self.fixture()
            if kind == "pe-subnet":
                endpoint["properties"]["subnet"]["id"] = "/foreign"
            elif kind == "pe-tags":
                endpoint["tags"] = {}
            elif kind == "nic-parent":
                nic["properties"]["privateEndpoint"]["id"] = "/foreign"
            elif kind == "nic-subnet":
                nic["properties"]["ipConfigurations"][0]["properties"]["subnet"][
                    "id"
                ] = "/foreign"
            elif kind == "nic-id":
                nic["id"] = "/foreign"
            elif kind == "ip-id":
                nic["properties"]["ipConfigurations"][0]["id"] = "/foreign"
            elif kind == "duplicate":
                records["azurerm_subnet.private_endpoints"]["properties"][
                    "ipConfigurations"
                ] *= 2
            elif kind == "foreign":
                records["azurerm_subnet.private_endpoints"]["properties"][
                    "ipConfigurations"
                ] = [{"id": "/foreign"}]
            elif kind == "virtual-machine":
                nic["properties"]["virtualMachine"] = {"id": "/foreign"}
            else:
                records["azurerm_subnet.gpu"] = records.pop(
                    "azurerm_subnet.private_endpoints"
                )
            with self.subTest(kind=kind), patch.object(
                bridge.shared, "arm", side_effect=[endpoint, nic]
            ), self.assertRaises(bridge.shared.SharedError):
                bridge.reject_attached_children(records)

    def test_other_attachment_types_and_unowned_endpoint_still_fail(self):
        for field in ("serviceAssociationLinks", "resourceNavigationLinks"):
            records, endpoint, nic = self.fixture()
            records["azurerm_subnet.private_endpoints"]["properties"][field] = [
                {"id": "/foreign"}
            ]
            with patch.object(
                bridge.shared, "arm", side_effect=[endpoint, nic]
            ), self.assertRaises(bridge.shared.SharedError):
                bridge.reject_attached_children(records)
        records, _, _ = self.fixture()
        records["azurerm_subnet.private_endpoints"]["properties"][
            "privateEndpoints"
        ] = []
        with patch.object(bridge.shared, "arm") as read, self.assertRaises(
            bridge.shared.SharedError
        ):
            bridge.reject_attached_children(records)
        read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
