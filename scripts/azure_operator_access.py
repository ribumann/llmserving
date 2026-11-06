"""Independent fixed operator-access ARM cleanup; never deletes shared roots."""

from __future__ import annotations

from operator_config import setting

import argparse
import os
import re
from datetime import UTC, datetime

import azure_shared_lifecycle as lifecycle
import validate_operator_access_plan as scope
from azure_disk_probe import mask_subject
from azure_release_import import ReleaseImportError, az
from azure_retained_platform import preserve_external_nsg, preserve_storage_topic

WORKFLOW = ".github/workflows/azure-operator-access-cleanup.yml"
ORDER = [
    "azurerm_virtual_network_gateway.operator",
    "azurerm_private_dns_resolver_inbound_endpoint.operator",
    "azurerm_private_endpoint.state",
    "azurerm_private_dns_resolver.operator",
    "azurerm_subnet.dns",
    "azurerm_subnet.gateway",
    "azurerm_public_ip.gateway",
]
DNS_RESOURCE_GUID = setting("dns_resource_guid")
DNS_PLATFORM_IPCONFIG = setting("dns_platform_ipconfig")


def resolver_platform_attachments(details: dict, expected_tags: dict) -> bool:
    """Recognize only this observed owned endpoint's platform backlinks; GET owned ID only."""
    subnet = scope.RESOURCES["azurerm_subnet.dns"]["id"]
    endpoint = scope.RESOURCES[
        "azurerm_private_dns_resolver_inbound_endpoint.operator"
    ]["id"]
    links = details.get("serviceAssociationLinks", [])
    configurations = details.get("ipConfigurations", [])
    if not links and not configurations:
        return False
    if (
        not isinstance(links, list)
        or len(links) != 1
        or not isinstance(links[0], dict)
        or not scope.shared.equal(
            links[0].get("id"), f"{subnet}/serviceAssociationLinks/dnsResolverLink"
        )
        or not isinstance(configurations, list)
        or len(configurations) != 1
        or not isinstance(configurations[0], dict)
        or not scope.shared.equal(configurations[0].get("id"), DNS_PLATFORM_IPCONFIG)
    ):
        raise lifecycle.SharedError("DNS platform attachment identity differs.")
    properties = links[0].get("properties")
    if (
        not isinstance(properties, dict)
        or properties.get("linkedResourceType") != "Microsoft.Network/dnsResolvers"
        or properties.get("link") != f"/InboundEndpoint/{DNS_RESOURCE_GUID}"
        or properties.get("provisioningState") != "Succeeded"
        or properties.get("allowDelete") is not False
    ):
        raise lifecycle.SharedError("DNS platform association metadata differs.")
    owned = lifecycle.arm(endpoint, "2022-07-01")
    properties = owned.get("properties")
    if (
        not scope.shared.equal(owned.get("id"), endpoint)
        or owned.get("tags") != expected_tags
        or owned.get("location") != scope.shared.REGION
        or not isinstance(properties, dict)
        or properties.get("resourceGuid") != DNS_RESOURCE_GUID
        or properties.get("provisioningState") != "Succeeded"
    ):
        raise lifecycle.SharedError("Owned inbound endpoint platform identity differs.")
    configurations = properties.get("ipConfigurations")
    if not isinstance(configurations, list) or len(configurations) != 1:
        raise lifecycle.SharedError("Owned inbound endpoint IP configuration differs.")
    configuration = configurations[0]
    if not isinstance(configuration, dict):
        raise lifecycle.SharedError("Malformed owned inbound IP configuration.")
    if (
        configuration.get("privateIpAddress") != "10.20.31.4"
        or configuration.get("privateIpAllocationMethod") != "Static"
        or not isinstance(configuration.get("subnet"), dict)
        or not scope.shared.equal(configuration["subnet"].get("id"), subnet)
    ):
        raise lifecycle.SharedError("Owned inbound endpoint subnet/address differs.")
    return True


