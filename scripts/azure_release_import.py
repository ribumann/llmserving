"""Consume one checked candidate; optionally push to the existing owned registry."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import release_bundle as bundle
from azure_canary import FALLBACK_TARGET
from azure_disk_probe import mask_subject

WORKFLOW = ".github/workflows/azure-fallback-release-import.yml"
CANDIDATE_RUN = "42031238122"
CANDIDATE_ATTEMPT = "1"
CANDIDATE_SHA = "1f9f15f2c7046c81f9b988170d77ea3750a3ac65"
CANDIDATE_MANIFEST_SHA256 = (
    "2392632e34ff4622fdb4ab311637e9e70767cccb2b2ae91f1632b3451c2a3c7a"
)
GROUP = "rg-llmserving-e2e-shared"
REGISTRY = "llmreleaseacr0ea5e6"
LOGIN_SERVER = f"{REGISTRY}.azurecr.io"
REGION = "italynorth"
TAG = f"tested-{CANDIDATE_SHA}"


class ReleaseImportError(RuntimeError):
    pass


def command(arguments: list[str], *, decode: bool = True) -> object:
    executable = arguments[0]
    if os.name == "nt":
        executable = shutil.which(executable)
        if executable is None:
            raise ReleaseImportError(
                "Release executable is unavailable; no shell or authentication fallback."
            )
    try:
        result = subprocess.run(
            [executable, *arguments[1:]],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseImportError(
            f"Release command failed ({type(exc).__name__})."
        ) from None
    if result.returncode:
        raise ReleaseImportError(
            f"{' '.join(arguments[:2])} failed (exit {result.returncode}); "
            "no credential or raw service diagnostic is published."
        )
    if not decode:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise ReleaseImportError("Release command returned malformed JSON.") from None


def az(*arguments: str, decode: bool = True) -> object:
    return command(
        [
            "az",
            *arguments,
            "--subscription",
            FALLBACK_TARGET.subscription,
            "--only-show-errors",
            "--output",
            "json",
        ],
        decode=decode,
    )


def validate_config() -> None:
    expected = {
        "GITHUB_REPOSITORY": bundle.REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_WORKFLOW_REF": f"{bundle.REPOSITORY}/{WORKFLOW}@refs/heads/main",
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise ReleaseImportError(
            "Release consumption requires its fixed main/manual workflow."
        )
    if not re.fullmatch(r"[0-9a-f]{40}", os.environ.get("GITHUB_SHA", "")):
        raise ReleaseImportError("Consuming workflow source identity is invalid.")


def validate_candidate() -> None:
    run = command(
        [
            "gh",
            "api",
            f"repos/{bundle.REPOSITORY}/actions/runs/{CANDIDATE_RUN}/attempts/{CANDIDATE_ATTEMPT}",
        ]
    )
    if (
        not isinstance(run, dict)
        or not isinstance(run.get("repository"), dict)
        or not isinstance(run.get("head_repository"), dict)
        or run["repository"].get("full_name") != bundle.REPOSITORY
        or run["head_repository"].get("full_name") != bundle.REPOSITORY
        or run.get("path")
        not in {
            ".github/workflows/runtime-ci.yml",
            ".github/workflows/runtime-ci.yml@main",
        }
        or str(run.get("id")) != CANDIDATE_RUN
        or str(run.get("run_attempt")) != CANDIDATE_ATTEMPT
        or run.get("head_sha") != CANDIDATE_SHA
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        raise ReleaseImportError(
            "Candidate is not the fixed successful trusted run attempt."
        )


@contextmanager
def candidate_identity():
    # Bind the verifier to the independently fixed producer, not downloaded metadata.
    fields = {
        "GITHUB_SHA": CANDIDATE_SHA,
        "GITHUB_RUN_ID": CANDIDATE_RUN,
        "GITHUB_RUN_ATTEMPT": CANDIDATE_ATTEMPT,
    }
    previous = {key: os.environ.get(key) for key in fields}
    os.environ.update(fields)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def verify_archives(directory: Path) -> dict:
    manifest_path = directory / "release-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ReleaseImportError("Candidate manifest must be a regular file.")
    if bundle.file_hash(manifest_path) != CANDIDATE_MANIFEST_SHA256:
        raise ReleaseImportError(
            "Manifest checksum does not match the fixed reviewed candidate."
        )
    manifest = json.loads(manifest_path.read_text())
    with candidate_identity():
        bundle.verify(manifest, directory)
    return manifest


def inspect_image(reference: str, expected_digest: str) -> None:
    images = command(["docker", "image", "inspect", reference])
    if (
        not isinstance(images, list)
        or len(images) != 1
        or not isinstance(images[0], dict)
        or images[0].get("Id") != expected_digest
        or images[0].get("Os") != "linux"
        or images[0].get("Architecture") != "amd64"
    ):
        raise ReleaseImportError(
            "Loaded/pulled image does not match the tested Linux/amd64 config."
        )


def validate_registry() -> None:
    expected = {
        "AZURE_SUBSCRIPTION_ID": FALLBACK_TARGET.subscription,
        "AZURE_TENANT_ID": FALLBACK_TARGET.tenant,
        "AZURE_CLIENT_ID": FALLBACK_TARGET.client,
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise ReleaseImportError("Protected registry target does not match.")
    account = az("account", "show")
    if (
        not isinstance(account, dict)
        or account.get("id") != FALLBACK_TARGET.subscription
        or account.get("tenantId") != FALLBACK_TARGET.tenant
        or not isinstance(account.get("user"), dict)
        or account["user"].get("type") != "servicePrincipal"
        or account["user"].get("name") != FALLBACK_TARGET.client
    ):
        raise ReleaseImportError(
            "Registry login principal or target is not the fixed fallback."
        )
    group = az("group", "show", "--name", GROUP)
    group_id = f"/subscriptions/{FALLBACK_TARGET.subscription}/resourceGroups/{GROUP}"
    if (
        not isinstance(group, dict)
        or str(group.get("id", "")).lower() != group_id.lower()
        or group.get("name") != GROUP
        or group.get("tags") != FALLBACK_TARGET.group_tags
    ):
        raise ReleaseImportError(
            "Retained shared group identity/ownership does not match."
        )
    registry = az("acr", "show", "--name", REGISTRY, "--resource-group", GROUP)
    required_tags = {
        **FALLBACK_TARGET.group_tags,
        "feature": "azure-llm-serving-demo",
        "component": "shared",
        "stage": "release",
    }
    if (
        not isinstance(registry, dict)
        or str(registry.get("id", "")).lower()
        != f"{group_id}/providers/Microsoft.ContainerRegistry/registries/{REGISTRY}".lower()
        or registry.get("name") != REGISTRY
        or registry.get("loginServer") != LOGIN_SERVER
        or str(registry.get("location", "")).lower() != REGION
        or not isinstance(registry.get("sku"), dict)
        or registry["sku"].get("name") != "Basic"
        or registry.get("adminUserEnabled") is not False
        or registry.get("provisioningState") != "Succeeded"
        or not isinstance(registry.get("tags"), dict)
        or any(
            registry["tags"].get(key) != value for key, value in required_tags.items()
        )
    ):
        raise ReleaseImportError(
            "Existing shared registry shape/ownership does not match; never create or adopt."
        )


def image_metadata(
    component: str, *, digest: str | None = None, tag: str = TAG
) -> dict:
    image = f"{component}@{digest}" if digest is not None else f"{component}:{tag}"
    metadata = az(
        "acr",
        "repository",
        "show",
        "--name",
        REGISTRY,
        "--image",
        image,
    )
    if (
        not isinstance(metadata, dict)
        or not isinstance(metadata.get("digest"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", metadata["digest"])
        or not isinstance(metadata.get("changeableAttributes"), dict)
    ):
        raise ReleaseImportError("Registry manifest digest/attributes are malformed.")
    return metadata


def push_image(component: str, config_digest: str) -> dict:
    reference = f"{LOGIN_SERVER}/{component}:{TAG}"
    repositories = az("acr", "repository", "list", "--name", REGISTRY)
    if not isinstance(repositories, list) or any(
        not isinstance(item, str) for item in repositories
    ):
        raise ReleaseImportError("Registry repository inventory is malformed.")
    tags = []
    if component in repositories:
        tags = az(
            "acr",
            "repository",
            "show-tags",
            "--name",
            REGISTRY,
            "--repository",
            component,
        )
        if not isinstance(tags, list) or any(
            not isinstance(item, str) for item in tags
        ):
            raise ReleaseImportError("Registry tag inventory is malformed.")
    if TAG in tags:
        command(["docker", "pull", reference], decode=False)
        inspect_image(reference, config_digest)
    else:
        # A nonce isolates upload from the source tag. The server-side NoForce
        # import, not this earlier inventory, arbitrates concurrent writers.
        upload_tag = f"{TAG}-upload-{secrets.token_hex(16)}"
        upload_reference = f"{LOGIN_SERVER}/{component}:{upload_tag}"
        command(
            ["docker", "image", "tag", f"llmserving-ci:{component}", upload_reference],
            decode=False,
        )
        command(["docker", "push", upload_reference], decode=False)
        uploaded = image_metadata(component, tag=upload_tag)
        uploaded_reference = f"{LOGIN_SERVER}/{component}@{uploaded['digest']}"
        command(["docker", "pull", uploaded_reference], decode=False)
        inspect_image(uploaded_reference, config_digest)
        registry_id = (
            f"/subscriptions/{FALLBACK_TARGET.subscription}/resourceGroups/{GROUP}"
            f"/providers/Microsoft.ContainerRegistry/registries/{REGISTRY}"
        )
        az(
            "acr",
            "import",
            "--name",
            REGISTRY,
            "--registry",
            registry_id,
            "--source",
            uploaded_reference,
            "--image",
            f"{component}:{TAG}",
            decode=False,
        )
        if image_metadata(component)["digest"] != uploaded["digest"]:
            raise ReleaseImportError(
                "Write-once imported tag does not match the verified upload."
            )
        if image_metadata(component, tag=upload_tag)["digest"] != uploaded["digest"]:
            raise ReleaseImportError("Upload tag changed; refuse to untag it.")
        az(
            "acr",
            "repository",
            "untag",
            "--name",
            REGISTRY,
            "--image",
            f"{component}:{upload_tag}",
            decode=False,
        )
    metadata = image_metadata(component)
    digest_reference = f"{LOGIN_SERVER}/{component}@{metadata['digest']}"
    command(["docker", "pull", digest_reference], decode=False)
    inspect_image(digest_reference, config_digest)
    az(
        "acr",
        "repository",
        "update",
        "--name",
        REGISTRY,
        "--image",
        f"{component}@{metadata['digest']}",
        "--write-enabled",
        "false",
        "--delete-enabled",
        "false",
        decode=False,
    )
    az(
        "acr",
        "repository",
        "update",
        "--name",
        REGISTRY,
        "--image",
        f"{component}:{TAG}",
        "--write-enabled",
        "false",
        "--delete-enabled",
        "false",
        decode=False,
    )
    locked = image_metadata(component)
    locked_manifest = image_metadata(component, digest=metadata["digest"])
    if (
        locked["digest"] != metadata["digest"]
        or locked["changeableAttributes"].get("writeEnabled") is not False
        or locked["changeableAttributes"].get("deleteEnabled") is not False
        or locked_manifest["digest"] != metadata["digest"]
        or locked_manifest["changeableAttributes"].get("writeEnabled") is not False
        or locked_manifest["changeableAttributes"].get("deleteEnabled") is not False
    ):
        raise ReleaseImportError(
            "Exact tag/manifest digest/write/delete locks did not verify."
        )
    return {
        "component": component,
        "image": digest_reference,
        "imageConfigDigest": config_digest,
    }


def consume(directory: Path, *, push: bool) -> dict:
    validate_config()
    validate_candidate()
    manifest = verify_archives(directory)
    images = [
        item for item in manifest["artifacts"] if item["component"] in bundle.IMAGES
    ]
    command(["docker", "info"], decode=False)
    for record in images:
        if not push:
            command(
                ["docker", "load", "--input", str(directory / record["archive"])],
                decode=False,
            )
        inspect_image(
            f"llmserving-ci:{record['component']}", record["imageConfigDigest"]
        )
    result = {
        "schemaVersion": 1,
        "repository": bundle.REPOSITORY,
        "sourceSha": CANDIDATE_SHA,
        "runId": CANDIDATE_RUN,
        "runAttempt": CANDIDATE_ATTEMPT,
        "downloadHashesAndDockerLoadVerified": True,
        "registryImportVerified": False,
        "resourcesOrRolesCreated": False,
        "functionsPackageSha256": next(
            item["sha256"]
            for item in manifest["artifacts"]
            if item["component"] == "functions"
        ),
        "images": [],
    }
    if push:
        validate_registry()
        az("acr", "login", "--name", REGISTRY, decode=False)
        for record in images:
            result["images"].append(
                push_image(record["component"], record["imageConfigDigest"])
            )
        result["registryImportVerified"] = True
    else:
        result["images"] = [
            {
                "component": item["component"],
                "imageConfigDigest": item["imageConfigDigest"],
            }
            for item in images
        ]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("validate-config", "consume"))
    parser.add_argument("--archives", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    try:
        validate_config()
        if args.operation == "validate-config":
            mask_subject()
            print("Fixed main-only release consumer verified; no Azure commands.")
            return
        if args.archives is None or args.result is None:
            raise ReleaseImportError("Archives and result paths are required.")
        result = consume(args.archives, push=args.push)
        args.result.write_text(json.dumps(result, indent=2) + "\n")
        print(
            "Seven tested image downloads/configs verified; "
            f"registry import verified: {result['registryImportVerified']}. "
            "No application deployment or model/cloud acceptance is claimed."
        )
    except (ReleaseImportError, ValueError, TypeError, OSError) as exc:
        raise SystemExit(f"Release consumption refused or failed: {exc}") from None


if __name__ == "__main__":
    main()
