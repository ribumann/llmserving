"""A fixed, non-compute OIDC canary; never a general-purpose resource cleaner."""

from __future__ import annotations

from operator_config import setting

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass

RESOURCE_GROUP = setting("primary_canary_group")
IDENTITY_NAME = "id-llm-oidc-cleanup-canary"
IDENTITY_TYPE = "Microsoft.ManagedIdentity/userAssignedIdentities"
WORKFLOW_PATH = ".github/workflows/azure-oidc-canary.yml"
GROUP_TAGS = {
    "project": "llmserving-public-validation",
    "managedBy": "copilot-release",
}
PURPOSE = "oidc-cleanup-canary"


@dataclass(frozen=True)
class Target:
    resource_group: str
    workflow_path: str
    cleanup_workflow_path: str | None = None
    subscription: str | None = None
    tenant: str | None = None
    client: str | None = None
    region: str | None = None

    @property
    def group_tags(self) -> dict[str, str]:
        return {
            **GROUP_TAGS,
            **(
                {
                    "target": setting("target_tag"),
                    "expiresOn": setting("expires_on"),
                    "runId": setting("campaign_tag"),
                }
                if self.subscription is not None
                else {}
            ),
        }

    @property
    def identity_tags(self) -> dict[str, str]:
        tags = self.group_tags
        campaign = tags.pop("runId", None)
        if campaign is not None:
            tags["releaseRunId"] = campaign
        return tags


PRIMARY_TARGET = Target(RESOURCE_GROUP, WORKFLOW_PATH)
FALLBACK_TARGET = Target(
    setting("canary_group"),
    ".github/workflows/azure-fallback-oidc-canary.yml",
    ".github/workflows/azure-fallback-canary-cleanup.yml",
    setting("subscription_id"),
    setting("tenant_id"),
    setting("deployment_client_id"),
    setting("canary_region"),
)
TARGETS = {"primary": PRIMARY_TARGET, "fallback": FALLBACK_TARGET}


class CanaryError(RuntimeError):
    pass