def target() -> dict:
    expected = {
        "GITHUB_REPOSITORY": lifecycle.REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": f"{lifecycle.REPOSITORY}/{WORKFLOW}@refs/heads/main",
        "OPERATOR_ACCESS_CLEANUP_ARMED": "true",
        "AZURE_SUBSCRIPTION_ID": lifecycle.FALLBACK_TARGET.subscription,
        "AZURE_TENANT_ID": lifecycle.FALLBACK_TARGET.tenant,
        "AZURE_CLIENT_ID": lifecycle.FALLBACK_TARGET.client,
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise lifecycle.SharedError(
            "Operator cleanup is not armed in its exact protected workflow."
        )
    if os.environ.get("GITHUB_EVENT_NAME") not in {"workflow_dispatch", "schedule"}:
        raise lifecycle.SharedError("Unsupported operator cleanup event.")
    digest = os.environ.get("OPERATOR_ACCESS_ROOT_SHA256", "")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise lifecycle.SharedError("Exact public root fingerprint is required.")
    expiry = os.environ.get("OPERATOR_ACCESS_EXPIRES_AT", "")
    lifecycle.utc(expiry)
    return {"root_certificate_sha256": digest, "expires_at": expiry}


def identity() -> None:
    account = az("account", "show")
    if (
        not isinstance(account, dict)
        or account.get("id") != lifecycle.FALLBACK_TARGET.subscription
        or account.get("tenantId") != lifecycle.FALLBACK_TARGET.tenant
        or not isinstance(account.get("user"), dict)
        or account["user"].get("name") != lifecycle.FALLBACK_TARGET.client
        or account["user"].get("type") != "servicePrincipal"
    ):
        raise lifecycle.SharedError(
            "Only the existing isolated UAMI may clean operator access."
        )
    group = az("group", "show", "--name", lifecycle.GROUP)
    if (
        not isinstance(group, dict)
        or not scope.shared.equal(group.get("id"), scope.ROOT)
        or group.get("tags") != lifecycle.FALLBACK_TARGET.group_tags
    ):
        raise lifecycle.SharedError("Retained shared group ownership differs.")


def inventory(selected: dict) -> dict:
    records = az("resource", "list", "--resource-group", lifecycle.GROUP)
    if not isinstance(records, list):
        raise lifecycle.SharedError("Operator-access inventory is unverified.")
    known = {
        value["id"].casefold(): address for address, value in scope.RESOURCES.items()
    }
    shared_ids = {value["id"].casefold() for value in scope.shared.RESOURCES.values()}
    expected_tags = {
        **scope.shared.TAGS,
        "component": "operator-access",
        "cleanupAfter": selected["expires_at"],
        "rootCertificate": selected["root_certificate_sha256"],
    }
    found = {}
    generated = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise lifecycle.SharedError("Malformed operator-access ARM resource.")
        identifier = record["id"]
        address = known.get(identifier.casefold())
        if address:
            if address in found or (
                not address.startswith("azurerm_subnet.")
                and record.get("tags") != expected_tags
            ):
                raise lifecycle.SharedError(
                    "Operator resource tags/identity differ from the exact approved campaign."
                )
            found[address] = record
        elif identifier.casefold() in shared_ids or scope.shared.equal(
            identifier, scope.ACCOUNT
        ):
            continue
        else:
            generated.append(record)
    vnet = lifecycle.arm(scope.VNET, "2023-09-01")
    if vnet.get("tags") != scope.shared.TAGS:
        raise lifecycle.SharedError(
            "Operator subnets lack their exact owned shared VNet parent."
        )
    properties = vnet.get("properties")
    if not isinstance(properties, dict) or not isinstance(
        properties.get("subnets"), list
    ):
        raise lifecycle.SharedError("Operator subnet inventory is incomplete.")
    for subnet in properties["subnets"]:
        if not isinstance(subnet, dict) or not isinstance(subnet.get("id"), str):
            raise lifecycle.SharedError("Malformed shared subnet entry.")
        address = known.get(subnet["id"].casefold())
        if address is None:
            if subnet["id"].casefold() not in shared_ids:
                raise lifecycle.SharedError("Unknown subnet prevents operator cleanup.")
            continue
        expected = scope.RESOURCES[address]
        details = subnet.get("properties")
        if (
            not isinstance(details, dict)
            or details.get("addressPrefix") not in expected["address_prefixes"]
        ):
            raise lifecycle.SharedError("Operator subnet address range differs.")
        allowed_children = (
            {
                scope.RESOURCES["azurerm_virtual_network_gateway.operator"][
                    "id"
                ].casefold()
            }
            if address == "azurerm_subnet.gateway"
            else {
                scope.RESOURCES[
                    "azurerm_private_dns_resolver_inbound_endpoint.operator"
                ]["id"].casefold()
            }
        )
        platform = (
            resolver_platform_attachments(details, expected_tags)
            if address == "azurerm_subnet.dns"
            else False
        )
        for field in (
            "ipConfigurations",
            "privateEndpoints",
            "serviceAssociationLinks",
            "resourceNavigationLinks",
        ):
            children = details.get(field, [])
            if not isinstance(children, list):
                raise lifecycle.SharedError(
                    "Operator subnet attachment metadata is malformed."
                )
            if platform and field in {"ipConfigurations", "serviceAssociationLinks"}:
                continue
            for child in children:
                if not isinstance(child, dict) or not isinstance(child.get("id"), str):
                    raise lifecycle.SharedError("Unknown operator subnet attachment.")
                identifier = child["id"].casefold()
                if not any(
                    identifier == parent or identifier.startswith(f"{parent}/")
                    for parent in allowed_children
                ):
                    raise lifecycle.SharedError(
                        "Foreign attachment prevents operator subnet removal."
                    )
        found[address] = subnet
    for record in generated:
        if preserve_storage_topic(record) or preserve_external_nsg(record):
            continue
        identifier = record["id"]
        prefix = f"{scope.ROOT}/providers/Microsoft.Network/networkInterfaces/"
        if (
            identifier.casefold().startswith(prefix.casefold())
            and "/" not in identifier[len(prefix) :]
        ):
            nic = lifecycle.arm(identifier, "2023-09-01")
            properties = nic.get("properties")
            endpoint = (
                properties.get("privateEndpoint")
                if isinstance(properties, dict)
                else None
            )
            parent = endpoint.get("id") if isinstance(endpoint, dict) else None
            if any(
                scope.shared.equal(parent, value)
                for value in (
                    scope.RESOURCES["azurerm_private_endpoint.state"]["id"],
                    scope.shared.RESOURCES["azurerm_private_endpoint.vault"]["id"],
                )
            ):
                continue
        if scope.shared.equal(
            identifier,
            f"{scope.RESOURCES['azurerm_private_endpoint.state']['id']}/privateDnsZoneGroups/state-blob-zone-group",
        ):
            continue
        if scope.shared.equal(
            identifier,
            f"{scope.shared.RESOURCES['azurerm_private_endpoint.vault']['id']}/privateDnsZoneGroups/vault-zone-group",
        ):
            continue
        raise lifecycle.SharedError(
            "Unknown shared resource prevents operator cleanup; never broaden deletion."
        )
    return found


def cleanup(*, now: bool) -> None:
    selected = target()
    identity()
    if now and os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise lifecycle.SharedError(
            "Immediate operator cleanup requires protected manual dispatch."
        )
    inventory(selected)
    if not now and datetime.now(UTC) < lifecycle.utc(selected["expires_at"]):
        print(
            "Operator access ARM cleanup gate verified; fixed deadline not reached, no mutation."
        )
        return
    for address in ORDER:
        if address not in inventory(selected):
            continue
        identifier = scope.RESOURCES[address]["id"]
        api = "2022-07-01" if "/dnsResolvers/" in identifier else "2023-09-01"
        az(
            "rest",
            "--method",
            "DELETE",
            "--url",
            f"https://management.azure.com{identifier}?api-version={api}",
            decode=False,
        )
        if address in inventory(selected):
            raise lifecycle.SharedError(
                "Operator deletion is pending; independent retry required before deleting dependencies."
            )
    if inventory(selected):
        raise lifecycle.SharedError("Operator cleanup incomplete.")
    print(
        "Operator access absent; shared network/DNS/state/groups/grants retained. Canonical local state needs reconciliation."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", action="store_true")
    args = parser.parse_args()
    try:
        mask_subject()
        cleanup(now=args.now)
    except (lifecycle.SharedError, ReleaseImportError, OSError, ValueError) as error:
        raise SystemExit(f"Operator access cleanup stopped: {error}") from None


if __name__ == "__main__":
    main()
