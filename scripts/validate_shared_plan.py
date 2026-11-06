"""Fixed fallback shared-stack scope guard, not permission or cleanup approval."""

from __future__ import annotations

from operator_config import setting

import argparse
from functools import partial
from pathlib import Path

from azure_canary import FALLBACK_TARGET
from azure_release_import import GROUP, REGION, REGISTRY
from validate_retained_group_plan import PlanRejected, run_saved_plan, validate_plan

ROOT = f"/subscriptions/{FALLBACK_TARGET.subscription}/resourceGroups/{GROUP}"
TAGS = {
    **FALLBACK_TARGET.group_tags,
    "feature": "azure-llm-serving-demo",
    "component": "shared",
    "stage": "release",
}


def expected_resources() -> dict[str, dict]:
    resources = {}

    def add(kind, label, name, suffix, *, tagged=True, **fields):
        resources[f"azurerm_{kind}.{label}"] = {
            "id": f"{ROOT}/providers/{suffix}",
            "name": name,
            **({"tags": TAGS} if tagged else {}),
            **fields,
        }

    vnet = f"{ROOT}/providers/Microsoft.Network/virtualNetworks/{setting('resource_prefix')}-shared-vnet"
    add(
        "virtual_network",
        "shared",
        f"{setting('resource_prefix')}-shared-vnet",
        f"Microsoft.Network/virtualNetworks/{setting('resource_prefix')}-shared-vnet",
    )
    for label in ("containerapps", "functions", "data", "private_endpoints", "gpu"):
        name = f"snet-{label.replace('_', '-')}"
        add(
            "subnet",
            label,
            name,
            f"Microsoft.Network/virtualNetworks/{setting('resource_prefix')}-shared-vnet/subnets/{name}",
            tagged=False,
            virtual_network_name=f"{setting('resource_prefix')}-shared-vnet",
        )
    add(
        "network_security_group",
        "gpu",
        f"{setting('resource_prefix')}-gpu-nsg",
        f"Microsoft.Network/networkSecurityGroups/{setting('resource_prefix')}-gpu-nsg",
    )
    add(
        "public_ip",
        "nat",
        f"{setting('resource_prefix')}-shared-nat-pip",
        f"Microsoft.Network/publicIPAddresses/{setting('resource_prefix')}-shared-nat-pip",
    )
    add(
        "nat_gateway",
        "shared",
        f"{setting('resource_prefix')}-shared-natgw",
        f"Microsoft.Network/natGateways/{setting('resource_prefix')}-shared-natgw",
    )
    for label, zone in (
        ("postgres", "privatelink.postgres.database.azure.com"),
        ("vault", "privatelink.vaultcore.azure.net"),
        ("blob", "privatelink.blob.core.windows.net"),
        ("queue", "privatelink.queue.core.windows.net"),
        ("table", "privatelink.table.core.windows.net"),
    ):
        add(
            "private_dns_zone", label, zone, f"Microsoft.Network/privateDnsZones/{zone}"
        )
        name = f"{setting('resource_prefix')}-{label}-link"
        add(
            "private_dns_zone_virtual_network_link",
            label,
            name,
            f"Microsoft.Network/privateDnsZones/{zone}/virtualNetworkLinks/{name}",
            private_dns_zone_name=zone,
            virtual_network_id=vnet,
        )
    add(
        "container_registry",
        "shared",
        REGISTRY,
        f"Microsoft.ContainerRegistry/registries/{REGISTRY}",
        admin_enabled=False,
        sku="Basic",
    )
    add(
        "key_vault",
        "shared",
        f"{setting('resource_prefix')}-kv-{setting('resource_suffix')}",
        f"Microsoft.KeyVault/vaults/{setting('resource_prefix')}-kv-{setting('resource_suffix')}",
        tenant_id=FALLBACK_TARGET.tenant,
        enable_rbac_authorization=True,
        public_network_access_enabled=False,
    )
    add(
        "private_endpoint",
        "vault",
        f"{setting('resource_prefix')}-vault-pe",
        f"Microsoft.Network/privateEndpoints/{setting('resource_prefix')}-vault-pe",
        subnet_id=f"{vnet}/subnets/snet-private-endpoints",
    )
    add(
        "log_analytics_workspace",
        "shared",
        f"{setting('resource_prefix')}-law",
        f"Microsoft.OperationalInsights/workspaces/{setting('resource_prefix')}-law",
    )
    add(
        "application_insights",
        "shared",
        f"{setting('resource_prefix')}-appi",
        f"Microsoft.Insights/components/{setting('resource_prefix')}-appi",
        workspace_id=resources["azurerm_log_analytics_workspace.shared"]["id"],
    )
    return resources


