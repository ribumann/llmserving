"""Exact operator serial8 recovery: one missing AZ gateway, six unchanged resources."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import validate_operator_access_plan as scope
from azure_release_import import ReleaseImportError, command
from validate_retained_group_plan import PlanRejected, run_saved_plan

LINEAGE = "5a630028-d04a-3e1c-af96-bbd58b8434fe"
SERIAL = 8
STATE_SHA256 = "4496a600b605459310e5df169868204ec02894d661214b70ca421c2434054f76"
DEADLINE = "2026-11-05T21:55:55Z"
ROOT_SHA256 = "945b63536aebe7639cd0f879071182c15be158dba2d96bacd71eefc32a505bba"
GATEWAY = "azurerm_virtual_network_gateway.operator"
EXISTING = set(scope.RESOURCES) - {GATEWAY}


def snapshot(metadata: object) -> None:
    if metadata != {"sha256": STATE_SHA256, "lineage": LINEAGE, "serial": SERIAL}:
        raise PlanRejected("Recovery requires the exact preserved operator serial8.")
    path = Path("terraform.tfstate")
    if (
        path.is_symlink()
        or hashlib.sha256(path.read_bytes()).hexdigest() != STATE_SHA256
    ):
        raise PlanRejected("Canonical operator recovery state changed; no retry.")


def canonical_state() -> object:
    from azure_operator_apply import local_context

    local_context(Path.cwd())
    raw = Path("terraform.tfstate").read_bytes()
    state = json.loads(raw)
    snapshot(
        {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "lineage": state.get("lineage"),
            "serial": state.get("serial"),
        }
    )
    return command(["terraform", "show", "-json", "terraform.tfstate"])


def managed(module: object) -> dict:
    records = {}
    for record in scope.shared.module_records(module):
        record = scope.shared.obj(record)
        if record.get("mode") != "managed":
            continue
        address = record.get("address")
        if address not in scope.RESOURCES or address in records:
            raise PlanRejected("Unexpected/duplicate operator recovery address.")
        records[address] = record
    return records


def validate_reconcile(
    plan: object, group: str, canonical: object, target: dict
) -> None:
    if (
        target.get("expires_at") != DEADLINE
        or target.get("root_certificate_sha256") != ROOT_SHA256
    ):
        raise PlanRejected("Recovery cannot change the approved root or deadline.")
    plan = scope.shared.obj(plan)
    canonical = scope.shared.obj(canonical)
    prior_module = scope.shared.obj(
        scope.shared.obj(scope.shared.obj(plan.get("prior_state")).get("values")).get(
            "root_module"
        )
    )
    prior = managed(prior_module)
    current = managed(scope.shared.obj(canonical.get("values")).get("root_module"))
    if (
        set(prior) != EXISTING
        or prior != current
        or plan.get("resource_drift", []) != []
    ):
        raise PlanRejected(
            "Recovery prior must equal the exact canonical six; no drift."
        )
    future = managed(scope.shared.obj(plan.get("planned_values")).get("root_module"))
    if set(future) != set(scope.RESOURCES):
        raise PlanRejected("Recovery must leave exactly the seven reviewed resources.")
    seen = set()
    for record in plan.get("resource_changes", []):
        record = scope.shared.obj(record)
        if record.get("mode") == "data":
            continue
        address = record.get("address")
        change = scope.shared.obj(record.get("change"))
        if (
            address not in scope.RESOURCES
            or address in seen
            or record.get("mode") != "managed"
            or record.get("type") != address.split(".")[0]
        ):
            raise PlanRejected("Unexpected/duplicate recovery change.")
        seen.add(address)
        if address == GATEWAY:
            if change.get("actions") != ["create"] or change.get("before") is not None:
                raise PlanRejected("Only the missing AZ gateway may be created.")
        elif (
            change.get("actions") != ["no-op"]
            or change.get("before") != prior[address].get("values")
            or change.get("after") != change.get("before")
            or change.get("after_unknown") not in ({}, False)
        ):
            raise PlanRejected("Existing operator six must remain exact known NOOPs.")
        if change.get("after") != future[address].get("values"):
            raise PlanRejected("Recovery changes differ from native planned values.")
    if seen != set(scope.RESOURCES):
        raise PlanRejected("Recovery must account for all seven managed changes.")

    initial = copy.deepcopy(plan)
    initial.pop("prior_state")
    for record in initial["resource_changes"]:
        if record.get("mode") == "managed":
            record["change"]["actions"] = ["create"]
            record["change"]["before"] = None
    # Keep actual prior-only data evidence in the strict validation projection.
    projected = initial["planned_values"]["root_module"]["resources"]
    addresses = {record.get("address") for record in projected}
    for record in prior_module.get("resources", []):
        if record.get("mode") == "data" and record.get("address") not in addresses:
            projected.append(copy.deepcopy(record))
            addresses.add(record.get("address"))
    scope.validate(initial, group, operation="create", target=target)
    owned = copy.deepcopy(plan)
    owned["planned_values"]["root_module"]["resources"] = []
    owned["resource_changes"] = [
        {
            **{key: value for key, value in record.items() if key != "values"},
            "change": {
                "actions": ["delete"],
                "before": record["values"],
                "after": None,
                "after_unknown": {},
            },
        }
        for record in prior.values()
    ]
    scope.validate(owned, group, operation="destroy", target=target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--private-log", type=Path, required=True)
    args = parser.parse_args()
    import azure_shared_bridge as bridge

    try:
        target = json.loads(args.target.read_text())
        canonical = canonical_state()
        run_saved_plan(
            args.plan,
            scope.shared.GROUP,
            args.private_log,
            terraform="terraform",
            apply=False,
            require_canonical_local=True,
            validator=lambda plan, group: validate_reconcile(
                plan, group, canonical, target
            ),
        )
    except (
        PlanRejected,
        OSError,
        ValueError,
        KeyError,
        ReleaseImportError,
        bridge.shared.SharedError,
    ) as error:
        raise SystemExit(
            f"Operator recovery check stopped: {type(error).__name__}; inspect private evidence."
        ) from None
    print("Exact operator serial8 recovery native scope check passed; no apply.")


if __name__ == "__main__":
    main()
