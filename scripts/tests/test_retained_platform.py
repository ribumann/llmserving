import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import azure_operator_access as operator
import azure_retained_platform as platform
import azure_shared_lifecycle as shared


class RetainedPlatformTests(unittest.TestCase):
    def test_exact_five_external_nsgs_preserved_get_only(self):
        for identifier, subnet in platform.EXTERNAL_NSGS.items():
            metadata = {
                "id": identifier,
                "name": identifier.rsplit("/", 1)[1],
                "type": "Microsoft.Network/networkSecurityGroups",
                "location": platform.REGION,
                "tags": platform.TAGS,
                "properties": {
                    "provisioningState": "Succeeded",
                    "securityRules": [],
                    "defaultSecurityRules": [
                        {"name": name} for name in platform.DEFAULT_NSG_RULE_NAMES
                    ],
                    "subnets": (
                        [{"id": subnet}] if "-containerapps-" in identifier else None
                    ),
                },
            }
            with patch.object(platform, "az", return_value=metadata) as read:
                self.assertTrue(
                    platform.preserve_external_nsg({"id": identifier.upper()})
                )
                read.assert_called_once_with(
                    "rest",
                    "--method",
                    "GET",
                    "--url",
                    f"https://management.azure.com{identifier}?api-version=2023-09-01",
                )
            for mutation in (
                "tags",
                "type",
                "location",
                "rules",
                "subnet",
                "extra",
                "nic",
                "pending",
            ):
                import copy

                changed = copy.deepcopy(metadata)
                if mutation in ("tags", "type", "location"):
                    changed[mutation] = {} if mutation == "tags" else "foreign"
                elif mutation == "rules":
                    changed["properties"]["securityRules"] = [{"name": "unexpected"}]
                elif mutation == "subnet":
                    changed["properties"]["subnets"] = [{"id": "/foreign"}]
                elif mutation == "extra":
                    changed["properties"]["subnets"] = [{"id": subnet}, {"id": subnet}]
                elif mutation == "nic":
                    changed["properties"]["networkInterfaces"] = [{"id": "/foreign"}]
                else:
                    changed["properties"]["provisioningState"] = "Updating"
                with (
                    self.subTest(mutation=mutation),
                    patch.object(platform, "az", return_value=changed),
                    self.assertRaises(platform.ReleaseImportError),
                ):
                    platform.preserve_external_nsg({"id": identifier})
            self.assertNotIn(
                identifier, [item["id"] for item in operator.scope.RESOURCES.values()]
            )
            self.assertNotIn(
                identifier, [item["id"] for item in shared.scope.RESOURCES.values()]
            )
        with patch.object(platform, "az") as read:
            self.assertFalse(
                platform.preserve_external_nsg({"id": identifier + "-foreign"})
            )
            read.assert_not_called()

    def metadata(self):
        topic = {
            "id": platform.TOPIC,
            "name": platform.NAME,
            "type": "Microsoft.EventGrid/systemTopics",
            "location": platform.REGION,
            "tags": None,
            "properties": {
                "source": platform.ACCOUNT.lower(),
                "topicType": "microsoft.storage.storageaccounts",
                "provisioningState": "Succeeded",
            },
        }
        subscription = {
            "value": [
                {
                    "id": platform.SUBSCRIPTION,
                    "name": "StorageAntimalwareSubscription",
                    "properties": {
                        "provisioningState": "Succeeded",
                        "destination": {"endpointType": "WebHook"},
                    },
                }
            ]
        }
        return topic, subscription

    def test_exact_preserve_only_get_calls_no_destination_logging(self):
        with patch.object(platform, "az", side_effect=self.metadata()) as azure:
            self.assertTrue(platform.preserve_storage_topic({"id": platform.TOPIC}))
            self.assertEqual(azure.call_count, 2)
            for call in azure.call_args_list:
                self.assertEqual(call.args[:3], ("rest", "--method", "GET"))
        with patch.object(platform, "az") as azure:
            self.assertFalse(
                platform.preserve_storage_topic({"id": platform.TOPIC + "-foreign"})
            )
            azure.assert_not_called()
        self.assertNotIn(
            platform.TOPIC, [value["id"] for value in shared.scope.RESOURCES.values()]
        )
        self.assertNotIn(
            platform.TOPIC, [value["id"] for value in operator.scope.RESOURCES.values()]
        )

    def test_foreign_source_type_name_and_subscription_fail_closed(self):
        for field in ("id", "name", "type", "location"):
            topic, subscriptions = self.metadata()
            topic[field] = "foreign"
            with (
                patch.object(platform, "az", side_effect=[topic, subscriptions]),
                self.assertRaises(platform.ReleaseImportError),
            ):
                platform.preserve_storage_topic({"id": platform.TOPIC})
        for field in ("source", "topicType", "provisioningState"):
            topic, subscriptions = self.metadata()
            topic["properties"][field] = "foreign"
            with (
                patch.object(platform, "az", side_effect=[topic, subscriptions]),
                self.assertRaises(platform.ReleaseImportError),
            ):
                platform.preserve_storage_topic({"id": platform.TOPIC})
        for kind in ("missing", "extra", "next", "name", "id", "endpoint", "failed"):
            topic, subscriptions = self.metadata()
            if kind == "missing":
                subscriptions["value"] = []
            elif kind == "extra":
                subscriptions["value"] *= 2
            elif kind == "next":
                subscriptions["nextLink"] = "foreign"
            elif kind in ("name", "id"):
                subscriptions["value"][0][kind] = "foreign"
            elif kind == "endpoint":
                subscriptions["value"][0]["properties"]["destination"][
                    "endpointType"
                ] = "foreign"
            else:
                subscriptions["value"][0]["properties"]["provisioningState"] = "Failed"
            with (
                patch.object(platform, "az", side_effect=[topic, subscriptions]),
                self.assertRaises(platform.ReleaseImportError),
            ):
                platform.preserve_storage_topic({"id": platform.TOPIC})

    def test_operator_inventory_excludes_verified_topic_from_deletion(self):
        selected = {
            "expires_at": "2026-11-05T21:55:55Z",
            "root_certificate_sha256": "a" * 64,
        }
        vnet = {"tags": operator.scope.shared.TAGS, "properties": {"subnets": []}}
        with (
            patch.object(operator, "az", return_value=[{"id": platform.TOPIC}]),
            patch.object(shared, "arm", return_value=vnet),
            patch.object(platform, "az", side_effect=self.metadata()),
        ):
            self.assertEqual(operator.inventory(selected), {})


if __name__ == "__main__":
    unittest.main()
