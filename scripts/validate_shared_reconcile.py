"""One exact shared29 partial-state recovery; never a general retry policy."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import validate_shared_plan as scope
from azure_release_import import ReleaseImportError, command
from validate_retained_group_plan import PlanRejected, run_saved_plan

LINEAGE = "c5fe615f-a6a1-0d7b-eff8-b17acb8252b2"
SERIAL = 29
STATE_SHA256 = "9ac867489cc393609edc99b2296bb6e3f69633c5d7b6befadb9fe4813c8b48b9"
DEADLINE = "2026-11-05T21:55:55Z"
CREATES = {
    "azurerm_public_ip.nat",
    "azurerm_nat_gateway_public_ip_association.shared",
}
EXISTING = scope.ADDRESSES - CREATES


def refreshed_values(address: str, original: dict, refreshed: dict) -> None:
    expected = copy.deepcopy(original)
    if address == "azurerm_nat_gateway.shared":
        if original.get("zones") is None and refreshed.get("zones") == []:
            expected["zones"] = []
    elif address.startswith("azurerm_subnet.") and address in EXISTING:
        for field in ("service_endpoints", "service_endpoint_policy_ids"):
            if original.get(field) is None and refreshed.get(field) == []:
                expected[field] = []
    elif address == "azurerm_private_dns_zone.vault":
        if (
            original.get("number_of_record_sets") == 1
            and refreshed.get("number_of_record_sets") == 2
        ):
            expected["number_of_record_sets"] = 2
    elif address == "azurerm_virtual_network.shared" and original.get("subnet") == []:
        prefixes = {
            "containerapps": "10.20.1.0/24",
            "gpu": "10.20.10.0/24",
            "private_endpoints": "10.20.2.0/24",
            "functions": "10.20.3.0/24",
            "data": "10.20.4.0/26",
        }
        entries = [
            {
                "name": scope.RESOURCES[f"azurerm_subnet.{label}"]["name"],
                "id": scope.RESOURCES[f"azurerm_subnet.{label}"]["id"],
                "address_prefix": prefix,
                "security_group": (
                    scope.RESOURCES["azurerm_network_security_group.gpu"]["id"]
                    if label == "gpu"
                    else ""
                ),
            }
            for label, prefix in prefixes.items()
        ]
        actual = refreshed.get("subnet")
        if (
            isinstance(actual, list)
            and len(actual) == 5
            and all(isinstance(item, dict) for item in actual)
            and sorted(actual, key=lambda item: item.get("name", ""))
            == sorted(entries, key=lambda item: item["name"])
        ):
            expected["subnet"] = copy.deepcopy(actual)
    if expected != refreshed:
        raise PlanRejected(
            "Recovery refresh exceeds the exact reviewed normalizations."
        )


def validate_refresh(plan: dict, prior: dict, current: dict) -> None:
    drift = plan.get("resource_drift", [])
    if not isinstance(drift, list):
        raise PlanRejected("Malformed recovery refresh changes.")
    changed = {
        address
        for address in EXISTING
        if prior[address].get("values") != current[address].get("values")
    }
    seen = set()
    for record in drift:
        record = scope.obj(record)
        address = record.get("address")
        if (
            address not in changed
            or address in seen
            or record.get("mode") != "managed"
            or record.get("type") != address.split(".")[0]
        ):
            raise PlanRejected("Unexpected/duplicate recovery refresh address.")
        seen.add(address)
        change = scope.obj(record.get("change"))
        if (
            change.get("actions") != ["update"]
            or change.get("before") != current[address]["values"]
            or change.get("after") != prior[address]["values"]
            or change.get("after_unknown") not in ({}, False)
        ):
            raise PlanRejected(
                "Recovery refresh does not match canonical/native prior values."
            )
        refreshed_values(address, current[address]["values"], prior[address]["values"])
    if seen != changed:
        raise PlanRejected(
            "Recovery refresh must account for every canonical normalization."
        )
    for address in EXISTING:
        normalized = {**current[address], "values": prior[address]["values"]}
        sensitivity = copy.deepcopy(current[address].get("sensitive_values", {}))
        refreshed = prior[address].get("sensitive_values", {})
        if not isinstance(sensitivity, dict) or not isinstance(refreshed, dict):
            raise PlanRejected("Recovery sensitivity metadata is malformed.")
        fields = (
            ("zones",)
            if address == "azurerm_nat_gateway.shared"
            else (
                ("service_endpoints", "service_endpoint_policy_ids")
                if address.startswith("azurerm_subnet.")
                else ()
            )
        )
        for field in fields:
            if (
                field not in sensitivity
                and refreshed.get(field) == []
                and current[address]["values"].get(field) is None
                and prior[address]["values"].get(field) == []
            ):
                sensitivity[field] = []
        if (
            address == "azurerm_virtual_network.shared"
            and sensitivity.get("subnet") == []
            and refreshed.get("subnet") == [{}, {}, {}, {}, {}]
            and current[address]["values"].get("subnet") == []
            and len(prior[address]["values"].get("subnet", [])) == 5
        ):
            sensitivity["subnet"] = [{}, {}, {}, {}, {}]
        if sensitivity != refreshed:
            raise PlanRejected(
                "Recovery sensitivity metadata changed beyond exact empty shapes."
            )
        if (
            "sensitive_values" in current[address]
            or "sensitive_values" in prior[address]
        ):
            normalized["sensitive_values"] = sensitivity
        if normalized != prior[address]:
            raise PlanRejected("Recovery canonical resource metadata changed.")


def managed(module: object) -> dict:
    result = {}
    for record in scope.module_records(module):
        record = scope.obj(record)
        if record.get("mode") != "managed":
            continue
        address = record.get("address")
        if not isinstance(address, str) or address in result:
            raise PlanRejected("Recovery state has missing/duplicate addresses.")
        result[address] = record
    return result


def validate_reconcile(plan: object, group: str, canonical: object) -> None:
    plan = scope.obj(plan)
    prior_module = scope.obj(
        scope.obj(scope.obj(plan.get("prior_state")).get("values")).get("root_module")
    )
    prior = managed(prior_module)
    canonical = scope.obj(canonical)
    current = managed(scope.obj(canonical.get("values")).get("root_module"))
    if set(prior) != EXISTING or set(current) != EXISTING:
        raise PlanRejected("Recovery prior resources differ from exact canonical 27.")
    validate_refresh(plan, prior, current)
    future = managed(scope.obj(plan.get("planned_values")).get("root_module"))
    if set(future) != scope.ADDRESSES:
        raise PlanRejected("Recovery must leave exactly the reviewed 29 resources.")
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise PlanRejected("Recovery lacks native changes.")
    seen = set()
    for record in changes:
        record = scope.obj(record)
        if record.get("mode") != "managed":
            continue
        address = record.get("address")
        if address not in scope.ADDRESSES or address in seen:
            raise PlanRejected("Unexpected/duplicate recovery change.")
        seen.add(address)
        change = scope.obj(record.get("change"))
        if address in CREATES:
            if change.get("actions") != ["create"] or change.get("before") is not None:
                raise PlanRejected(
                    "Only missing PIP and NAT association may be created."
                )
        elif (
            change.get("actions") != ["no-op"]
            or change.get("before") != change.get("after")
            or change.get("before") != prior[address].get("values")
            or change.get("after_unknown") not in ({}, False)
        ):
            raise PlanRejected("Existing 27 resources must remain exact known NOOPs.")
        if change.get("after") != future[address].get("values"):
            raise PlanRejected("Recovery change differs from native planned values.")
    if seen != scope.ADDRESSES:
        raise PlanRejected("Recovery must account for all 29 managed changes.")

    # Reuse both unchanged strict guards to validate every native value/reference.
    initial = copy.deepcopy(plan)
    initial.pop("prior_state")
    # Refreshed plans can keep a verified data context only in prior_state.
    # Preserve it in the validation projection instead of losing that evidence.
    projected = initial["planned_values"]["root_module"]["resources"]
    projected_addresses = {record.get("address") for record in projected}
    for record in prior_module["resources"]:
        if record.get("mode") == "data":
            scope.validate_data(record)
            if record["address"] not in projected_addresses:
                projected.append(copy.deepcopy(record))
                projected_addresses.add(record["address"])
    for record in initial["resource_changes"]:
        if record.get("mode") == "managed":
            record["change"]["actions"] = ["create"]
            record["change"]["before"] = None
    scope.validate_fixed_shared(initial, group, operation="create")

    owned = copy.deepcopy(plan)
    owned["planned_values"]["root_module"]["resources"] = [
        item for item in prior_module["resources"] if item.get("mode") != "managed"
    ]
    owned["resource_changes"] = [
        {
            **{key: value for key, value in item.items() if key != "values"},
            "change": {
                "actions": ["delete"],
                "before": item["values"],
                "after": None,
                "after_unknown": {},
            },
        }
        for item in prior.values()
    ]
    scope.validate_fixed_shared(owned, group, operation="destroy")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--private-log", type=Path, required=True)
    args = parser.parse_args()
    # Import here to reuse the strict ACL/snapshot checks without an import cycle.
    import azure_shared_bridge as bridge

    try:
        bridge.private_directory(Path.cwd())
        raw = Path("terraform.tfstate").read_bytes()
        state = json.loads(raw)
        bridge.recovery_state(
            {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "lineage": state.get("lineage"),
                "serial": state.get("serial"),
            }
        )
        version = command(["terraform", "version", "-json"])
        if (
            not isinstance(version, dict)
            or version.get("terraform_version") != "1.16.6"
        ):
            raise PlanRejected("Recovery check requires Terraform 1.16.6.")
        canonical = command(["terraform", "show", "-json", "terraform.tfstate"])
        run_saved_plan(
            args.plan,
            scope.GROUP,
            args.private_log,
            terraform="terraform",
            apply=False,
            validator=lambda plan, group: validate_reconcile(plan, group, canonical),
        )
    except (
        PlanRejected,
        OSError,
        ValueError,
        bridge.shared.SharedError,
        ReleaseImportError,
    ) as error:
        raise SystemExit(
            f"Recovery check stopped: {type(error).__name__}; inspect private evidence."
        ) from None
    print("Exact shared partial recovery native scope check passed; no apply.")


if __name__ == "__main__":
    main()
