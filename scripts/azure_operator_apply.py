"""Single guarded local-state operator7 apply with independent ARM cleanup."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import azure_operator_access as cleanup
import azure_shared_bridge as bridge
import validate_operator_access_plan as scope
import validate_operator_reconcile as reconcile
from azure_release_import import ReleaseImportError, az, command
from validate_retained_group_plan import PlanRejected, run_saved_plan


def variable(name: str) -> str:
    record = command(
        [
            "gh",
            "api",
            f"repos/{bridge.shared.REPOSITORY}/actions/variables/{name}",
        ]
    )
    if (
        not isinstance(record, dict)
        or record.get("name") != name
        or not isinstance(record.get("value"), str)
    ):
        raise bridge.shared.SharedError("Operator cleanup variable is unverified.")
    return record["value"]


def arming(selected: dict, run_id: str) -> None:
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise bridge.shared.SharedError(
            "Exact successful operator cleanup run is required."
        )
    deadline = bridge.shared.utc(selected["expires_at"])
    now = datetime.now(UTC)
    if (
        variable("OPERATOR_ACCESS_CLEANUP_ARMED") != "true"
        or variable("OPERATOR_ACCESS_EXPIRES_AT") != selected["expires_at"]
        or variable("OPERATOR_ACCESS_ROOT_SHA256")
        != selected["root_certificate_sha256"]
        or not now < deadline <= now + timedelta(hours=4)
        or deadline > bridge.configuration(creating=True)
    ):
        raise bridge.shared.SharedError(
            "Operator cleanup fingerprint/deadline is not independently armed."
        )
    run = command(
        [
            "gh",
            "api",
            f"repos/{bridge.shared.REPOSITORY}/actions/runs/{run_id}/attempts/1",
        ]
    )
    if (
        not isinstance(run, dict)
        or str(run.get("id")) != run_id
        or run.get("run_attempt") != 1
        or run.get("path") not in {cleanup.WORKFLOW, f"{cleanup.WORKFLOW}@main"}
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or not isinstance(run.get("head_repository"), dict)
        or run["head_repository"].get("full_name") != bridge.shared.REPOSITORY
        or not now - timedelta(minutes=30)
        <= bridge.shared.utc(run.get("created_at"))
        <= now
    ):
        raise bridge.shared.SharedError(
            "Operator cleanup run is not a recent trusted successful exact attempt."
        )
    jobs = command(
        [
            "gh",
            "api",
            f"repos/{bridge.shared.REPOSITORY}/actions/runs/{run_id}/attempts/1/jobs?per_page=100",
        ]
    )
    if (
        not isinstance(jobs, dict)
        or jobs.get("total_count") != 1
        or not isinstance(jobs.get("jobs"), list)
        or len(jobs["jobs"]) != 1
    ):
        raise bridge.shared.SharedError(
            "Operator cleanup exact attempt job is unverified."
        )
    job = jobs["jobs"][0]
    required = {
        "Run azure/login@a457da9ea143d694b1b9c7c869ebb04ebe844ef5",
        "Verify fixed ARM cleanup and remove only eligible operator resources",
    }
    if (
        not isinstance(job, dict)
        or job.get("name") != "cleanup"
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
        or not isinstance(job.get("steps"), list)
    ):
        raise bridge.shared.SharedError(
            "Operator cleanup job did not actually execute successfully."
        )
    steps = job["steps"]
    for name in required:
        matches = [
            step
            for step in steps
            if isinstance(step, dict) and step.get("name") == name
        ]
        if (
            len(matches) != 1
            or matches[0].get("status") != "completed"
            or matches[0].get("conclusion") != "success"
        ):
            raise bridge.shared.SharedError(
                "Operator cleanup login/ARM verification was skipped or failed."
            )


def local_context(module: Path) -> None:
    bridge.private_directory(module)
    if any(
        os.environ.get(key)
        for key in ("TF_DATA_DIR", "TF_WORKSPACE", "TF_CLI_CONFIG_FILE")
    ):
        raise bridge.shared.SharedError(
            "Operator apply refuses redirected data/workspace/config."
        )
    workspace = module / ".terraform/environment"
    if (
        workspace.is_symlink()
        or workspace.exists()
        and workspace.read_text().strip() != "default"
    ):
        raise bridge.shared.SharedError(
            "Operator apply requires the persisted default workspace."
        )
    version = command(["terraform", "version", "-json"])
    if not isinstance(version, dict) or version.get("terraform_version") != "1.16.6":
        raise bridge.shared.SharedError("Operator apply requires Terraform 1.16.6.")
    backend_path = module / ".terraform/terraform.tfstate"
    if backend_path.is_symlink():
        raise bridge.shared.SharedError(
            "Operator backend metadata must not be a symlink."
        )
    if backend_path.exists():
        backend = json.loads(backend_path.read_text()).get("backend", {})
        if not isinstance(backend, dict) or backend.get("type") not in {None, "local"}:
            raise bridge.shared.SharedError(
                "Operator apply requires canonical local state."
            )
        if backend.get("type") == "local" and (
            not isinstance(backend.get("config"), dict)
            or backend["config"].get("path") not in {None, "", "terraform.tfstate"}
            or backend["config"].get("workspace_dir")
            not in {None, "", "terraform.tfstate.d"}
        ):
            raise bridge.shared.SharedError(
                "Operator apply refuses redirected local state."
            )


def live(selected: dict, *, recovering: bool = False) -> None:
    bridge.identity(protected=False)
    bridge.shared.dependencies_absent()
    if recovering:
        if set(cleanup.inventory(selected)) != reconcile.EXISTING:
            raise bridge.shared.SharedError(
                "Operator recovery requires exactly the six owned existing resources."
            )
    else:
        existing = bridge.shared.inventory(None, bridge=True)
        if set(existing) != set(scope.shared.RESOURCES):
            raise bridge.shared.SharedError(
                "Operator apply requires complete owned shared infrastructure."
            )
        bridge.reject_attached_children(existing)
        if cleanup.inventory(selected):
            raise bridge.shared.SharedError(
                "Initial operator apply cannot adopt/retry existing resources."
            )
    feature = az(
        "feature",
        "show",
        "--namespace",
        "Microsoft.Network",
        "--name",
        "AllowBringYourOwnPublicIpAddress",
    )
    if (
        not isinstance(feature, dict)
        or not isinstance(feature.get("properties"), dict)
        or feature["properties"].get("state") != "Registered"
    ):
        raise bridge.shared.SharedError(
            "Policy-required public IP feature must be Registered."
        )


def local_apply(
    plan: Path,
    log: Path,
    target: Path,
    second_backup: Path,
    cleanup_run: str,
    *,
    recovering: bool = False,
) -> None:
    if target.is_symlink() or not target.is_file():
        raise bridge.shared.SharedError(
            "Operator public target must be a regular file."
        )
    selected = json.loads(target.read_text())
    if not isinstance(selected, dict) or not {
        "root_certificate_public_data",
        "root_certificate_sha256",
        "expires_at",
    }.issubset(selected):
        raise bridge.shared.SharedError("Operator public target is incomplete.")
    module = Path.cwd()
    local_context(module)
    arming(selected, cleanup_run)
    if recovering:
        live(selected, recovering=True)
    else:
        live(selected)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    before = bridge.backup(module, second_backup, f"operator-{stamp}-before")
    canonical = None
    if recovering:
        reconcile.snapshot(before["state"])
        canonical = reconcile.canonical_state()
    elif before["state"] is not None:
        raise bridge.shared.SharedError(
            "Initial operator apply requires no canonical state."
        )

    def gate(native: object, group: str) -> None:
        if recovering:
            reconcile.validate_reconcile(native, group, canonical, selected)
        else:
            scope.validate(native, group, operation="create", target=selected)
        local_context(module)
        if recovering:
            reconcile.snapshot(before["state"])
        elif (module / "terraform.tfstate").exists() or (
            module / "terraform.tfstate"
        ).is_symlink():
            raise bridge.shared.SharedError(
                "Canonical operator state appeared before apply."
            )
        arming(selected, cleanup_run)
        if recovering:
            live(selected, recovering=True)
        else:
            live(selected)

    try:
        run_saved_plan(
            plan,
            scope.shared.GROUP,
            log,
            terraform="terraform",
            apply=True,
            validator=gate,
            require_canonical_local=True,
        )
    finally:
        bridge.backup(module, second_backup, f"operator-{stamp}-after")
    if not (module / "terraform.tfstate").is_file():
        raise bridge.shared.SharedError(
            "Operator apply did not persist state; preserve logs, no retry."
        )
    print(
        "Guarded operator7 applied with verified private checkpoints; no VPN/data-plane/migration claim."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--private-log", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--second-backup", type=Path, required=True)
    parser.add_argument("--cleanup-run", required=True)
    parser.add_argument(
        "--recover-serial8",
        action="store_true",
        help="Only the reviewed exact failed operator snapshot; never a general retry.",
    )
    args = parser.parse_args()
    try:
        local_apply(
            args.plan,
            args.private_log,
            args.target,
            args.second_backup,
            args.cleanup_run,
            recovering=args.recover_serial8,
        )
    except (
        bridge.shared.SharedError,
        PlanRejected,
        ReleaseImportError,
        OSError,
        ValueError,
        KeyError,
    ) as error:
        raise SystemExit(
            f"Operator apply stopped: {type(error).__name__}; preserve private state/logs, no retry."
        ) from None


if __name__ == "__main__":
    main()
