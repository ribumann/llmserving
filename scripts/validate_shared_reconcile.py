"""One exact shared29 partial-state recovery; never a general retry policy."""

from __future__ import annotations

import copy

import validate_shared_plan as scope
from validate_retained_group_plan import PlanRejected

LINEAGE = "c5fe615f-a6a1-0d7b-eff8-b17acb8252b2"
SERIAL = 29
STATE_SHA256 = "9ac867489cc393609edc99b2296bb6e3f69633c5d7b6befadb9fe4813c8b48b9"
DEADLINE = "2026-11-05T21:55:55Z"
CREATES = {
    "azurerm_public_ip.nat",
    "azurerm_nat_gateway_public_ip_association.shared",
}
EXISTING = scope.ADDRESSES - CREATES


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
    if plan.get("resource_drift", []) != []:
        raise PlanRejected("Recovery must not contain refreshed resource drift.")
    prior_module = scope.obj(
        scope.obj(scope.obj(plan.get("prior_state")).get("values")).get("root_module")
    )
    prior = managed(prior_module)
    canonical = scope.obj(canonical)
    current = managed(scope.obj(canonical.get("values")).get("root_module"))
    if set(prior) != EXISTING or set(current) != EXISTING or prior != current:
        raise PlanRejected("Recovery prior resources differ from exact canonical 27.")
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
