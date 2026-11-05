"""Ownership-only guard for a private, native Terraform retained-group plan."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


class PlanRejected(ValueError):
    pass


def _object(value: object) -> dict:
    if not isinstance(value, dict):
        raise PlanRejected("Malformed Terraform plan structure.")
    return value


def _group_values(values: object, group: str) -> None:
    values = _object(values)
    if "resource_group_name" in values:
        name = values["resource_group_name"]
        if not isinstance(name, str) or name.casefold() != group.casefold():
            raise PlanRejected(
                "Resource group is unknown or outside the retained group."
            )


def _resource(resource: object, group: str) -> dict:
    resource = _object(resource)
    if resource.get("mode") not in ("managed", "data") or not isinstance(
        resource.get("type"), str
    ):
        raise PlanRejected("Malformed Terraform resource record.")
    if resource["mode"] == "managed" and resource["type"] == "azurerm_resource_group":
        raise PlanRejected("Group-owning state or a managed group cannot be retained.")
    return resource


def _module(module: object, group: str) -> None:
    module = _object(module)
    resources = module.get("resources", [])
    children = module.get("child_modules", [])
    if not isinstance(resources, list) or not isinstance(children, list):
        raise PlanRejected("Malformed Terraform module records.")
    for resource in resources:
        resource = _resource(resource, group)
        _group_values(resource.get("values"), group)
    for child in children:
        _module(child, group)


def validate_plan(plan: object, group: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._()-]{1,90}", group) or group.endswith("."):
        raise PlanRejected("A nonblank Azure resource group name is required.")
    plan = _object(plan)
    if not re.fullmatch(r"1\.\d+", str(plan.get("format_version", ""))):
        raise PlanRejected("Unsupported Terraform plan format.")
    if (
        plan.get("errored", False) is not False
        or plan.get("complete", True) is not True
    ):
        raise PlanRejected("Errored or incomplete plans cannot be applied.")
    variables = _object(plan.get("variables"))
    selected = _object(variables.get("existing_resource_group_name")).get("value")
    if not isinstance(selected, str) or selected.casefold() != group.casefold():
        raise PlanRejected("Plan variables do not select the expected retained group.")
    if "prior_state" in plan:
        prior = _object(plan["prior_state"])
        values = _object(prior.get("values"))
        _module(values.get("root_module"), group)
    planned = _object(plan.get("planned_values"))
    _module(planned.get("root_module"), group)
    changes = plan.get("resource_changes", [])
    if not isinstance(changes, list):
        raise PlanRejected("Malformed Terraform resource changes.")
    allowed_actions = (
        ["no-op"],
        ["create"],
        ["read"],
        ["update"],
        ["delete"],
        ["delete", "create"],
        ["create", "delete"],
    )
    for resource in changes:
        resource = _resource(resource, group)
        change = _object(resource.get("change"))
        if change.get("actions") not in allowed_actions:
            raise PlanRejected("Unsupported Terraform resource action.")
        for key in ("before", "after"):
            if key not in change:
                raise PlanRejected("Missing Terraform resource change values.")
            if change[key] is not None:
                _group_values(change[key], group)
        unknown = _object(change.get("after_unknown"))
        if unknown.get("resource_group_name", False) is not False:
            raise PlanRejected("Unknown resource group cannot be approved.")


def run_saved_plan(
    plan_path: Path, group: str, log_path: Path, *, terraform: str, apply: bool
) -> None:
    # A private copy prevents a caller replacing the original after validation.
    with tempfile.TemporaryDirectory(prefix="retained-group-plan-") as directory:
        saved = Path(directory) / "approved.tfplan"
        fd = os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(plan_path.read_bytes())
        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(log_fd, "w") as log:
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("TF_CLI_ARGS", "TF_LOG"))
            }
            shown = subprocess.run(
                [terraform, "show", "-json", str(saved)],
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
                env=env,
                check=False,
            )
            if shown.returncode:
                raise PlanRejected("Terraform show failed; inspect the private log.")
            try:
                plan = json.loads(shown.stdout)
            except json.JSONDecodeError as error:
                raise PlanRejected("Terraform returned malformed plan JSON.") from error
            validate_plan(plan, group)
            if apply:
                result = subprocess.run(
                    [terraform, "apply", "-input=false", "-no-color", str(saved)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    check=False,
                )
                if result.returncode:
                    raise PlanRejected(
                        "Terraform apply failed; inspect the private log."
                    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--private-log", required=True, type=Path)
    parser.add_argument("--terraform-bin", default="terraform")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        run_saved_plan(
            args.plan,
            args.resource_group,
            args.private_log,
            terraform=args.terraform_bin,
            apply=args.apply,
        )
    except PlanRejected as error:
        print(str(error), file=sys.stderr)
        return 2
    except OSError:
        print("Cannot access private plan/log or execute Terraform.", file=sys.stderr)
        return 2
    print(
        "Retained-group ownership guard passed; this is not deployment-scope approval."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
