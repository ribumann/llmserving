from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from common import azure_demo_vm

from conftest import load_worker_entrypoint


def test_saved_group_targets_ip_power_and_run_command_without_renaming_resources(
    monkeypatch,
):
    network = MagicMock()
    network.network_interfaces.get.return_value.ip_configurations = [
        SimpleNamespace(private_ip_address="10.0.1.5")
    ]
    assert (
        azure_demo_vm.resolve_private_ip(
            "sub",
            "demo123",
            name_prefix="saved",
            resource_group_name="rg-retained",
            client=network,
        )
        == "10.0.1.5"
    )
    network.network_interfaces.get.assert_called_once_with(
        "rg-retained", "saved-demo123-nic"
    )

    compute = MagicMock()
    compute.virtual_machines.instance_view.return_value.statuses = [
        SimpleNamespace(code="PowerState/deallocated")
    ]
    azure_demo_vm.ensure_vm_running(
        "sub",
        "demo123",
        name_prefix="saved",
        resource_group_name="rg-retained",
        client=compute,
    )
    compute.virtual_machines.instance_view.assert_called_once_with(
        "rg-retained", "saved-demo123-vm"
    )
    compute.virtual_machines.begin_start.assert_called_once_with(
        "rg-retained", "saved-demo123-vm"
    )
    monkeypatch.setattr(
        azure_demo_vm.uuid, "uuid4", lambda: SimpleNamespace(hex="retained")
    )
    compute.virtual_machines.begin_run_command.return_value.result.return_value = {
        "value": [
            {
                "code": "ComponentStatus/StdOut/succeeded",
                "message": "LLMSERVING_RUN_OK_retained\n",
            }
        ]
    }
    azure_demo_vm.run_command_on_vm(
        "sub",
        "demo123",
        name_prefix="saved",
        resource_group_name="rg-retained",
        script_lines=["true"],
        client=compute,
    )
    assert compute.virtual_machines.begin_run_command.call_args.args[:2] == (
        "rg-retained",
        "saved-demo123-vm",
    )


@pytest.mark.parametrize("group", ["", "../group", "group.", 12])
@pytest.mark.parametrize(
    "operation", ["resolve_private_ip", "ensure_vm_running", "run_command_on_vm"]
)
def test_invalid_explicit_group_never_falls_back_or_constructs_sdk(
    monkeypatch, group, operation
):
    factory = MagicMock()
    monkeypatch.setattr(azure_demo_vm, "_default_network_client", factory)
    monkeypatch.setattr(azure_demo_vm, "_default_compute_client", factory)
    kwargs = {"script_lines": ["true"]} if operation == "run_command_on_vm" else {}
    with pytest.raises(ValueError, match="persisted demo resource group"):
        getattr(azure_demo_vm, operation)(
            "sub", "demo123", resource_group_name=group, **kwargs
        )
    factory.assert_not_called()


def test_model_worker_forwards_same_scope_to_all_calls():
    worker = load_worker_entrypoint("model_deployment")
    ensure = MagicMock()
    dispatch = MagicMock()
    resolve = MagicMock(return_value="10.0.1.5")
    worker.run(
        workflow_id="wf",
        subscription_id="sub",
        environment_id="demo123",
        model_repo="test-model",
        hf_token="",
        name_prefix="saved",
        extra_args=[],
        health_check_attempts=1,
        health_check_interval_seconds=0,
        callback=MagicMock(),
        resource_group_name="rg-retained",
        ensure_running=ensure,
        dispatch_run_command=dispatch,
        resolve_ip=resolve,
        is_healthy=lambda _: True,
    )
    for call in [ensure, dispatch, resolve]:
        assert call.call_args.kwargs["resource_group_name"] == "rg-retained"
        assert call.call_args.kwargs["name_prefix"] == "saved"


@pytest.mark.parametrize("kind", ["evaluation_worker", "performance_worker"])
def test_future_evaluation_worker_lookup_supports_explicit_scope_without_routing_change(
    kind,
):
    worker = load_worker_entrypoint(kind)
    resolve = MagicMock(return_value="10.0.1.5")
    workload = (
        {"cases": [{"caseId": "test", "prompt": "hi", "expectedSubstring": "answer"}]}
        if kind == "evaluation_worker"
        else {"prompt": "hi", "concurrency": 1, "request_count": 1}
    )
    worker.run(
        workflow_id="wf",
        subscription_id="sub",
        environment_id="demo123",
        run_id="run",
        name_prefix="saved",
        resource_group_name="rg-retained",
        callback=MagicMock(),
        resolve_ip=resolve,
        submit=lambda *_: SimpleNamespace(ok=True, text="answer", latency_seconds=0.1),
        **workload,
    )
    resolve.assert_called_once_with(
        "sub", "demo123", name_prefix="saved", resource_group_name="rg-retained"
    )


@pytest.mark.parametrize(
    "kind", ["model_deployment", "evaluation_worker", "performance_worker"]
)
def test_job_json_scope_is_forwarded_unchanged(kind, monkeypatch):
    worker = load_worker_entrypoint(kind)
    monkeypatch.setenv("WORKFLOW_ID", "wf")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub")
    monkeypatch.setattr(
        worker,
        "job_input_from_env",
        lambda: {
            "environmentId": "demo123",
            "resourceGroupName": "rg-retained",
            "namePrefix": "saved",
            "modelRepo": "test-model",
            "runId": "run",
            "cases": [{"prompt": "hi"}],
            "workload": {"requestCount": 1},
        },
    )
    monkeypatch.setattr(worker, "WorkflowCallbackClient", MagicMock())
    monkeypatch.setattr(worker, "configure_job_telemetry", MagicMock())
    execute = MagicMock()
    monkeypatch.setattr(worker, "run", execute)
    assert worker.main() == 0
    assert execute.call_args.kwargs["resource_group_name"] == "rg-retained"
    assert execute.call_args.kwargs["name_prefix"] == "saved"
