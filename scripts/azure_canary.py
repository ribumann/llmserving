"""A fixed, non-compute OIDC canary; never a general-purpose resource cleaner."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass

RESOURCE_GROUP = "rg-llm-cleanup-canary-oss-e2e"
IDENTITY_NAME = "id-llm-oidc-cleanup-canary"
IDENTITY_TYPE = "Microsoft.ManagedIdentity/userAssignedIdentities"
WORKFLOW_PATH = ".github/workflows/azure-oidc-canary.yml"
GROUP_TAGS = {
    "project": "llmserving-public-validation",
    "managedBy": "copilot-release",
}
PURPOSE = "oidc-cleanup-canary"


class CanaryError(RuntimeError):
    pass


def command_json(arguments: list[str]) -> object:
    result = subprocess.run(arguments, text=True, capture_output=True, check=False, timeout=120)
    if result.returncode:
        raise CanaryError(f"{arguments[0]} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


@dataclass(frozen=True)
class Context:
    subscription: str
    tenant: str
    region: str
    repository: str

    @classmethod
    def from_environment(cls) -> Context:
        required = (
            "AZURE_SUBSCRIPTION_ID",
            "AZURE_TENANT_ID",
            "AZURE_CANARY_REGION",
            "AZURE_CANARY_RESOURCE_GROUP",
            "GITHUB_REPOSITORY",
        )
        if any(not os.environ.get(key) for key in required):
            raise CanaryError("Missing protected canary configuration.")
        if os.environ["AZURE_CANARY_RESOURCE_GROUP"] != RESOURCE_GROUP:
            raise CanaryError("Canary resource group is not the fixed authorized group.")
        if os.environ.get("GITHUB_REF") != "refs/heads/main":
            raise CanaryError("Only protected main may operate this canary.")
        if os.environ["GITHUB_REPOSITORY"] != "ribumann/llmserving":
            raise CanaryError("Unexpected canary repository.")
        return cls(
            os.environ["AZURE_SUBSCRIPTION_ID"],
            os.environ["AZURE_TENANT_ID"],
            os.environ["AZURE_CANARY_REGION"],
            os.environ["GITHUB_REPOSITORY"],
        )

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
            raise CanaryError("Azure account does not match the protected subscription and tenant.")
        group = self.az("group", "show", "--name", RESOURCE_GROUP)
        expected_id = f"/subscriptions/{self.subscription}/resourceGroups/{RESOURCE_GROUP}"
        if (
            group["id"].lower() != expected_id.lower()
            or group["name"] != RESOURCE_GROUP
            or group["location"] != self.region
            or group.get("tags") != GROUP_TAGS
        ):
            raise CanaryError(
                "Resource group identity, region or exact ownership tags do not match."
            )

    def identity(self) -> dict | None:
        identities = self.az("identity", "list", "--resource-group", RESOURCE_GROUP)
        matching = [item for item in identities if item["name"].lower() == IDENTITY_NAME.lower()]
        if not matching:
            return None
        if len(matching) != 1:
            raise CanaryError("Ambiguous fixed canary identity.")
        identity = matching[0]
        expected_id = (
            f"/subscriptions/{self.subscription}/resourceGroups/{RESOURCE_GROUP}"
            f"/providers/{IDENTITY_TYPE}/{IDENTITY_NAME}"
        )
        if (
            identity["id"].lower() != expected_id.lower()
            or identity["name"] != IDENTITY_NAME
            or identity["type"].lower() != IDENTITY_TYPE.lower()
            or identity["location"] != self.region
        ):
            raise CanaryError("Canary identity name, type, location or resource ID does not match.")
        tags = identity.get("tags") or {}
        expected_tags = {**GROUP_TAGS, "purpose": PURPOSE, "repository": self.repository}
        if any(tags.get(key) != value for key, value in expected_tags.items()):
            raise CanaryError("Canary identity ownership tags do not match; preserving resource.")
        if (
            not re.fullmatch(r"[1-9][0-9]*", tags.get("runId", ""))
            or not re.fullmatch(r"[1-9][0-9]*", tags.get("runAttempt", ""))
            or not re.fullmatch(r"[0-9a-f]{40}", tags.get("sourceSha", ""))
        ):
            raise CanaryError("Canary run ownership metadata is invalid; preserving resource.")
        return identity


def create(context: Context) -> None:
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
        raise CanaryError("Fixed canary already exists; cleanup must finish before another run.")
    tags = {
        **GROUP_TAGS,
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
        RESOURCE_GROUP,
        "--name",
        IDENTITY_NAME,
        "--location",
        context.region,
        "--tags",
        *(f"{key}={value}" for key, value in tags.items()),
    )
    identity = context.identity()
    if identity is None or identity["tags"] != tags:
        raise CanaryError("Created identity did not verify; independent cleanup is required.")
    print("Fixed owned canary created and verified; no compute resources were provisioned.")


def cleanup(context: Context, expected_run_id: str) -> None:
    context.validate_scope()
    identity = context.identity()
    if identity is None:
        print("Verified: fixed canary identity is absent.")
        return
    tags = identity["tags"]
    if expected_run_id and tags["runId"] != expected_run_id:
        raise CanaryError("Canary belongs to a different run; preserving resource.")
    run = command_json(["gh", "api", f"repos/{context.repository}/actions/runs/{tags['runId']}"])
    if (
        run["repository"]["full_name"] != context.repository
        or run["head_repository"]["full_name"] != context.repository
        or run["path"] not in (WORKFLOW_PATH, f"{WORKFLOW_PATH}@main")
        or run["event"] != "workflow_dispatch"
        or run["head_branch"] != "main"
        or run["head_sha"] != tags["sourceSha"]
        or str(run["run_attempt"]) != tags["runAttempt"]
        or run["status"] != "completed"
    ):
        raise CanaryError("Owning run is not a completed trusted canary; preserving resource.")
    context.az("identity", "delete", "--resource-group", RESOURCE_GROUP, "--name", IDENTITY_NAME)
    if context.identity() is not None:
        raise CanaryError("Canary deletion did not verify.")
    print("Verified: owned canary deleted and fixed identity is absent; resource group preserved.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "cleanup"))
    args = parser.parse_args()
    try:
        context = Context.from_environment()
        if args.operation == "create":
            create(context)
        else:
            cleanup(context, os.environ.get("EXPECTED_RUN_ID", ""))
    except CanaryError as error:
        print(f"Canary refused or failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
