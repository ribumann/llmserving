"""Fail-closed initial-bootstrap gate for a reviewed native Terraform saved plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


class PlanRejected(ValueError):
    pass


PROVIDER = "registry.terraform.io/azure/azapi"
TYPES = {
    "azapi_resource.state": "Microsoft.Storage/storageAccounts@2023-05-01",
    "azapi_resource.blobs": "Microsoft.Storage/storageAccounts/blobServices@2023-05-01",
    "azapi_resource.tfstate": "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01",
}
DATA = {
    "data.azapi_resource.shared": "azapi_resource",
    "data.azapi_client_config.current": "azapi_client_config",
}
ACCOUNT_BODY = {
    "kind": "StorageV2",
    "sku": {"name": "Standard_LRS"},
    "properties": {
        "supportsHttpsTrafficOnly": True,
        "minimumTlsVersion": "TLS1_2",
        "allowSharedKeyAccess": False,
        "allowBlobPublicAccess": False,
        "allowCrossTenantReplication": False,
        "defaultToOAuthAuthentication": True,
        "publicNetworkAccess": "Enabled",
        "networkAcls": {"bypass": "None", "defaultAction": "Allow"},
        "encryption": {
            "keySource": "Microsoft.Storage",
            "services": {"blob": {"enabled": True, "keyType": "Account"}},
        },
    },
}
BODIES = {
    "azapi_resource.state": ACCOUNT_BODY,
    "azapi_resource.blobs": {
        "properties": {
            "isVersioningEnabled": True,
            "deleteRetentionPolicy": {"enabled": True, "days": 7},
            "containerDeleteRetentionPolicy": {"enabled": True, "days": 7},
        }
    },
    "azapi_resource.tfstate": {"properties": {"publicAccess": "None"}},
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanRejected(message)


def _object(value: object) -> dict:
    _require(type(value) is dict, "Malformed object in bootstrap plan.")
    return value


def _list(value: object) -> list:
    _require(type(value) is list, "Malformed list in bootstrap plan.")
    return value


def _equal(actual: object, expected: object) -> bool:
    # Python otherwise considers True == 1, including inside dictionaries.
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(
            _equal(actual[key], value) for key, value in expected.items()
        )
    if type(expected) is list:
        return len(actual) == len(expected) and all(
            _equal(a, b) for a, b in zip(actual, expected)
        )
    return actual == expected


def _unknown(value: object) -> bool:
    if type(value) is bool:
        return value
    if type(value) is dict:
        return any([_unknown(item) for item in value.values()])
    if type(value) is list:
        return any([_unknown(item) for item in value])
    raise PlanRejected("Malformed unknown-value metadata.")


def _records(module: object) -> dict:
    module = _object(module)
    _require(
        _list(module.get("child_modules", [])) == [],
        "Child modules are not bootstrap scope.",
    )
    _require(
        _object(module.get("module_calls", {})) == {},
        "Module calls are not bootstrap scope.",
    )
    result = {}
    for item in _list(module.get("resources", [])):
        item = _object(item)
        address = item.get("address")
        _require(
            type(address) is str and address not in result, "Invalid resource address."
        )
        if address in TYPES:
            mode, kind = "managed", "azapi_resource"
        else:
            _require(address in DATA, "Resource outside the bootstrap allowlist.")
            mode, kind = "data", DATA[address]
        _require(
            item.get("mode") == mode and item.get("type") == kind,
            "Resource mode/type does not match the bootstrap allowlist.",
        )
        _require("index" not in item, "Indexed resources are not initial bootstrap.")
        result[address] = item
    return result


def _references(expression: object, target: str) -> None:
    expression = _object(expression)
    _require(
        set(expression) == {"references"}, "Parent must use the reviewed reference."
    )
    references = _list(expression["references"])
    _require(
        all(type(ref) is str for ref in references), "Malformed parent references."
    )
    _require(
        len(references) == 2 and set(references) == {target, target.rsplit(".", 1)[0]},
        "Foreign or ambiguous parent dependency.",
    )


def validate_plan(plan: object, expected: dict) -> None:
    """Validate reviewed bootstrap source only, not arbitrary Terraform expressions."""
    expected = _object(expected)
    required = {
        "subscription_id",
        "tenant_id",
        "existing_resource_group_name",
        "location",
        "name_prefix",
        "stage",
        "tags",
    }
    _require(
        set(expected) == required, "All explicit bootstrap target inputs are required."
    )
    for name in ("subscription_id", "tenant_id"):
        _require(
            type(expected[name]) is str
            and re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                expected[name],
            )
            is not None,
            "Expected subscription/tenant must be UUIDs.",
        )
    for name, pattern in (
        ("existing_resource_group_name", r"[A-Za-z0-9._()-]{1,90}"),
        ("location", r"[a-z][a-z0-9]+"),
        ("name_prefix", r"[a-z0-9]{1,13}"),
        ("stage", r"[a-z0-9]{2,12}"),
    ):
        _require(
            type(expected[name]) is str
            and re.fullmatch(pattern, expected[name]) is not None,
            "Invalid explicit bootstrap target input.",
        )
    _require(
        not expected["existing_resource_group_name"].endswith("."),
        "Invalid group name.",
    )
    tags = _object(expected["tags"])
    _require(
        all(type(k) is str and type(v) is str for k, v in tags.items()),
        "Tags must be strings.",
    )
    group_id = (
        f"/subscriptions/{expected['subscription_id']}/resourceGroups/"
        f"{expected['existing_resource_group_name']}"
    )
    suffix = hashlib.md5(
        f"{expected['subscription_id']}-{expected['stage']}".encode(),
        usedforsecurity=False,
    ).hexdigest()[:6]
    account = f"{expected['name_prefix']}state{suffix}"
    account_id = f"{group_id}/providers/Microsoft.Storage/storageAccounts/{account}"
    parents = {
        "azapi_resource.state": group_id,
        "azapi_resource.blobs": account_id,
        "azapi_resource.tfstate": f"{account_id}/blobServices/default",
    }
    references = {
        "azapi_resource.state": "data.azapi_resource.shared.id",
        "azapi_resource.blobs": "azapi_resource.state.id",
        "azapi_resource.tfstate": "azapi_resource.blobs.id",
    }
    names = {
        "azapi_resource.state": account,
        "azapi_resource.blobs": "default",
        "azapi_resource.tfstate": "tfstate",
    }
    plan = _object(plan)
    _require(
        plan.get("format_version") in ("1.0", "1.1", "1.2"),
        "Unsupported native plan format.",
    )
    _require(
        plan.get("errored", False) is False
        and plan.get("complete", True) is True
        and plan.get("applyable", True) is True,
        "Incomplete, errored or non-applyable bootstrap plan.",
    )
    for key in ("deferred_changes", "resource_drift", "action_invocations"):
        _require(
            plan.get(key, []) == [],
            "Deferred, drift or action changes are not initial bootstrap.",
        )
    variables = _object(plan.get("variables"))
    _require(
        set(variables) == required - {"tenant_id"}, "Unexpected bootstrap variables."
    )
    for name in variables:
        _require(
            _equal(_object(variables[name]).get("value"), expected[name]),
            "Plan variables differ from the explicit approved target.",
        )

    configuration = _object(plan.get("configuration"))
    providers = _object(configuration.get("provider_config"))
    _require(
        set(providers) == {"azapi"}, "Only the reviewed AzAPI provider is allowed."
    )
    provider = _object(providers["azapi"])
    constraint = provider.get("version_constraint")
    _require(type(constraint) is str, "Malformed provider version constraint.")
    _require(
        provider.get("full_name") == PROVIDER
        and re.sub(r"\s+", "", constraint) in ("=2.4.0", "2.4.0"),
        "Provider source/version must match reviewed bootstrap.",
    )
    expressions = _object(provider.get("expressions"))
    _require(
        set(expressions)
        == {
            "subscription_id",
            "skip_provider_registration",
            "enable_preflight",
            "disable_default_output",
        },
        "Unexpected provider configuration or endpoint overrides.",
    )
    _require(
        expressions["subscription_id"] == {"references": ["var.subscription_id"]},
        "Provider subscription is not bound.",
    )
    for name, value in (
        ("skip_provider_registration", True),
        ("enable_preflight", False),
        ("disable_default_output", True),
    ):
        _require(
            _equal(expressions[name], {"constant_value": value}),
            "Unsafe provider settings.",
        )
    config = _records(configuration.get("root_module"))
    _require(
        set(config) == set(TYPES) | set(DATA),
        "Configuration must contain exactly the reviewed five records.",
    )
    for address, item in config.items():
        _require(
            item.get("provider_config_key") == "azapi", "Unexpected resource provider."
        )
        _require(
            not any(
                key in item
                for key in (
                    "provisioners",
                    "connection",
                    "count_expression",
                    "for_each_expression",
                )
            ),
            "Provisioners and indexed resources are not bootstrap scope.",
        )
        if address in TYPES:
            expr = _object(item.get("expressions"))
            _require(
                expr.get("type") == {"constant_value": TYPES[address]},
                "Unexpected configured ARM type.",
            )
            _references(expr.get("parent_id"), references[address])
        elif address == "data.azapi_client_config.current":
            _require(
                _object(item.get("expressions", {})) == {},
                "Client configuration data must have no input overrides.",
            )
        else:
            _object(item.get("expressions"))

    prior = plan.get("prior_state")
    resolved_data = {}
    if prior is not None:
        records = _records(_object(_object(prior).get("values")).get("root_module"))
        _require(
            not (set(records) & set(TYPES)),
            "Prior managed state is not fresh bootstrap.",
        )
        resolved_data.update(records)
    planned = _records(_object(plan.get("planned_values")).get("root_module"))
    _require(
        set(TYPES) <= set(planned),
        "Planned records differ from reviewed bootstrap.",
    )
    for address in set(planned) & set(DATA):
        if address in resolved_data:
            _require(
                _equal(
                    resolved_data[address].get("values"), planned[address].get("values")
                ),
                "Conflicting resolved data records.",
            )
        resolved_data[address] = planned[address]
    _require(
        set(resolved_data) == set(DATA), "Both approved data lookups must be resolved."
    )
    current = _object(resolved_data["data.azapi_client_config.current"].get("values"))
    _require(
        current.get("tenant_id") == expected["tenant_id"]
        and current.get("subscription_id") == expected["subscription_id"],
        "Authenticated tenant/subscription differs from approved target.",
    )
    group = _object(resolved_data["data.azapi_resource.shared"].get("values"))
    _require(
        group.get("id") == group_id
        and group.get("name") == expected["existing_resource_group_name"]
        and group.get("type") == "Microsoft.Resources/resourceGroups@2024-03-01",
        "Group lookup does not bind the exact approved existing group.",
    )

    changes = _records({"resources": plan.get("resource_changes")})
    _require(
        set(TYPES) <= set(changes), "All three initial managed creates are required."
    )
    for address, item in changes.items():
        _require(item.get("provider_name") == PROVIDER, "Unexpected change provider.")
        _require(
            "previous_address" not in item and "deposed" not in item,
            "Moved/deposed state is not fresh bootstrap.",
        )
        change = _object(item.get("change"))
        _require(
            "importing" not in change and "generated_config" not in item,
            "Imports are not initial bootstrap.",
        )
        if address in DATA:
            _require(
                change.get("actions") == ["no-op"],
                "Data lookups must be resolved before approval.",
            )
            _require(
                _equal(change.get("after"), resolved_data[address].get("values")),
                "Inconsistent data lookup.",
            )
            _require(not _unknown(change.get("after_unknown")), "Unknown data lookup.")
            continue
        _require(
            change.get("actions") == ["create"]
            and change.get("before", "missing") is None,
            "Only fresh creates are allowed.",
        )
        after = _object(change.get("after"))
        unknown = _object(change.get("after_unknown"))
        _unknown(unknown)
        allowed_fields = {
            "body",
            "name",
            "type",
            "parent_id",
            "location",
            "tags",
            "id",
            "output",
            "response_export_values",
            "sensitive_body",
            "identity",
            "create_headers",
            "update_headers",
            "delete_headers",
            "read_headers",
            "create_query_parameters",
            "update_query_parameters",
            "delete_query_parameters",
            "read_query_parameters",
            "locks",
            "retry",
            "timeouts",
            "ignore_casing",
            "ignore_missing_property",
            "schema_validation_enabled",
            "replace_triggers_external_values",
            "replace_triggers_refs",
        }
        _require(
            set(after) <= allowed_fields and set(unknown) <= allowed_fields,
            "Unexpected AzAPI attributes.",
        )
        for field in ("body", "name", "type", "response_export_values"):
            _require(
                not _unknown(unknown.get(field, False)),
                "Unknown critical bootstrap security value.",
            )
        _require(
            _equal(after.get("body"), BODIES[address]),
            "Unexpected storage security/recovery body.",
        )
        _require(
            after.get("type") == TYPES[address] and after.get("name") == names[address],
            "Unexpected ARM type or name.",
        )
        _require(
            after.get("response_export_values") == [],
            "Management response exports are forbidden.",
        )
        for field in (
            "sensitive_body",
            "identity",
            "create_headers",
            "update_headers",
            "delete_headers",
            "read_headers",
            "create_query_parameters",
            "update_query_parameters",
            "delete_query_parameters",
            "read_query_parameters",
        ):
            empty = [] if field == "identity" else None
            _require(
                _equal(after.get(field), empty),
                "Unexpected identity, hidden body or request override.",
            )
            _require(
                not _unknown(unknown.get(field, False)), "Unknown request override."
            )
        if address == "azapi_resource.state":
            _require(
                after.get("location") == expected["location"]
                and _equal(after.get("tags"), tags),
                "Account location/tags differ from approval.",
            )
            _require(
                not _unknown(unknown.get("location", False))
                and not _unknown(unknown.get("tags", False)),
                "Unknown account location/tags.",
            )
        parent_unknown = unknown.get("parent_id", False)
        if parent_unknown is True:
            _require(
                address != "azapi_resource.state" and after.get("parent_id") is None,
                "Only child parents may depend on computed new IDs.",
            )
            # References alone are not expression semantics: reviewed source is a prerequisite.
            _references(
                _object(config[address]["expressions"]).get("parent_id"),
                references[address],
            )
        else:
            _require(
                parent_unknown is False and after.get("parent_id") == parents[address],
                "Foreign or malformed ARM parent.",
            )
        values = _object(planned[address].get("values"))
        for field in (
            "body",
            "type",
            "name",
            "parent_id",
            "location",
            "tags",
            "response_export_values",
        ):
            _require(
                _equal(values.get(field), after.get(field)),
                "Planned values and change payload disagree.",
            )


def _json(text: str) -> object:
    def pairs(items: list) -> dict:
        result = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON fields are forbidden.")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise PlanRejected("Nonfinite JSON values are forbidden.")

    try:
        return json.loads(
            text, object_pairs_hook=pairs, parse_constant=invalid_constant
        )
    except (ValueError, RecursionError) as error:
        raise PlanRejected("Malformed native plan or expected-target JSON.") from error


def run_saved_plan(
    plan_path: Path, expected: dict, log_path: Path, *, terraform: str, apply: bool
) -> None:
    with tempfile.TemporaryDirectory(prefix="bootstrap-plan-") as directory:
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
            _require(
                shown.returncode == 0, "Terraform show failed; inspect the private log."
            )
            validate_plan(_json(shown.stdout), expected)
            if apply:
                result = subprocess.run(
                    [terraform, "apply", "-input=false", "-no-color", str(saved)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    check=False,
                )
                _require(
                    result.returncode == 0,
                    "Terraform apply failed; inspect the private log.",
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument(
        "--expected-target",
        type=Path,
        required=True,
        help="Private JSON containing all seven explicit target inputs, including tenant_id and tags.",
    )
    parser.add_argument("--private-log", type=Path, required=True)
    parser.add_argument("--terraform-bin", default="terraform")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        run_saved_plan(
            args.plan,
            _object(_json(args.expected_target.read_text())),
            args.private_log,
            terraform=args.terraform_bin,
            apply=args.apply,
        )
    except PlanRejected as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, UnicodeError):
        print(
            "Cannot access private plan/target/log or execute Terraform.",
            file=sys.stderr,
        )
        return 2
    print(
        "Bootstrap initial-plan guard passed; no data-access or migration approval is implied."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
