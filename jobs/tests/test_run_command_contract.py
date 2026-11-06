"""Classic RunShellScript streams are not process exit status."""

from __future__ import annotations

import traceback
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from common import azure_demo_vm

MARKER = "LLMSERVING_RUN_OK_current"
SECRET = "hf_synthetic_never_publish"


def invoke(monkeypatch, result):
    monkeypatch.setattr(
        azure_demo_vm.uuid, "uuid4", lambda: SimpleNamespace(hex="current")
    )
    client = MagicMock()
    client.virtual_machines.begin_run_command.return_value.result.return_value = result
    return azure_demo_vm.run_command_on_vm(
        "sub", "demo", script_lines=[f"echo {SECRET}"], client=client
    )


def classic(stdout, stderr=""):
    return {
        "value": [
            {
                "code": "ProvisioningState/succeeded",
                "message": f"Enable succeeded: \n[stdout]\n{stdout}\n[stderr]\n{stderr}",
            }
        ]
    }


def test_classic_success_allows_normal_stderr(monkeypatch):
    result = classic(f"container-id\n{MARKER}\n", "normal warning")
    assert invoke(monkeypatch, result) is result


@pytest.mark.parametrize(
    "result",
    [
        classic("", f"docker: command not found {SECRET}"),
        classic(f"failed command {SECRET}"),
        classic("LLMSERVING_RUN_OK_stale"),
        classic(f"prefix{MARKER}"),
        classic(f"{MARKER}suffix"),
        classic("", MARKER),
        classic(f"{MARKER}\n{MARKER}"),
        {"value": [{"code": "ProvisioningState/succeeded", "message": MARKER}]},
        {"value": [{"code": "ComponentStatus/StdErr/succeeded", "message": MARKER}]},
        {"value": [{"code": "ComponentStatus/StdOut/failed", "message": MARKER}]},
        {"value": []},
        None,
    ],
)
def test_missing_wrong_or_ambiguous_marker_fails_secret_safely(monkeypatch, result):
    with pytest.raises(RuntimeError, match="output withheld") as error:
        invoke(monkeypatch, result)
    diagnostic = "".join(traceback.format_exception(error.value))
    assert SECRET not in diagnostic
    assert error.value.__context__ is None


def test_real_sdk_objects_and_separate_streams(monkeypatch):
    from azure.mgmt.compute.models import InstanceViewStatus, RunCommandResult

    result = RunCommandResult(
        value=[
            InstanceViewStatus(
                code="ComponentStatus/StdOut/succeeded", message=f"{MARKER}\n"
            ),
            InstanceViewStatus(
                code="ComponentStatus/StdErr/succeeded", message="benign stderr"
            ),
        ]
    )
    assert invoke(monkeypatch, result) is result


def test_real_sdk_classic_combined_stream(monkeypatch):
    from azure.mgmt.compute.models import InstanceViewStatus, RunCommandResult

    result = RunCommandResult(value=[InstanceViewStatus(**classic(MARKER)["value"][0])])
    assert invoke(monkeypatch, result) is result


@pytest.mark.parametrize("failure_point", ["begin", "poll"])
def test_sdk_errors_never_escape_with_script_or_secret(
    monkeypatch, failure_point, caplog
):
    client = MagicMock()
    operation = client.virtual_machines.begin_run_command
    if failure_point == "begin":
        operation.side_effect = RuntimeError(f"request script={SECRET}")
    else:
        operation.return_value.result.side_effect = RuntimeError(f"response={SECRET}")
    with pytest.raises(RuntimeError, match="output withheld") as error:
        azure_demo_vm.run_command_on_vm(
            "sub", "demo", script_lines=[f"echo {SECRET}"], client=client
        )
    assert SECRET not in "".join(traceback.format_exception(error.value))
    assert SECRET not in caplog.text
    assert error.value.__context__ is None


def test_every_invocation_uses_fresh_marker(monkeypatch):
    client = MagicMock()
    markers = []

    def respond(_group, _vm, parameters):
        import shlex

        marker = shlex.split(parameters["script"][-1])[-1]
        markers.append(marker)
        return SimpleNamespace(result=lambda: classic(marker))

    client.virtual_machines.begin_run_command.side_effect = respond
    for _ in range(2):
        azure_demo_vm.run_command_on_vm(
            "sub", "demo", script_lines=["true"], client=client
        )
    assert len(set(markers)) == 2
