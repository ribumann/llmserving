"""Execute the shipped Bash with synthetic commands; no APT, Docker or cloud writes.

Runs on Linux and Windows Git Bash. Only filesystem roots are redirected into
pytest's temp directory; retry counts, control flow and fail-fast stay unchanged.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from common import azure_demo_vm

from conftest import load_worker_entrypoint

TEMPLATE = Path(__file__).resolve().parents[2] / "infra/demo/cloud-init.tftpl"
worker = load_worker_entrypoint("model_deployment")


def cloud_script(name):
    template = TEMPLATE.read_text(encoding="utf-8")
    content = template.split(f"  - path: /opt/llmserving/{name}\n", 1)[1]
    content = content.split("    content: |\n", 1)[1]
    content = content.split("\n  - path:", 1)[0].split("\nruncmd:", 1)[0]
    return textwrap.dedent(content).replace("${vllm_image}", "synthetic@sha256:123")


def sandbox_paths(script):
    return (
        script.replace("/opt/llmserving", "./state")
        .replace("/etc/apt", "./etc/apt")
        .replace("/usr/share/keyrings", "./keyrings")
        .replace("/etc/os-release", "./os-release")
    )


@pytest.fixture
def shell(tmp_path):
    bash = shutil.which("bash")
    if not bash:
        pytest.fail("Executable bootstrap coverage requires Bash (Git Bash on Windows)")
    for directory in ["bin", "state", "etc/apt/sources.list.d", "keyrings"]:
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    (tmp_path / "os-release").write_text("VERSION_CODENAME=jammy\n", encoding="utf-8")

    def write(path, content):
        destination = tmp_path / path
        destination.write_text(content, encoding="utf-8", newline="\n")
        destination.chmod(0o755)

    write("bootstrap.sh", sandbox_paths(cloud_script("bootstrap.sh")))
    write("state/run-vllm.sh", sandbox_paths(cloud_script("run-vllm.sh")))
    stubs = {
        "apt-get": """\
n=0; [ ! -f apt-count ] || n=$(cat apt-count)
n=$((n + 1)); echo "$n" > apt-count
if [ "$n" -le "${APT_LOCKS:-0}" ] || \
   { [ "${APT_LOCK_EVERY:-0}" -gt 0 ] && [ "$((n % APT_LOCK_EVERY))" -ne 0 ]; }; then
  message="E: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process 123"
  echo "${APT_LOCK_MESSAGE:-$message}" >&2
  exit 100
fi
if [ -n "${APT_FAIL_MATCH:-}" ] && [[ "$*" == *"$APT_FAIL_MATCH"* ]]; then
  echo "${APT_ERROR:-E: Unable to locate package synthetic}" >&2
  exit 100
fi
""",
        "sleep": """\
n=0; [ ! -f sleep-count ] || n=$(cat sleep-count)
n=$((n + 1)); echo "$n" > sleep-count
if [ "${SLEEP_BOOTSTRAP:-0}" = 1 ] && [ "$n" = 1 ]; then bash bootstrap.sh; fi
""",
        "timeout": """\
shift; shift
exec "$@"
""",
        "cloud-init": """\
if [ "${CLOUD_INIT_COMPLETE_BOOTSTRAP:-0}" = 1 ]; then bash bootstrap.sh; fi
exit "${CLOUD_INIT_STATUS:-0}"
""",
        "curl": """\
if [ "${CURL_FAIL:-0}" = 1 ]; then exit 22; fi
echo 'deb https://synthetic stable main'
""",
        "gpg": """\
cat >/dev/null
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then shift; printf key > "$1"; break; fi
  shift
done
""",
        "dpkg": "echo amd64\n",
        "systemctl": 'exit "${SYSTEMCTL_FAIL:-0}"\n',
        "nvidia-ctk": 'exit "${TOOLKIT_FAIL:-0}"\n',
        "nvidia-smi": 'exit "${DRIVER_FAIL:-0}"\n',
        "docker": """\
case "$1" in
  info) exit "${DOCKER_FAIL:-0}";;
  pull) exit "${PULL_FAIL:-0}";;
  run) touch model-started; echo synthetic-container;;
