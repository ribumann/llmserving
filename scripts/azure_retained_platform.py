"""Exact preserve-only recognition of observed external platform resources."""

from __future__ import annotations

from azure_release_import import ReleaseImportError, az
from validate_shared_plan import REGION, ROOT, TAGS, equal

ACCOUNT = f"{ROOT}/providers/Microsoft.Storage/storageAccounts/llmreleasestate0ea5e6"
NAME = "llmreleasestate0ea5e6-e8ee3cde-435b-41d3-bd0b-ec07e5d98c99"
TOPIC = f"{ROOT}/providers/Microsoft.EventGrid/systemTopics/{NAME}"
SUBSCRIPTION = f"{TOPIC}/eventSubscriptions/StorageAntimalwareSubscription"
EXTERNAL_NSGS = {
    f"{ROOT}/providers/Microsoft.Network/networkSecurityGroups/"
    f"llmrelease-shared-vnet-snet-{name}-nsg-italynorth": f"{ROOT}/providers/Microsoft.Network/virtualNetworks/"
    f"llmrelease-shared-vnet/subnets/snet-{name}"
    for name in (
        "private-endpoints",
        "functions",
        "operator-dns",
        "data",
        "containerapps",
    )
}
DEFAULT_NSG_RULE_NAMES = {
    "AllowVnetInBound",
    "AllowAzureLoadBalancerInBound",
    "DenyAllInBound",
    "AllowVnetOutBound",
    "AllowInternetOutBound",
    "DenyAllOutBound",
}


def preserve_external_nsg(record: dict) -> bool:
    identifier = next(
        (
            identifier
            for identifier in EXTERNAL_NSGS
            if equal(record.get("id"), identifier)
        ),
        None,
    )
    if identifier is None:
        return False
    metadata = az(
        "rest",
        "--method",
        "GET",
        "--url",
        f"https://management.azure.com{identifier}?api-version=2023-09-01",
    )
    properties = metadata.get("properties") if isinstance(metadata, dict) else None
    if (
        not isinstance(metadata, dict)
        or not equal(metadata.get("id"), identifier)
        or metadata.get("name") != identifier.rsplit("/", 1)[1]
        or not isinstance(metadata.get("type"), str)
        or metadata["type"].casefold() != "microsoft.network/networksecuritygroups"
        or metadata.get("location") != REGION
        or metadata.get("tags") != TAGS
        or not isinstance(properties, dict)
        or properties.get("provisioningState") != "Succeeded"
        or properties.get("securityRules") != []
        or properties.get("networkInterfaces") not in (None, [])
    ):
        raise ReleaseImportError("Exact externally created NSG metadata differs.")
    subnets = properties.get("subnets")
    rules = properties.get("defaultSecurityRules")
    if (
        not isinstance(rules, list)
        or len(rules) != 6
        or any(not isinstance(rule, dict) for rule in rules)
        or {rule.get("name") for rule in rules} != DEFAULT_NSG_RULE_NAMES
    ):
        raise ReleaseImportError("External NSG default rule identities differ.")
    if identifier != next(
        item for item in EXTERNAL_NSGS if item.endswith("-containerapps-nsg-italynorth")
    ):
        if subnets not in (None, []):
            raise ReleaseImportError("External NSG must remain exactly unattached.")
        return True
    if (
        not isinstance(subnets, list)
        or len(subnets) != 1
        or not isinstance(subnets[0], dict)
        or not equal(subnets[0].get("id"), EXTERNAL_NSGS[identifier])
    ):
        raise ReleaseImportError(
            "External NSG must bind only its exact observed subnet."
        )
    # Recognition is never a Terraform address or permission to mutate the NSG.
    return True


def preserve_storage_topic(record: dict) -> bool:
    if not equal(record.get("id"), TOPIC):
        return False
    metadata = az(
        "rest",
        "--method",
        "GET",
        "--url",
        f"https://management.azure.com{TOPIC}?api-version=2022-06-15",
    )
    if not isinstance(metadata, dict):
        raise ReleaseImportError("Retained platform topic metadata is unverified.")
    properties = metadata.get("properties")
    if (
        not equal(metadata.get("id"), TOPIC)
        or metadata.get("name") != NAME
        or not isinstance(metadata.get("type"), str)
        or metadata["type"].casefold() != "microsoft.eventgrid/systemtopics"
        or metadata.get("location") != REGION
        or metadata.get("tags") not in (None, {})
        or not isinstance(properties, dict)
        or not equal(properties.get("source"), ACCOUNT)
        or not isinstance(properties.get("topicType"), str)
        or properties["topicType"].casefold() != "microsoft.storage.storageaccounts"
        or properties.get("provisioningState") != "Succeeded"
    ):
        raise ReleaseImportError(
            "Exact retained storage platform topic identity/source differs."
        )
    subscriptions = az(
        "rest",
        "--method",
        "GET",
        "--url",
        f"https://management.azure.com{TOPIC}/eventSubscriptions?api-version=2022-06-15",
    )
    if (
        not isinstance(subscriptions, dict)
        or subscriptions.get("nextLink")
        or not isinstance(subscriptions.get("value"), list)
        or len(subscriptions["value"]) != 1
    ):
        raise ReleaseImportError(
            "Retained platform subscription inventory is incomplete."
        )
    subscription = subscriptions["value"][0]
    details = subscription.get("properties") if isinstance(subscription, dict) else None
    destination = details.get("destination") if isinstance(details, dict) else None
    if (
        not isinstance(subscription, dict)
        or not equal(subscription.get("id"), SUBSCRIPTION)
        or subscription.get("name") != "StorageAntimalwareSubscription"
        or not isinstance(details, dict)
        or details.get("provisioningState") != "Succeeded"
        or not isinstance(destination, dict)
        or destination.get("endpointType") != "WebHook"
    ):
        raise ReleaseImportError(
            "Exact retained antimalware subscription identity differs."
        )
    # Never return a managed address: neither topic nor subscription is ours to delete.
    return True
