from __future__ import annotations

import pytest
from common.azure_demo_vm import demo_resource_names, resolve_private_ip, vllm_base_url


def test_demo_resource_names_matches_infra_demo_naming_convention() -> None:
    rg, vm_name, nic_name = demo_resource_names("demo123", name_prefix="llm")
    assert rg == "rg-llm-demo-demo123"
    assert vm_name == "llm-demo123-vm"
    assert nic_name == "llm-demo123-nic"


class _FakeIpConfig:
    def __init__(self, private_ip_address: str | None) -> None:
        self.private_ip_address = private_ip_address


class _FakeNic:
    def __init__(self, ip_configurations: list[_FakeIpConfig]) -> None:
        self.ip_configurations = ip_configurations


class _FakeNetworkInterfaces:
    def __init__(self, nic: _FakeNic) -> None:
        self._nic = nic
        self.calls: list[tuple[str, str]] = []

    def get(self, resource_group: str, nic_name: str) -> _FakeNic:
        self.calls.append((resource_group, nic_name))
        return self._nic


class _FakeNetworkClient:
    def __init__(self, nic: _FakeNic) -> None:
        self.network_interfaces = _FakeNetworkInterfaces(nic)


def test_resolve_private_ip_returns_first_ip_configuration() -> None:
    client = _FakeNetworkClient(_FakeNic([_FakeIpConfig("10.0.1.5")]))
    ip = resolve_private_ip("sub-1", "demo123", client=client)
    assert ip == "10.0.1.5"
    assert client.network_interfaces.calls == [("rg-llm-demo-demo123", "llm-demo123-nic")]


def test_resolve_private_ip_raises_when_no_ip_configurations() -> None:
    client = _FakeNetworkClient(_FakeNic([]))
    with pytest.raises(RuntimeError, match="no private IP"):
        resolve_private_ip("sub-1", "demo123", client=client)


def test_resolve_private_ip_raises_when_ip_address_missing() -> None:
    client = _FakeNetworkClient(_FakeNic([_FakeIpConfig(None)]))
    with pytest.raises(RuntimeError, match="no private IP"):
        resolve_private_ip("sub-1", "demo123", client=client)


def test_vllm_base_url_formats_http_url() -> None:
    assert vllm_base_url("10.0.1.5") == "http://10.0.1.5:8000"
    assert vllm_base_url("10.0.1.5", port=9000) == "http://10.0.1.5:9000"


class _FakePoller:
    def __init__(self, result: object) -> None:
        self._result = result

    def result(self) -> object:
        return self._result


class _FakeVirtualMachines:
    def __init__(self, result: object) -> None:
        self._result = result
        self.calls: list[tuple[str, str, dict]] = []

    def begin_run_command(self, resource_group: str, vm_name: str, parameters: dict) -> _FakePoller:
        self.calls.append((resource_group, vm_name, parameters))
        return _FakePoller(self._result)


class _FakeComputeClient:
    def __init__(self, result: object = "ok") -> None:
        self.virtual_machines = _FakeVirtualMachines(result)


def test_run_command_on_vm_targets_correct_resource_and_blocks_on_result() -> None:
    from common.azure_demo_vm import run_command_on_vm

    client = _FakeComputeClient(result="run-command-output")
    result = run_command_on_vm(
        "sub-1", "demo123", script_lines=["/opt/llmserving/run-vllm.sh a b"], client=client
    )

    assert result == "run-command-output"
    resource_group, vm_name, parameters = client.virtual_machines.calls[0]
    assert resource_group == "rg-llm-demo-demo123"
    assert vm_name == "llm-demo123-vm"
    assert parameters["command_id"] == "RunShellScript"
    assert parameters["script"] == ["/opt/llmserving/run-vllm.sh a b"]


class _FakeStatus:
    def __init__(self, code: str) -> None:
        self.code = code


class _FakeInstanceView:
    def __init__(self, statuses: list[_FakeStatus]) -> None:
        self.statuses = statuses


class _FakeVirtualMachinesWithPowerState:
    def __init__(self, power_state_code: str | None) -> None:
        self._power_state_code = power_state_code
        self.instance_view_calls: list[tuple[str, str]] = []
        self.begin_start_calls: list[tuple[str, str]] = []

    def instance_view(self, resource_group: str, vm_name: str) -> _FakeInstanceView:
        self.instance_view_calls.append((resource_group, vm_name))
        statuses = [_FakeStatus("ProvisioningState/succeeded")]
        if self._power_state_code:
            statuses.append(_FakeStatus(self._power_state_code))
        return _FakeInstanceView(statuses)

    def begin_start(self, resource_group: str, vm_name: str) -> _FakePoller:
        self.begin_start_calls.append((resource_group, vm_name))
        return _FakePoller(None)


class _FakeComputeClientWithPowerState:
    def __init__(self, power_state_code: str | None) -> None:
        self.virtual_machines = _FakeVirtualMachinesWithPowerState(power_state_code)


def test_ensure_vm_running_starts_deallocated_vm() -> None:
    from common.azure_demo_vm import ensure_vm_running

    client = _FakeComputeClientWithPowerState("PowerState/deallocated")
    power_state = ensure_vm_running("sub-1", "demo123", client=client)

    assert power_state == "PowerState/deallocated"
    assert client.virtual_machines.instance_view_calls == [("rg-llm-demo-demo123", "llm-demo123-vm")]
    assert client.virtual_machines.begin_start_calls == [("rg-llm-demo-demo123", "llm-demo123-vm")]


def test_ensure_vm_running_does_not_restart_a_running_vm() -> None:
    from common.azure_demo_vm import ensure_vm_running

    client = _FakeComputeClientWithPowerState("PowerState/running")
    power_state = ensure_vm_running("sub-1", "demo123", client=client)

    assert power_state == "PowerState/running"
    assert client.virtual_machines.begin_start_calls == []


def test_ensure_vm_running_starts_vm_when_power_state_unknown() -> None:
    from common.azure_demo_vm import ensure_vm_running

    client = _FakeComputeClientWithPowerState(None)
    power_state = ensure_vm_running("sub-1", "demo123", client=client)

    assert power_state == "PowerState/unknown"
    assert client.virtual_machines.begin_start_calls == [("rg-llm-demo-demo123", "llm-demo123-vm")]
