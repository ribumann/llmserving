"""Strict seven-resource operator-access native plan gate; no apply authorization."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from functools import partial
from pathlib import Path

import validate_shared_plan as shared
from validate_retained_group_plan import PlanRejected, run_saved_plan, validate_plan

ROOT = shared.ROOT
VNET = f"{ROOT}/providers/Microsoft.Network/virtualNetworks/llmrelease-shared-vnet"
ZONE = f"{ROOT}/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
ACCOUNT = f"{ROOT}/providers/Microsoft.Storage/storageAccounts/llmreleasestate0ea5e6"
RESOURCES = {
    "azurerm_subnet.gateway": {
        "id": f"{VNET}/subnets/GatewaySubnet",
        "name": "GatewaySubnet",
        "virtual_network_name": "llmrelease-shared-vnet",
        "address_prefixes": ["10.20.30.0/27"],
        "default_outbound_access_enabled": False,
    },
    "azurerm_subnet.dns": {
        "id": f"{VNET}/subnets/snet-operator-dns",
        "name": "snet-operator-dns",
        "virtual_network_name": "llmrelease-shared-vnet",
        "address_prefixes": ["10.20.31.0/28"],
        "default_outbound_access_enabled": False,
    },
    "azurerm_public_ip.gateway": {
        "id": f"{ROOT}/providers/Microsoft.Network/publicIPAddresses/llmrelease-operator-vpn-pip",
        "name": "llmrelease-operator-vpn-pip",
        "allocation_method": "Static",
        "sku": "Standard",
    },
    "azurerm_virtual_network_gateway.operator": {
        "id": f"{ROOT}/providers/Microsoft.Network/virtualNetworkGateways/llmrelease-operator-vpn",
        "name": "llmrelease-operator-vpn",
        "type": "Vpn",
        "vpn_type": "RouteBased",
        "sku": "VpnGw1",
        "generation": "Generation1",
        "active_active": False,
        "enable_bgp": False,
    },
    "azurerm_private_dns_resolver.operator": {
        "id": f"{ROOT}/providers/Microsoft.Network/dnsResolvers/llmrelease-operator-dns",
        "name": "llmrelease-operator-dns",
        "virtual_network_id": VNET,
    },
    "azurerm_private_dns_resolver_inbound_endpoint.operator": {
        "id": f"{ROOT}/providers/Microsoft.Network/dnsResolvers/llmrelease-operator-dns/inboundEndpoints/llmrelease-operator-dns-inbound",
        "name": "llmrelease-operator-dns-inbound",
    },
    "azurerm_private_endpoint.state": {
        "id": f"{ROOT}/providers/Microsoft.Network/privateEndpoints/llmrelease-state-pe",
        "name": "llmrelease-state-pe",
        "subnet_id": f"{VNET}/subnets/snet-private-endpoints",
    },
}
DATA = {
    "data.azurerm_resource_group.shared": ROOT,
    "data.azurerm_virtual_network.shared": VNET,
    "data.azurerm_subnet.endpoints": f"{VNET}/subnets/snet-private-endpoints",
    "data.azurerm_private_dns_zone.blob": ZONE,
}


def single(value: object) -> dict:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise PlanRejected("Expected exactly one reviewed operator-access block.")
    return value[0]


def validate_values(
    plan: dict, address: str, values: object, target: dict, *, existing: bool
) -> None:
    values = shared.obj(values)
    tagged = not address.startswith("azurerm_subnet.")
    expected = dict(RESOURCES[address])
    if address != "azurerm_private_dns_resolver_inbound_endpoint.operator":
        expected["resource_group_name"] = shared.GROUP
    if tagged:
        expected.update(
            {
                "location": shared.REGION,
                "tags": {
                    **shared.TAGS,
                    "component": "operator-access",
                    "cleanupAfter": target["expires_at"],
                    "rootCertificate": target["root_certificate_sha256"],
                },
            }
        )
    for key, selected in expected.items():
        if key == "id" and not existing and values.get(key) is None:
            continue
        if not shared.equal(values.get(key), selected):
            raise PlanRejected(
                "Operator resource ID/name/network/security/tags differ."
            )

    def binding(block: dict, key: str, resource: str) -> None:
        if block.get(key) is not None:
            if not shared.equal(block[key], RESOURCES[resource]["id"]):
                raise PlanRejected("Operator access references a foreign resource.")
        elif existing:
            raise PlanRejected("Existing operator resource binding must be known.")
        else:
            expressions = shared.obj(
                shared.configuration_record(plan, address).get("expressions")
            )
            expression = expressions.get(key)
            if expression is None:
                # Nested native HCL blocks carry their own expression list.
                for name in ("ip_configuration", "ip_configurations"):
                    if name in expressions:
                        expression = single(expressions[name]).get(key)
            shared.validate_reference(expression, resource)

    if address == "azurerm_subnet.dns":
        delegation = single(values.get("delegation"))
        service = single(delegation.get("service_delegation"))
        if (
            delegation.get("name") != "dns-resolver"
            or service.get("name") != "Microsoft.Network/dnsResolvers"
            or service.get("actions")
            != ["Microsoft.Network/virtualNetworks/subnets/join/action"]
        ):
            raise PlanRejected("Unexpected DNS subnet delegation.")
    elif address == "azurerm_subnet.gateway":
        if values.get("delegation", []) != []:
            raise PlanRejected("Gateway subnet must not have a service delegation.")
    elif address == "azurerm_virtual_network_gateway.operator":
        configuration = single(values.get("ip_configuration"))
        if (
            configuration.get("name") != "operator-vpn"
            or configuration.get("private_ip_address_allocation") != "Dynamic"
        ):
            raise PlanRejected("Unexpected gateway IP configuration.")
        binding(configuration, "subnet_id", "azurerm_subnet.gateway")
        binding(configuration, "public_ip_address_id", "azurerm_public_ip.gateway")
        clients = single(values.get("vpn_client_configuration"))
        if (
            clients.get("address_space") != ["172.29.240.0/24"]
            or clients.get("vpn_client_protocols") != ["OpenVPN"]
            or clients.get("vpn_auth_types") != ["Certificate"]
        ):
            raise PlanRejected(
                "VPN must use only the fixed pool and certificate/OpenVPN authentication."
            )
        certificate = single(clients.get("root_certificate"))
        if (
            certificate.get("name") != "llmrelease-operator-root"
            or certificate.get("public_cert_data")
            != target["root_certificate_public_data"]
        ):
            raise PlanRejected(
                "VPN root certificate differs from independently approved public root."
            )
        if any(
            clients.get(field) not in (None, "", [])
            for field in (
                "aad_tenant",
                "aad_audience",
                "aad_issuer",
                "radius_server_address",
                "radius_server_secret",
                "radius_server",
                "revoked_certificate",
                "virtual_network_gateway_client_connection",
            )
        ):
            raise PlanRejected("Unexpected VPN auth/secret/connection settings.")
    elif address == "azurerm_private_dns_resolver_inbound_endpoint.operator":
        binding(
            values, "private_dns_resolver_id", "azurerm_private_dns_resolver.operator"
        )
        configuration = single(values.get("ip_configurations"))
        if (
            configuration.get("private_ip_allocation_method") != "Static"
            or configuration.get("private_ip_address") != "10.20.31.4"
        ):
            raise PlanRejected("Unexpected resolver inbound address.")
        binding(configuration, "subnet_id", "azurerm_subnet.dns")
    elif address == "azurerm_private_endpoint.state":
        connection = single(values.get("private_service_connection"))
        if (
            connection.get("name") != "llmrelease-state-blob"
            or not shared.equal(
                connection.get("private_connection_resource_id"), ACCOUNT
            )
            or connection.get("subresource_names") != ["blob"]
            or connection.get("is_manual_connection") is not False
        ):
            raise PlanRejected(
                "State endpoint must select only the exact existing account blob subresource."
            )
        groups = values.get("private_dns_zone_group")
        if groups == [] and existing:
            return
        group = single(groups)
        if group.get("name") != "state-blob-zone-group" or not shared.equal(
            group.get("private_dns_zone_ids"), [ZONE]
        ):
            raise PlanRejected("State endpoint DNS group differs.")


def validate(plan: object, group: str, *, operation: str, target: dict) -> None:
    if operation not in {"create", "destroy"} or group != shared.GROUP:
        raise PlanRejected("Only fixed operator access create/destroy is supported.")
    if set(target) != {
        "root_certificate_public_data",
        "root_certificate_sha256",
        "expires_at",
    }:
        raise PlanRejected(
            "Exact independent public certificate/deadline target is required."
        )
    try:
        certificate = base64.b64decode(
            target["root_certificate_public_data"], validate=True
        )
    except (ValueError, TypeError):
        raise PlanRejected("Malformed public certificate encoding.") from None
    if hashlib.sha256(certificate).hexdigest() != target["root_certificate_sha256"]:
        raise PlanRejected(
            "Public certificate does not match the independent DER fingerprint."
        )
    validate_plan(plan, group)
    plan = shared.obj(plan)
    config = shared.obj(plan.get("configuration"))
    providers = shared.obj(config.get("provider_config"))
    if (
        set(providers) != {"azurerm"}
        or shared.obj(providers["azurerm"]).get("full_name")
        != "registry.terraform.io/hashicorp/azurerm"
    ):
        raise PlanRejected("Only the reviewed default AzureRM provider is supported.")
    provider = shared.obj(providers["azurerm"])
    if shared.obj(provider.get("expressions")).get("subscription_id") != {
        "references": ["var.subscription_id"]
    }:
        raise PlanRejected(
            "Operator provider must bind the fixed subscription variable."
        )
    configuration = shared.obj(config.get("root_module"))
    if configuration.get("module_calls", {}) != {}:
        raise PlanRejected("Operator module must not delegate or use provisioners.")
    required = set(RESOURCES) | set(DATA) | {"data.azurerm_client_config.current"}
    found = set()
    for record in configuration.get("resources", []):
        if (
            not isinstance(record, dict)
            or record.get("address") not in required
            or record.get("provider_config_key") != "azurerm"
            or record.get("provisioners", []) != []
            or record["address"] in found
        ):
            raise PlanRejected(
                "Unexpected operator configuration address/provider/provisioner."
            )
        found.add(record["address"])
    if found != required:
        raise PlanRejected(
            "Operator configuration is missing exact resource/data bindings."
        )
    for name, value in {
        "subscription_id": shared.FALLBACK_TARGET.subscription,
        **target,
    }.items():
        if (
            shared.obj(shared.obj(plan.get("variables")).get(name)).get("value")
            != value
        ):
            raise PlanRejected("Operator plan inputs differ from independent target.")
    prior = plan.get("prior_state", {}).get("values", {}).get("root_module", {})
    planned = shared.obj(plan.get("planned_values")).get("root_module")
    sets = []
    for module, existing in ((prior, True), (planned, False)):
        seen = set()
        for record in shared.module_records(module):
            address = record.get("address")
            if address in seen:
                raise PlanRejected("Duplicate operator resource.")
            if record.get("mode") == "managed":
                if (
                    address not in RESOURCES
                    or record.get("type") != address.split(".")[0]
                    or operation == "create"
                    and existing
                    or operation == "destroy"
                    and not existing
                ):
                    raise PlanRejected("Unexpected prior/planned operator ownership.")
                validate_values(
                    plan, address, record.get("values"), target, existing=existing
                )
                seen.add(address)
            elif record.get("mode") == "data":
                values = shared.obj(record.get("values"))
                if address in DATA:
                    if not shared.equal(values.get("id"), DATA[address]):
                        raise PlanRejected("Foreign operator existing-resource data.")
                elif address == "data.azurerm_client_config.current":
                    if (
                        values.get("subscription_id")
                        != shared.FALLBACK_TARGET.subscription
                        or values.get("tenant_id") != shared.FALLBACK_TARGET.tenant
                    ):
                        raise PlanRejected(
                            "Foreign operator provider tenant/subscription."
                        )
                else:
                    raise PlanRejected(
                        "Unexpected operator data source, including storage key reads."
                    )
            else:
                raise PlanRejected("Unknown operator record mode.")
        sets.append(seen)
    changes = set()
    for record in plan.get("resource_changes", []):
        if record.get("mode") == "data":
            continue
        address = record.get("address")
        change = shared.obj(record.get("change"))
        if (
            address not in RESOURCES
            or address in changes
            or change.get("actions")
            != (["create"] if operation == "create" else ["delete"])
            or change.get("before" if operation == "create" else "after") is not None
        ):
            raise PlanRejected(
                "Only exact fresh creates or pure owned operator deletes are supported."
            )
        validate_values(
            plan,
            address,
            change.get("after" if operation == "create" else "before"),
            target,
            existing=operation == "destroy",
        )
        changes.add(address)
    if (
        changes != sets[1 if operation == "create" else 0]
        or operation == "create"
        and changes != set(RESOURCES)
    ):
        raise PlanRejected(
            "Operator changes do not cover the exact seven create/owned delete set."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--private-log", type=Path, required=True)
    parser.add_argument("--operation", choices=("create", "destroy"), required=True)
    parser.add_argument("--terraform-bin", default="terraform")
    args = parser.parse_args()
    try:
        target = json.loads(args.target.read_text())
        run_saved_plan(
            args.plan,
            shared.GROUP,
            args.private_log,
            terraform=args.terraform_bin,
            apply=False,
            validator=partial(validate, operation=args.operation, target=target),
        )
    except (PlanRejected, OSError, ValueError) as error:
        raise SystemExit(f"Operator access plan stopped: {error}") from None
    print(
        "Fixed operator access scope passed; no apply, private connectivity or cleanup proof."
    )


if __name__ == "__main__":
    main()