RESOURCES = expected_resources()
ASSOCIATIONS = {
    "azurerm_subnet_network_security_group_association.gpu": {
        "subnet_id": "azurerm_subnet.gpu",
        "network_security_group_id": "azurerm_network_security_group.gpu",
    },
    "azurerm_nat_gateway_public_ip_association.shared": {
        "nat_gateway_id": "azurerm_nat_gateway.shared",
        "public_ip_address_id": "azurerm_public_ip.nat",
    },
    **{
        f"azurerm_subnet_nat_gateway_association.{label}": {
            "subnet_id": f"azurerm_subnet.{label}",
            "nat_gateway_id": "azurerm_nat_gateway.shared",
        }
        for label in ("containerapps", "functions", "gpu")
    },
}
ADDRESSES = set(RESOURCES) | set(ASSOCIATIONS)


def obj(value: object) -> dict:
    if not isinstance(value, dict):
        raise PlanRejected("Malformed fixed shared-stack plan.")
    return value


def equal(actual: object, expected: object) -> bool:
    if isinstance(expected, str) and expected.startswith("/subscriptions/"):
        return isinstance(actual, str) and actual.casefold() == expected.casefold()
    return type(actual) is type(expected) and actual == expected


def configuration_record(plan: dict, address: str) -> dict:
    config = obj(obj(plan.get("configuration")).get("root_module"))
    records = config.get("resources")
    if not isinstance(records, list):
        raise PlanRejected(
            "Unknown shared target lacks native configuration references."
        )
    matches = [
        item
        for item in records
        if isinstance(item, dict) and item.get("address") == address
    ]
    if len(matches) != 1:
        raise PlanRejected(
            "Unknown shared target lacks a unique configuration binding."
        )
    return matches[0]


def validate_reference(expression: object, target: str) -> None:
    expression = obj(expression)
    references = expression.get("references")
    allowed = {target, f"{target}.id"}
    if (
        set(expression) != {"references"}
        or not isinstance(references, list)
        or not references
        or any(not isinstance(item, str) or item not in allowed for item in references)
    ):
        raise PlanRejected(
            "Unknown shared target is not bound to the exact owned resource."
        )


def known_or_reference(
    plan: dict, address: str, values: dict, field: str, target: str
) -> None:
    if values.get(field) is not None:
        if not equal(values[field], RESOURCES[target]["id"]):
            raise PlanRejected("Shared resource references an unexpected target.")
        return
    expressions = obj(configuration_record(plan, address).get("expressions"))
    validate_reference(expressions.get(field), target)


def validate_endpoint(
    plan: dict, values: dict, *, existing: bool, allow_partial_destroy: bool = False
) -> None:
    expressions = obj(
        configuration_record(plan, "azurerm_private_endpoint.vault").get("expressions")
    )
    for block, field, target, list_value in (
        (
            "private_service_connection",
            "private_connection_resource_id",
            "azurerm_key_vault.shared",
            False,
        ),
        (
            "private_dns_zone_group",
            "private_dns_zone_ids",
            "azurerm_private_dns_zone.vault",
            True,
        ),
    ):
        blocks = values.get(block)
        if (
            block == "private_dns_zone_group"
            and blocks == []
            and existing
            and allow_partial_destroy
        ):
            continue
        if not isinstance(blocks, list) or len(blocks) != 1:
            raise PlanRejected(
                "The vault endpoint must have exactly its owned service/DNS group."
            )
        value = obj(blocks[0])
        selected = value.get(field)
        expected = RESOURCES[target]["id"]
        if list_value:
            known = (
                isinstance(selected, list)
                and len(selected) == 1
                and equal(selected[0], expected)
            )
            unknown = selected is None or selected == [None]
            if value.get("name") != "vault-zone-group":
                raise PlanRejected("Unexpected vault private DNS group.")
        else:
            known = equal(selected, expected)
            unknown = selected is None
            if (
                value.get("name") != f"{setting('resource_prefix')}-vault-psc"
                or value.get("is_manual_connection") is not False
                or value.get("subresource_names") != ["vault"]
            ):
                raise PlanRejected("Unexpected vault private service connection.")
        if not known:
            if existing or not unknown:
                raise PlanRejected(
                    "Vault endpoint references a foreign or unknown vault/DNS zone."
                )
            configurations = expressions.get(block)
            if not isinstance(configurations, list) or len(configurations) != 1:
                raise PlanRejected("Missing native vault endpoint block binding.")
            validate_reference(obj(configurations[0]).get(field), target)