esac
""",
    }
    for name, body in stubs.items():
        write(
            f"bin/{name}",
            f'#!/usr/bin/env bash\nset -eu\necho "{name} $*" >> events\n{body}',
        )

    def run(script, **env):
        write("test.sh", sandbox_paths(script))
        return subprocess.run(
            [bash, "-c", 'export PATH="$PWD/bin:$PATH"; exec bash ./test.sh'],
            cwd=tmp_path,
            env={**os.environ, **{key: str(value) for key, value in env.items()}},
            text=True,
            capture_output=True,
            # Git Bash process startup on Windows is much slower than Linux;
            # exhaustion still asserts the exact production retry/wait counts.
            timeout=120,
        )

    return SimpleNamespace(root=tmp_path, run=run)


def test_no_early_package_module_and_no_package_process_timeout(shell):
    template = TEMPLATE.read_text(encoding="utf-8")
    assert not re.search(r"^(packages|package_update|package_upgrade):", template, re.M)
    assert "  - [bash, /opt/llmserving/bootstrap.sh]" in template
    result = shell.run("bash bootstrap.sh")
    assert result.returncode == 0, result.stderr
    events = (shell.root / "events").read_text().splitlines()
    assert [line for line in events if line.startswith("timeout ")] == [
        "timeout --kill-after=10s 120 docker pull synthetic@sha256:123"
    ]


def test_lock_contention_retries_then_bootstrap_is_idempotently_ready(shell):
    for locks in [2, 0]:
        result = shell.run("bash bootstrap.sh", APT_LOCKS=locks, PULL_FAIL=1)
        assert result.returncode == 0, result.stderr
        assert (shell.root / "state/bootstrap.ready").exists()
        assert not (shell.root / "state/bootstrap.failed").exists()
    assert (shell.root / "sleep-count").read_text().strip() == "2"
    events = (shell.root / "events").read_text()
    assert "install -y ca-certificates curl gnupg" in events
    assert "install -y docker-ce docker-ce-cli containerd.io" in events
    assert "nvidia-ctk runtime configure --runtime=docker" in events
    assert events.index("systemctl restart docker") < events.index("docker info")


def test_lock_retry_exhaustion_fails_without_installing_runtime(shell):
    result = shell.run("bash bootstrap.sh", APT_LOCKS=100)
    assert result.returncode == 100
    assert "lock retry budget exhausted at prerequisites" in result.stderr
    assert (shell.root / "apt-count").read_text().strip() == "30"
    assert (shell.root / "sleep-count").read_text().strip() == "29"
    assert (shell.root / "state/bootstrap.failed").exists()
    assert not (shell.root / "state/bootstrap.ready").exists()
    assert "docker " not in (shell.root / "events").read_text()


def test_repeated_contention_across_stages_has_shared_retry_budget(shell):
    result = shell.run("bash bootstrap.sh", APT_LOCK_EVERY=12)
    assert result.returncode == 100
    assert "lock retry budget exhausted at nvidia-container-toolkit" in result.stderr
    assert (shell.root / "sleep-count").read_text().strip() == "60"
    assert (shell.root / "state/bootstrap.failed").exists()
    assert not (shell.root / "state/bootstrap.ready").exists()


def test_older_native_apt_lock_error_is_retried(shell):
    result = shell.run(
        "bash bootstrap.sh",
        APT_LOCKS=1,
        APT_LOCK_MESSAGE="E: Could not get lock /var/lib/apt/lists/lock - open "
        "(11: Resource temporarily unavailable)",
    )
    assert result.returncode == 0, result.stderr
    assert (shell.root / "sleep-count").read_text().strip() == "1"


def test_permission_failure_is_not_lock_contention_and_can_be_safely_retried(shell):
    result = shell.run(
        "bash bootstrap.sh",
        APT_FAIL_MATCH="update",
        APT_ERROR="E: Unable to acquire the dpkg frontend lock; are you root?",
    )
    assert result.returncode == 100
    assert not (shell.root / "sleep-count").exists()
    assert (shell.root / "state/bootstrap.failed").exists()
    result = shell.run("bash bootstrap.sh")
    assert result.returncode == 0, result.stderr
    assert (shell.root / "state/bootstrap.ready").exists()
    assert not (shell.root / "state/bootstrap.failed").exists()


@pytest.mark.parametrize(
    "failure",
    [
        {"APT_FAIL_MATCH": "update"},
        {"APT_FAIL_MATCH": "nvidia-container-toolkit"},
        {"CURL_FAIL": 1},
        {"TOOLKIT_FAIL": 1},
        {"SYSTEMCTL_FAIL": 1},
        {"DOCKER_FAIL": 1},
    ],
)
def test_non_lock_failure_is_terminal_and_clears_stale_readiness(shell, failure):
    (shell.root / "state/bootstrap.ready").touch()
    result = shell.run("bash bootstrap.sh", **failure)
    assert result.returncode != 0
    assert "GPU bootstrap failed at" in result.stderr
    assert (shell.root / "state/bootstrap.failed").exists()
    assert not (shell.root / "state/bootstrap.ready").exists()
    assert not (shell.root / "sleep-count").exists()
    if failure.get("APT_FAIL_MATCH") == "update":
        assert (shell.root / "apt-count").read_text().strip() == "1"
        assert "not lock contention" in result.stderr


def test_deployment_waits_for_executed_bootstrap_before_model_start(shell):
    script = "\n".join(worker._build_script_lines("synthetic/model", "", []))
    result = shell.run("set -euo pipefail\n" + script, SLEEP_BOOTSTRAP=1)
    assert result.returncode == 0, result.stderr
    assert (shell.root / "model-started").exists()
    events = (shell.root / "events").read_text()
    assert events.index("nvidia-ctk runtime configure") < events.index("docker run")


@pytest.mark.parametrize("state", ["failed", "missing", "both"])
def test_deployment_never_starts_model_before_success(shell, state):
    if state in {"failed", "both"}:
        (shell.root / "state/bootstrap.failed").touch()
    if state == "both":
        (shell.root / "state/bootstrap.ready").touch()
    result = shell.run(
        "set -euo pipefail\n"
        + "\n".join(worker._build_script_lines("synthetic/model", "", []))
    )
    assert result.returncode != 0
    assert not (shell.root / "model-started").exists()
    if state == "missing":
        assert "Timed out waiting" in result.stderr
        assert (shell.root / "sleep-count").read_text().strip() == "150"
    else:
        assert "bootstrap failed" in result.stderr
        assert not (shell.root / "sleep-count").exists()


def test_direct_model_script_also_requires_bootstrap_success(shell):
    result = shell.run("bash state/run-vllm.sh synthetic/model ''")
    assert result.returncode != 0
    assert not (shell.root / "model-started").exists()


def test_model_start_requires_actual_driver_readiness(shell):
    (shell.root / "state/bootstrap.ready").touch()
    result = shell.run("bash state/run-vllm.sh synthetic/model ''", DRIVER_FAIL=1)
    assert result.returncode != 0
    assert "driver readiness timed out" in result.stderr
    assert not (shell.root / "model-started").exists()


def bootstrap_gate():
    return TEMPLATE.with_name("bootstrap-gate.sh").read_text(encoding="utf-8")


def test_managed_driver_has_explicit_bootstrap_gate_dependency():
    source = TEMPLATE.with_name("main.tf").read_text(encoding="utf-8")
    driver = source.split(
        'resource "azurerm_virtual_machine_extension" "nvidia_driver" {', 1
    )[1]
    assert re.search(
        r"depends_on\s*=\s*\[azurerm_virtual_machine_extension.bootstrap_gate\]", driver
    )
    gate = source.split(
        'resource "azurerm_virtual_machine_extension" "bootstrap_gate" {', 1
    )[1].split("# Installs the NVIDIA", 1)[0]
    assert 'script = filebase64("${path.module}/bootstrap-gate.sh")' in gate
    assert "azurerm_linux_virtual_machine.demo.id" in gate
    assert "nvidia_driver" not in gate  # No dependency cycle.


def test_gate_waits_for_real_bootstrap_without_running_driver_early(shell):
    result = shell.run(bootstrap_gate(), CLOUD_INIT_COMPLETE_BOOTSTRAP=1, APT_LOCKS=1)
    assert result.returncode == 0, result.stderr
    assert "managed NVIDIA driver installation may start" in result.stdout
    assert (shell.root / "state/bootstrap.ready").exists()
    events = (shell.root / "events").read_text()
    assert events.index("cloud-init status --wait") < events.index("apt-get ")
    assert events.index("apt-get ") < events.index("docker info")


@pytest.mark.parametrize("status", [1, 2, 127])
def test_gate_propagates_cloud_init_failure_even_with_stale_ready_marker(shell, status):
    (shell.root / "state/bootstrap.ready").touch()
    result = shell.run(bootstrap_gate(), CLOUD_INIT_STATUS=status)
    assert result.returncode == status
    assert "cloud-init failed or readiness wait timed out" in result.stderr
    assert "installation may start" not in result.stdout


@pytest.mark.parametrize("markers", [[], ["failed"], ["ready", "failed"]])
def test_gate_rejects_missing_or_failed_bootstrap_despite_cloud_init_success(
    shell, markers
):
    for marker in markers:
        (shell.root / f"state/bootstrap.{marker}").touch()
    result = shell.run(bootstrap_gate())
    assert result.returncode == 1
    assert "successful runtime bootstrap was not confirmed" in result.stderr


def test_gate_propagates_actual_bootstrap_failure(shell):
    result = shell.run(
        bootstrap_gate(), CLOUD_INIT_COMPLETE_BOOTSTRAP=1, APT_FAIL_MATCH="update"
    )
    assert result.returncode == 100
    assert (shell.root / "state/bootstrap.failed").exists()
    assert not (shell.root / "state/bootstrap.ready").exists()
    assert "installation may start" not in result.stdout


def test_gate_timeout_only_terminates_status_observer(shell):
    # Execute real GNU timeout, shortening only its deadline for this test.
    # The simulated package transaction is a sibling, not a child of the
    # observer, matching cloud-init's independent systemd service.
    assert "timeout --kill-after=10s 1500 cloud-init status --wait" in bootstrap_gate()
    gate = bootstrap_gate().replace(
        "timeout --kill-after=10s 1500", '"/usr/bin/timeout" --kill-after=1s 0.1s'
    )
    (shell.root / "bin/cloud-init").write_text(
        "#!/bin/sh\nexec /usr/bin/sleep 5\n", encoding="utf-8", newline="\n"
    )
    script = (
        # Keep the sibling alive until explicitly released, rather than relying
        # on process startup timing (particularly slow under Windows Git Bash).
        'trap "touch package-finish" EXIT\n'
        "(while [ ! -f package-finish ]; do /usr/bin/sleep 1; done; "
        "touch package-survived) &\npackage_pid=$!\n"
        "set +e\n(\n" + gate + "\n)\nrc=$?\nset -e\n"
        'kill -0 "$package_pid"\ntouch package-finish\nwait "$package_pid"\nexit "$rc"\n'
    )
    result = shell.run(script)
    # GNU timeout returns 137 if its KILL fallback was needed (seen on Git Bash).
    assert result.returncode in {124, 137}, result.stderr
    assert f"readiness wait timed out (exit {result.returncode})" in result.stderr
    assert (shell.root / "package-survived").exists()
    assert not (shell.root / "state/bootstrap.ready").exists()


@pytest.mark.parametrize(
    "script,ok",
    [
        (["true"], True),
        (["echo normal-warning >&2"], True),
        (["exit 0"], True),
        (["false", "echo must-not-run"], False),
        (["false | true", "echo must-not-run"], False),
        (['echo "$UNDEFINED_SYNTHETIC_VARIABLE"'], False),
        (["bash -c 'exit 127'"], False),
    ],
)
def test_run_command_wrapper_executes_bash_fail_fast(shell, script, ok):
    client = MagicMock()
    observed = []

    def respond(_group, _vm, parameters):
        # Emulate the classic extension's /bin/sh transport and combined message.
        # The wrapper, not the transport shell, must establish Bash fail-fast.
        result = shell.run("sh -c " + shlex.quote("\n".join(parameters["script"])))
        observed.append(result)
        return SimpleNamespace(
            result=lambda: {
                "value": [
                    {
                        "code": "ProvisioningState/succeeded",
                        "message": f"Enable succeeded: \n[stdout]\n{result.stdout}"
                        f"\n[stderr]\n{result.stderr}",
                    }
                ]
            }
        )

    client.virtual_machines.begin_run_command.side_effect = respond
    if ok:
        azure_demo_vm.run_command_on_vm(
            "sub", "demo", script_lines=script, client=client
        )
    else:
        with pytest.raises(RuntimeError, match="output withheld"):
            azure_demo_vm.run_command_on_vm(
                "sub", "demo", script_lines=script, client=client
            )
    assert observed
    assert (observed[0].returncode == 0) is ok
    assert "must-not-run" not in observed[0].stdout