def command_json(arguments: list[str]) -> object:
    result = subprocess.run(
        arguments, text=True, capture_output=True, check=False, timeout=120
    )
    if result.returncode:
        raise CanaryError(f"{arguments[0]} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


@dataclass(frozen=True)
class Context:
    subscription: str
    tenant: str
    region: str
    repository: str
    target: Target = PRIMARY_TARGET

    @classmethod
    def from_environment(cls, target_name: str = "primary") -> Context:
        target = TARGETS.get(target_name)
        if target is None:
            raise CanaryError("Unknown canary target.")
        required = (
            "AZURE_SUBSCRIPTION_ID",
            "AZURE_TENANT_ID",
            "AZURE_CANARY_REGION",
            "AZURE_CANARY_RESOURCE_GROUP",
            "GITHUB_REPOSITORY",
        )
        if any(not os.environ.get(key) for key in required):
            raise CanaryError("Missing protected canary configuration.")
        if os.environ["AZURE_CANARY_RESOURCE_GROUP"] != target.resource_group:
            raise CanaryError(
                "Canary resource group is not the fixed authorized group."
            )
        if os.environ.get("GITHUB_REF") != "refs/heads/main":
            raise CanaryError("Only protected main may operate this canary.")
        if os.environ["GITHUB_REPOSITORY"] != setting("repository"):
            raise CanaryError("Unexpected canary repository.")
        expected_identity = {
            "AZURE_SUBSCRIPTION_ID": setting("subscription_id"),
            "AZURE_TENANT_ID": setting("tenant_id"),
            "AZURE_CLIENT_ID": setting("deployment_client_id"),
            "AZURE_CANARY_REGION": setting("canary_region"),
        }
        if any(os.environ.get(key) != value for key, value in expected_identity.items()):
            raise CanaryError("Canary identity differs from the reviewed operator target.")
        if target.subscription is not None:
            expected = {
                "AZURE_SUBSCRIPTION_ID": target.subscription,
                "AZURE_TENANT_ID": target.tenant,
                "AZURE_CLIENT_ID": target.client,
                "AZURE_CANARY_REGION": target.region,
            }
            if any(os.environ.get(key) != value for key, value in expected.items()):
                raise CanaryError(
                    "Protected fallback configuration does not match the fixed target."
                )
            refs = {
                f"{setting('repository')}/{path}@refs/heads/main"
                for path in (target.workflow_path, target.cleanup_workflow_path)
            }
            if os.environ.get("GITHUB_WORKFLOW_REF") not in refs:
                raise CanaryError(
                    "Only the protected fallback workflow pair may use this target."
                )
        return cls(
            os.environ["AZURE_SUBSCRIPTION_ID"],
            os.environ["AZURE_TENANT_ID"],
            os.environ["AZURE_CANARY_REGION"],
            os.environ["GITHUB_REPOSITORY"],
            target,
        )

    def validate_workflow(self, operation: str) -> None:
        if self.target.cleanup_workflow_path is None:
            return
        path = (
            self.target.workflow_path
            if operation == "create"
            else self.target.cleanup_workflow_path
        )
        if (
            os.environ.get("GITHUB_WORKFLOW_REF")
            != f"{self.repository}/{path}@refs/heads/main"
        ):
            raise CanaryError("Canary operation does not match its protected workflow.")

    def az(self, *arguments: str) -> object:
        return command_json(
            [
                "az",
                *arguments,
                "--subscription",
                self.subscription,
                "--only-show-errors",
                "--output",
                "json",
            ]
        )

    def validate_scope(self) -> None:
        account = self.az("account", "show")
        if account["id"] != self.subscription or account["tenantId"] != self.tenant:
            raise CanaryError(
                "Azure account does not match the protected subscription and tenant."
            )
        if (
            account.get("user", {}).get("type") != "servicePrincipal"
            or account.get("user", {}).get("name") != setting("deployment_client_id")
        ):
            raise CanaryError(
                "Azure login principal does not match the fixed fallback identity."
            )
        group = self.az("group", "show", "--name", self.target.resource_group)
        expected_id = f"/subscriptions/{self.subscription}/resourceGroups/{self.target.resource_group}"
        if (
            group["id"].lower() != expected_id.lower()
            or group["name"] != self.target.resource_group
            or group["location"] != self.region
            or group.get("tags") != self.target.group_tags
        ):
            raise CanaryError(
                "Resource group identity, region or exact ownership tags do not match."
            )

    def identity(self) -> dict | None:
        identities = self.az(
            "identity", "list", "--resource-group", self.target.resource_group
        )
        matching = [
            item for item in identities if item["name"].lower() == IDENTITY_NAME.lower()
        ]
        if not matching:
            return None
        if len(matching) != 1:
            raise CanaryError("Ambiguous fixed canary identity.")
        identity = matching[0]
        expected_id = (
            f"/subscriptions/{self.subscription}/resourceGroups/{self.target.resource_group}"
            f"/providers/{IDENTITY_TYPE}/{IDENTITY_NAME}"
        )
        if (
            identity["id"].lower() != expected_id.lower()
            or identity["name"] != IDENTITY_NAME
            or identity["type"].lower() != IDENTITY_TYPE.lower()
            or identity["location"] != self.region
        ):
            raise CanaryError(
                "Canary identity name, type, location or resource ID does not match."
            )
        tags = identity.get("tags") or {}
        expected_tags = {
            **self.target.identity_tags,
            "purpose": PURPOSE,
            "repository": self.repository,
        }
        if any(tags.get(key) != value for key, value in expected_tags.items()):
            raise CanaryError(
                "Canary identity ownership tags do not match; preserving resource."
            )
        if (
            not re.fullmatch(r"[1-9][0-9]*", tags.get("runId", ""))
            or not re.fullmatch(r"[1-9][0-9]*", tags.get("runAttempt", ""))
            or not re.fullmatch(r"[0-9a-f]{40}", tags.get("sourceSha", ""))
        ):
            raise CanaryError(
                "Canary run ownership metadata is invalid; preserving resource."
            )
        return identity


def create(context: Context) -> None:
    context.validate_workflow("create")
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise CanaryError("Canary creation requires an explicit main-branch dispatch.")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    sha = os.environ.get("GITHUB_SHA", "")
    if (
        not re.fullmatch(r"[1-9][0-9]*", run_id)
        or not re.fullmatch(r"[1-9][0-9]*", attempt)
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
    ):
        raise CanaryError("Invalid trusted workflow run context.")
    context.validate_scope()
    if context.identity() is not None:
        raise CanaryError(
            "Fixed canary already exists; cleanup must finish before another run."
        )
    tags = {
        **context.target.identity_tags,
        "purpose": PURPOSE,
        "repository": context.repository,
        "runId": run_id,
        "runAttempt": attempt,
        "sourceSha": sha,
    }
    context.az(
        "identity",
        "create",
        "--resource-group",
        context.target.resource_group,
        "--name",
        IDENTITY_NAME,
        "--location",
        context.region,
        "--tags",
        *(f"{key}={value}" for key, value in tags.items()),
    )
    identity = context.identity()
    if identity is None or identity["tags"] != tags:
        raise CanaryError(
            "Created identity did not verify; independent cleanup is required."
        )
    print(
        "Fixed owned canary created and verified; no compute resources were provisioned."
    )


def cleanup(context: Context, expected_run_id: str) -> None:
    context.validate_workflow("cleanup")
    context.validate_scope()
    identity = context.identity()
    if identity is None:
        print("Verified: fixed canary identity is absent.")
        return
    tags = identity["tags"]
    if expected_run_id and tags["runId"] != expected_run_id:
        raise CanaryError("Canary belongs to a different run; preserving resource.")
    run = command_json(
        ["gh", "api", f"repos/{context.repository}/actions/runs/{tags['runId']}"]
    )
    if (
        run["repository"]["full_name"] != context.repository
        or run["head_repository"]["full_name"] != context.repository
        or run["path"]
        not in (context.target.workflow_path, f"{context.target.workflow_path}@main")
        or run["event"] != "workflow_dispatch"
        or run["head_branch"] != "main"
        or run["head_sha"] != tags["sourceSha"]
        or str(run["run_attempt"]) != tags["runAttempt"]
        or run["status"] != "completed"
    ):
        raise CanaryError(
            "Owning run is not a completed trusted canary; preserving resource."
        )
    context.az(
        "identity",
        "delete",
        "--resource-group",
        context.target.resource_group,
        "--name",
        IDENTITY_NAME,
    )
    if context.identity() is not None:
        raise CanaryError("Canary deletion did not verify.")
    print(
        "Verified: owned canary deleted and fixed identity is absent; resource group preserved."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "cleanup", "validate-config"))
    parser.add_argument("--target", choices=tuple(TARGETS), default="primary")
    args = parser.parse_args()
    try:
        context = Context.from_environment(args.target)
        if args.operation == "create":
            create(context)
        elif args.operation == "cleanup":
            cleanup(context, os.environ.get("EXPECTED_RUN_ID", ""))
        else:
            print(
                "Protected canary configuration verified; no Azure commands executed."
            )
    except CanaryError as error:
        print(f"Canary refused or failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
