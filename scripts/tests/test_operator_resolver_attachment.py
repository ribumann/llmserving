from __future__ import annotations

from scripts.tests import operator_fixture  # noqa: F401

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import azure_operator_access as operator


class ResolverAttachmentTests(unittest.TestCase):
    def fixture(self):
        subnet = operator.scope.RESOURCES["azurerm_subnet.dns"]["id"]
        endpoint = operator.scope.RESOURCES[
            "azurerm_private_dns_resolver_inbound_endpoint.operator"
        ]["id"]
        tags = {"exact": "synthetic-owned-tags"}
        details = {
            "addressPrefix": "10.20.31.0/28",
            "serviceAssociationLinks": [
                {
                    "id": f"{subnet}/serviceAssociationLinks/dnsResolverLink",
                    "properties": {
                        "linkedResourceType": "Microsoft.Network/dnsResolvers",
                        "link": f"/InboundEndpoint/{operator.DNS_RESOURCE_GUID}",
                        "provisioningState": "Succeeded",
                        "allowDelete": False,
                    },
                }
            ],
            "ipConfigurations": [{"id": operator.DNS_PLATFORM_IPCONFIG}],
        }
        owned = {
            "id": endpoint,
            "tags": tags,
            "location": operator.scope.shared.REGION,
            "properties": {
                "resourceGuid": operator.DNS_RESOURCE_GUID,
                "provisioningState": "Succeeded",
                "ipConfigurations": [
                    {
                        "privateIpAddress": "10.20.31.4",
                        "privateIpAllocationMethod": "Static",
                        "subnet": {"id": subnet},
                    }
                ],
            },
        }
        return details, owned, tags

    def test_exact_backlinks_get_only_owned_endpoint(self):
        details, owned, tags = self.fixture()
        details["ipConfigurations"][0]["id"] = details["ipConfigurations"][0][
            "id"
        ].upper()
        with patch.object(operator.lifecycle, "arm", return_value=owned) as read:
            self.assertTrue(operator.resolver_platform_attachments(details, tags))
            read.assert_called_once_with(owned["id"], "2022-07-01")
        with patch.object(operator.lifecycle, "arm") as read:
            self.assertFalse(operator.resolver_platform_attachments({}, tags))
            read.assert_not_called()

    def test_foreign_duplicate_or_changed_platform_metadata_rejected(self):
        for mutation in (
            "foreign-lb",
            "extra-lb",
            "foreign-link",
            "link-guid",
            "link-type",
            "allow-delete",
            "pending-link",
        ):
            details, _owned, tags = self.fixture()
            link = details["serviceAssociationLinks"][0]
            if mutation == "foreign-lb":
                details["ipConfigurations"][0]["id"] += "-foreign"
            elif mutation == "extra-lb":
                details["ipConfigurations"].append(
                    copy.deepcopy(details["ipConfigurations"][0])
                )
            elif mutation == "foreign-link":
                link["id"] += "-foreign"
            elif mutation == "link-guid":
                link["properties"]["link"] = "/InboundEndpoint/foreign"
            elif mutation == "link-type":
                link["properties"]["linkedResourceType"] = "foreign"
            elif mutation == "allow-delete":
                link["properties"]["allowDelete"] = True
            else:
                link["properties"]["provisioningState"] = "Updating"
            with (
                self.subTest(mutation=mutation),
                patch.object(operator.lifecycle, "arm") as read,
                self.assertRaises(operator.lifecycle.SharedError),
            ):
                operator.resolver_platform_attachments(details, tags)
            read.assert_not_called()

    def test_owned_endpoint_guid_tags_config_subnet_and_ip_bound(self):
        for mutation in (
            "id",
            "guid",
            "tags",
            "region",
            "pending",
            "extra-config",
            "ip",
            "dynamic",
            "subnet",
        ):
            details, owned, tags = self.fixture()
            properties = owned["properties"]
            config = properties["ipConfigurations"][0]
            if mutation == "id":
                owned["id"] += "-foreign"
            elif mutation == "guid":
                properties["resourceGuid"] = "foreign"
            elif mutation == "tags":
                owned["tags"] = {}
            elif mutation == "region":
                owned["location"] = "foreign"
            elif mutation == "pending":
                properties["provisioningState"] = "Updating"
            elif mutation == "extra-config":
                properties["ipConfigurations"].append(
                    copy.deepcopy(properties["ipConfigurations"][0])
                )
            elif mutation == "ip":
                config["privateIpAddress"] = "10.20.31.5"
            elif mutation == "dynamic":
                config["privateIpAllocationMethod"] = "Dynamic"
            else:
                config["subnet"]["id"] = "/foreign"
            with (
                self.subTest(mutation=mutation),
                patch.object(operator.lifecycle, "arm", return_value=owned),
                self.assertRaises(operator.lifecycle.SharedError),
            ):
                operator.resolver_platform_attachments(details, tags)


if __name__ == "__main__":
    unittest.main()
