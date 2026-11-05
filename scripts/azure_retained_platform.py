"""Preserve-only recognition of one verified storage antimalware system topic."""

from __future__ import annotations

from azure_release_import import ReleaseImportError, az
from validate_shared_plan import REGION, ROOT, equal

ACCOUNT = f"{ROOT}/providers/Microsoft.Storage/storageAccounts/llmreleasestate0ea5e6"
NAME = "llmreleasestate0ea5e6-e8ee3cde-435b-41d3-bd0b-ec07e5d98c99"
TOPIC = f"{ROOT}/providers/Microsoft.EventGrid/systemTopics/{NAME}"
SUBSCRIPTION = f"{TOPIC}/eventSubscriptions/StorageAntimalwareSubscription"


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