def validate_values(
    plan: dict,
    address: str,
    values: object,
    *,
    existing: bool,
    allow_partial_destroy: bool = False,
) -> None:
    values = obj(values)
    if address in RESOURCES:
        expected = RESOURCES[address]
        for key, value in expected.items():
            if key == "id" and not existing and values.get(key) is None:
                continue
            if (
                key in ("workspace_id", "virtual_network_id", "subnet_id")
                and values.get(key) is None
                and not existing
            ):
                target = next(
                    name for name, item in RESOURCES.items() if item["id"] == value
                )
                known_or_reference(plan, address, values, key, target)
            elif not equal(values.get(key), value):
                raise PlanRejected(
                    "Shared resource name, ID, tags or fixed security fields differ."
                )
        if not equal(values.get("resource_group_name"), GROUP):
            raise PlanRejected("Shared resource lacks its exact retained group.")
        if "location" in values and not equal(values["location"], REGION):
            raise PlanRejected("Shared resource region differs.")
        if address == "azurerm_private_endpoint.vault":
            validate_endpoint(
                plan,
                values,
                existing=existing,
                allow_partial_destroy=allow_partial_destroy,
            )
    elif address in ASSOCIATIONS:
        bindings = ASSOCIATIONS[address]
        for field, target in bindings.items():
            if existing and values.get(field) is None:
                raise PlanRejected("Existing association has an unknown target.")
            known_or_reference(plan, address, values, field, target)
        if existing:
            if "subnet_id" in bindings:
                allowed_ids = {RESOURCES[bindings["subnet_id"]]["id"]}
            else:
                gateway = RESOURCES[bindings["nat_gateway_id"]]["id"]
                public_ip = RESOURCES[bindings["public_ip_address_id"]]["id"]
                allowed_ids = {
                    f"{gateway}|{public_ip}",
                    f"{gateway}/publicIPAddresses/{setting('resource_prefix')}-shared-nat-pip",
                }
            if not any(equal(values.get("id"), value) for value in allowed_ids):
                raise PlanRejected(
                    "Existing association ID is outside the exact owned pair."
                )
    else:
        raise PlanRejected("Unexpected managed shared-stack address.")


def module_records(module: object) -> list:
    module = obj(module)
    if module.get("child_modules", []) != []:
        raise PlanRejected("The fixed shared stack has no child modules.")
    resources = module.get("resources", [])
    if not isinstance(resources, list):
        raise PlanRejected("Malformed shared resource records.")
    return resources


def validate_data(record: dict) -> None:
    address = record.get("address")
    values = obj(record.get("values"))
    if address == "data.azurerm_resource_group.shared[0]":
        if (
            not equal(values.get("id"), ROOT)
            or not equal(values.get("name"), GROUP)
            or not equal(values.get("tags"), FALLBACK_TARGET.group_tags)
        ):
            raise PlanRejected("Shared group metadata differs from the fixed campaign.")
    elif address == "data.azurerm_client_config.current":
        if not equal(
            values.get("subscription_id"), FALLBACK_TARGET.subscription
        ) or not equal(values.get("tenant_id"), FALLBACK_TARGET.tenant):
            raise PlanRejected("Shared provider context differs from the fixed target.")
    else:
        raise PlanRejected("Unexpected shared-stack data source.")


def validate_provider_bindings(plan: dict) -> None:
    config = obj(plan.get("configuration"))
    providers = obj(config.get("provider_config"))
    if set(providers) != {"azurerm"}:
        raise PlanRejected("Only the fixed default AzureRM provider is supported.")
    provider = obj(providers["azurerm"])
    if provider.get("full_name") != "registry.terraform.io/hashicorp/azurerm":
        raise PlanRejected("Unexpected shared provider source.")
    subscription = obj(obj(provider.get("expressions")).get("subscription_id"))
    if subscription != {"references": ["var.subscription_id"]}:
        raise PlanRejected(
            "Shared provider must use the exact fixed subscription variable."
        )
    module = obj(config.get("root_module"))
    if module.get("module_calls", {}) != {}:
        raise PlanRejected("Shared configuration must not delegate to other modules.")
    resources = module.get("resources")
    if not isinstance(resources, list):
        raise PlanRejected("Missing native shared provider bindings.")
    required = ADDRESSES | {
        "data.azurerm_resource_group.shared",
        "data.azurerm_client_config.current",
    }
    found = set()
    for resource in resources:
        resource = obj(resource)
        if resource.get("provisioners", []) != []:
            raise PlanRejected("Shared scope does not permit provisioner side effects.")
        address = resource.get("address")
        if not isinstance(address, str):
            raise PlanRejected("Missing shared configuration address.")
        if address not in required:
            continue
        if address in found or resource.get("provider_config_key") != "azurerm":
            raise PlanRejected(
                "Shared resources must bind uniquely to the verified provider."
            )
        found.add(address)
    if found != required:
        raise PlanRejected("Missing fixed resource/context provider bindings.")


