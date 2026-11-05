"""Record and verify credential-free, run-bound release-candidate archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

IMAGES = (
    "backend",
    "frontend",
    "terraform_runner",
    "model_deployment",
    "evaluation_worker",
    "performance_worker",
    "export_worker",
)
COMPONENTS = (*IMAGES, "functions")
REPOSITORY = "ribumann/llmserving"


def context() -> dict:
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
    ):
        raise ValueError(
            "Release-candidate packaging requires a main-branch manual run."
        )
    sha = os.environ.get("GITHUB_SHA", "")
    run = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or any(
        not re.fullmatch(r"[1-9][0-9]*", value) for value in (run, attempt)
    ):
        raise ValueError("Release-candidate source/run identity is invalid.")
    return {
        "schemaVersion": 1,
        "repository": REPOSITORY,
        "sourceSha": sha,
        "runId": run,
        "runAttempt": attempt,
    }


def archive_name(component: str) -> str:
    if component not in COMPONENTS:
        raise ValueError("Unknown release component.")
    return "functions.zip" if component == "functions" else f"{component}.tar.gz"


def file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("Archive must be a nonempty regular file, not a symlink.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_record(record: object, component: str, expected: dict) -> dict:
    if not isinstance(record, dict):
        raise TypeError("Component record must be an object.")
    fields = {*expected, "component", "archive", "sizeBytes", "sha256"}
    if component in IMAGES:
        fields.add("imageConfigDigest")
    if (
        set(record) != fields
        or any(
            type(record.get(key)) is not type(value) or record[key] != value
            for key, value in expected.items()
        )
        or record.get("component") != component
        or record.get("archive") != archive_name(component)
        or type(record.get("sizeBytes")) is not int
        or record["sizeBytes"] <= 0
        or not isinstance(record.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
    ):
        raise ValueError(
            "Component identity, source/run, archive or checksum is invalid."
        )
    if component in IMAGES and (
        not isinstance(record["imageConfigDigest"], str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", record["imageConfigDigest"])
    ):
        raise ValueError("Docker image config digest is invalid.")
    return record


def record_archive(component: str, archive: Path, image_id: str | None) -> dict:
    identity = context()
    if archive.name != archive_name(component):
        raise ValueError("Archive filename does not match the fixed component.")
    record = {
        **identity,
        "component": component,
        "archive": archive.name,
        "sizeBytes": archive.stat().st_size,
        "sha256": file_hash(archive),
    }
    if component in IMAGES:
        record["imageConfigDigest"] = image_id
    elif image_id is not None:
        raise ValueError("Functions is a ZIP package, not an image.")
    return validate_record(record, component, identity)


def assemble(directory: Path) -> dict:
    identity = context()
    if {path.name for path in directory.iterdir()} != {
        f"{component}.json" for component in COMPONENTS
    }:
        raise ValueError(
            "Exactly seven image records and one Functions record are required."
        )
    records = []
    for component in COMPONENTS:
        path = directory / f"{component}.json"
        if path.is_symlink() or not path.is_file():
            raise ValueError("Component record must be a regular file.")
        records.append(
            validate_record(json.loads(path.read_text()), component, identity)
        )
    return {
        **identity,
        "kind": "checked-release-candidate",
        "artifacts": records,
        "limitations": [
            "Docker config digests are NOT registry pull digests.",
            "Archives must be hash-verified before docker load or Functions deployment.",
            "Not a signed provenance attestation, dependency lock or reproducible rebuild.",
            "No model weights, Azure resources, secrets or Terraform state are included.",
            "Registry import/pull digests, model pinning and cloud acceptance remain required.",
        ],
    }


def verify(manifest: object, directory: Path) -> None:
    identity = context()
    if (
        not isinstance(manifest, dict)
        or any(
            type(manifest.get(key)) is not type(value) or manifest[key] != value
            for key, value in identity.items()
        )
        or manifest.get("kind") != "checked-release-candidate"
    ):
        raise ValueError(
            "Manifest source/run identity does not match the expected release run."
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(COMPONENTS):
        raise ValueError("Manifest must contain every fixed component exactly once.")
    by_name = {}
    for record in artifacts:
        if not isinstance(record, dict) or not isinstance(record.get("component"), str):
            raise TypeError("Invalid manifest component.")
        component = record["component"]
        if component not in COMPONENTS or component in by_name:
            raise ValueError("Unexpected or duplicate manifest component.")
        by_name[component] = validate_record(record, component, identity)
    for component in COMPONENTS:
        record = by_name[component]
        path = directory / record["archive"]
        if (
            file_hash(path) != record["sha256"]
            or path.stat().st_size != record["sizeBytes"]
        ):
            raise ValueError(f"{component} archive checksum/size mismatch.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--component", choices=COMPONENTS, required=True)
    record.add_argument("--archive", type=Path, required=True)
    record.add_argument("--image-id")
    bundle = subparsers.add_parser("assemble")
    bundle.add_argument("--records", type=Path, required=True)
    verification = subparsers.add_parser("verify")
    verification.add_argument("--manifest", type=Path, required=True)
    verification.add_argument("--archives", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "record":
            result = record_archive(args.component, args.archive, args.image_id)
        elif args.operation == "assemble":
            result = assemble(args.records)
        else:
            verify(json.loads(args.manifest.read_text()), args.archives)
            print(
                "Every fixed release archive matches its expected run-bound checksum."
            )
            return
        print(json.dumps(result, indent=2))
    except (ValueError, TypeError, OSError) as exc:
        raise SystemExit(f"Release bundle error: {exc}") from None


if __name__ == "__main__":
    main()
