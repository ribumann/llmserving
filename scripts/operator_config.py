"""Explicit, immutable target inputs for the bounded operator tools.

This is not Azure authentication or authorization. The independently reviewed
configuration must be supplied separately from the active Azure login.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
NAME = r"[a-z][a-z0-9-]{1,39}"
PATTERNS = {
    "repository": r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
    **{key: UUID for key in (
        "subscription_id", "tenant_id", "deployment_client_id", "sso_client_id",
        "sso_object_id", "dns_resource_guid", "shared_lineage", "operator_lineage",
    )},
    **{key: NAME for key in (
        "resource_prefix", "shared_group", "control_group", "demo_group",
        "canary_group", "primary_canary_group", "infrastructure_group", "target_tag",
        "campaign_tag",
    )},
    **{key: r"[a-z0-9]{3,24}" for key in (
        "state_account", "registry_name",
    )},
    "resource_suffix": r"[a-z0-9]{6}",
    "region": r"[a-z]{3,30}",
    "canary_region": r"[a-z]{3,30}",
    "expires_on": r"20[0-9]{2}-[0-9]{2}-[0-9]{2}",
    "recovery_deadline": r"20[0-9]{2}(?:-[0-9]{2}){2}T[0-9]{2}(?::[0-9]{2}){2}Z",
    "dns_platform_ipconfig": r"/subscriptions/" + UUID + r"/resourceGroups/[A-Za-z0-9._()-]+/providers/Microsoft.Network/loadBalancers/[A-Za-z0-9._-]+/frontendIPConfigurations/[A-Za-z0-9._-]+",
    "storage_topic_name": r"[a-z0-9-]{3,100}",
    "candidate_run": r"[1-9][0-9]*",
    "candidate_attempt": r"[1-9][0-9]*",
    "candidate_sha": r"[0-9a-f]{40}",
    **{key: r"[0-9a-f]{64}" for key in (
        "candidate_manifest_sha256", "shared_state_sha256", "operator_state_sha256",
        "operator_root_sha256",
    )},
    "shared_serial": r"(?:0|[1-9][0-9]*)",
    "operator_serial": r"(?:0|[1-9][0-9]*)",
}


class OperatorConfigurationError(ValueError):
    pass


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise OperatorConfigurationError("Duplicate operator configuration field.")
        result[key] = value
    return result


@lru_cache(maxsize=1)
def _configuration() -> dict[str, str]:
    raw = os.environ.get("LLM_SERVING_OPERATOR_CONFIG")
    if not raw:
        raise OperatorConfigurationError(
            "Missing LLM_SERVING_OPERATOR_CONFIG; supply reviewed target JSON before running operator tools."
        )
    try:
        values = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (ValueError, TypeError):
        raise OperatorConfigurationError("Invalid operator configuration JSON.") from None
    if not isinstance(values, dict) or set(values) - PATTERNS.keys():
        raise OperatorConfigurationError("Unknown operator configuration fields.")
    for key, value in values.items():
        if not isinstance(value, str) or re.fullmatch(PATTERNS[key], value) is None:
            raise OperatorConfigurationError(f"Invalid operator configuration field: {key}.")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for key, value in values.items():
            if key not in {"candidate_attempt", "shared_serial", "operator_serial"}:
                print(f"::add-mask::{value}")
    return values


def setting(key: str) -> str:
    values = _configuration()
    if key not in values:
        raise OperatorConfigurationError(f"Missing operator configuration field: {key}.")
    return values[key]


def terraform_operator_target() -> dict[str, str]:
    return {
        "subscription_id": setting("subscription_id"),
        "resource_group_name": setting("shared_group"),
        **{key: setting(key) for key in (
            "resource_prefix", "state_account", "region", "target_tag",
            "campaign_tag", "expires_on",
        )},
    }