def validate_fixed_shared(
    plan: object, group: str, *, operation: str, allow_partial_destroy: bool = False
) -> None:
    if group != GROUP or operation not in ("create", "destroy"):
        raise PlanRejected(
            "Only the fixed fallback shared create/destroy scope is supported."
        )
    if allow_partial_destroy and operation != "destroy":
        raise PlanRejected("Partial recovery is only supported for owned destruction.")
    validate_plan(plan, group)
    plan = obj(plan)
    validate_provider_bindings(plan)
    for name, value in {
        "subscription_id": FALLBACK_TARGET.subscription,
        "location": REGION,
        "stage": "release",
        "name_prefix": setting("resource_prefix"),
        "tags": FALLBACK_TARGET.group_tags,
        "key_vault_allowed_ip_ranges": [],
    }.items():
        if not equal(obj(obj(plan.get("variables")).get(name)).get("value"), value):
            raise PlanRejected(
                "Shared plan variables differ from the fixed reviewed campaign."
            )
    prior = []
    if "prior_state" in plan:
        prior = module_records(
            obj(obj(plan["prior_state"]).get("values")).get("root_module")
        )
    planned = module_records(obj(plan.get("planned_values")).get("root_module"))
    for records, existing in ((prior, True), (planned, False)):
        seen = set()
        for record in records:
            record = obj(record)
            address = record.get("address")
            if not isinstance(address, str) or address in seen:
                raise PlanRejected("Duplicate or missing shared resource address.")
            seen.add(address)
            if record.get("mode") == "managed":
                if record.get("type") != address.split(".")[0]:
                    raise PlanRejected("Shared resource address/type differ.")
                if (
                    operation == "create"
                    and existing
                    or operation == "destroy"
                    and not existing
                ):
                    raise PlanRejected(
                        "Create requires fresh state; destroy must leave no managed resources."
                    )
                validate_values(
                    plan,
                    address,
                    record.get("values"),
                    existing=existing,
                    allow_partial_destroy=allow_partial_destroy,
                )
            else:
                validate_data(record)
    context_addresses = {
        record["address"]
        for record in [*prior, *planned]
        if record.get("mode") == "data"
    }
    if context_addresses != {
        "data.azurerm_resource_group.shared[0]",
        "data.azurerm_client_config.current",
    }:
        raise PlanRejected(
            "Both verified existing-group and provider contexts are required."
        )
    changes = plan.get("resource_changes", [] if allow_partial_destroy else None)
    if not isinstance(changes, list):
        raise PlanRejected("Missing native shared resource changes.")
    managed = set()
    for record in changes:
        record = obj(record)
        if record.get("mode") != "managed":
            if record.get("address") not in {
                "data.azurerm_resource_group.shared[0]",
                "data.azurerm_client_config.current",
            }:
                raise PlanRejected("Unexpected shared-stack data change.")
            continue
        address = record.get("address")
        if (
            not isinstance(address, str)
            or address not in ADDRESSES
            or address in managed
            or record.get("type") != address.split(".")[0]
        ):
            raise PlanRejected("Unexpected/duplicate shared resource address or type.")
        managed.add(address)
        change = obj(record.get("change"))
        if change.get("actions") != (
            ["create"] if operation == "create" else ["delete"]
        ):
            raise PlanRejected(
                "Only initial creates or pure owned deletes are supported."
            )
        if change.get("before" if operation == "create" else "after") is not None:
            raise PlanRejected(
                "Shared create/delete carries unexpected prior/future values."
            )
        validate_values(
            plan,
            address,
            change.get("after" if operation == "create" else "before"),
            existing=operation == "destroy",
            allow_partial_destroy=allow_partial_destroy,
        )
    if operation == "create" and managed != ADDRESSES:
        raise PlanRejected(
            "Initial shared plan must create exactly the 29 reviewed resources."
        )
    prior_addresses = {
        item["address"] for item in prior if item.get("mode") == "managed"
    }
    planned_addresses = {
        item["address"] for item in planned if item.get("mode") == "managed"
    }
    if managed != (planned_addresses if operation == "create" else prior_addresses):
        raise PlanRejected(
            "Shared changes do not cover the exact planned/prior managed set."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=("create", "destroy"), required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--private-log", type=Path, required=True)
    parser.add_argument("--terraform-bin", default="terraform")
    args = parser.parse_args()
    try:
        run_saved_plan(
            args.plan,
            GROUP,
            args.private_log,
            terraform=args.terraform_bin,
            apply=False,
            validator=partial(validate_fixed_shared, operation=args.operation),
        )
    except (PlanRejected, OSError) as exc:
        raise SystemExit(f"Fixed shared plan rejected: {exc}") from None
    print(
        "Fixed shared scope passed; no apply, permission, persistence or cleanup proof is implied."
    )


if __name__ == "__main__":
    main()
