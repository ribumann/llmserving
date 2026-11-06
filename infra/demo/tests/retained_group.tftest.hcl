mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      name     = "rg-retained"
      location = "eastus"
      id       = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg-retained"
    }
  }
}

override_data {
  target = data.terraform_remote_state.shared
  values = {
    outputs = {
      location      = "polandcentral"
      gpu_subnet_id = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/shared/providers/Microsoft.Network/virtualNetworks/shared/subnets/gpu"
    }
  }
}

variables {
  subscription_id      = "44444444-4444-4444-4444-444444444444"
  environment_id       = "demo123"
  admin_ssh_public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCrgP4wSJC13w+p6GqIevlv3vtqFJWop44L3cB6qXluVnMaWRw+cg8QB14zziphwTiJG6ZbiFze4Yoa4oKovFDnqtn2jQmhtgwp5K64yn2Ra6hsXSpsmdRwtOlVPcD1g+93Joc8KBFz99NmM1u1iTnBqpc0ZC9kLFmfPWxadFtyrz7sFuxzzX7jpA/y5UbGi6mEYvsJmKHIivHBDKA0Z3XMBFmD0oOwGrUZN55Dz/UdP6FukoYEEDeZh1Y0bInjtq8G9x/qSwZC95njuUOy0IPpAyqY7MxZBEq/I4aUrYhwHLujrz/bt+Q2L29VgCHuWGRzLK6H7KCeRQZ2GElnMVMR test-only-discarded-private-half"
}

run "managed_default" {
  command = plan
  variables {
    tags = {
      managedBy = "previously-ignored"
    }
  }
  assert {
    condition     = length(azurerm_resource_group.demo) == 1 && length(data.azurerm_resource_group.demo) == 0 && azurerm_resource_group.demo[0].name == "rg-llm-demo-demo123"
    error_message = "The original managed group must remain the default."
  }
  assert {
    condition     = azurerm_network_interface.demo.name == "llm-demo123-nic" && azurerm_linux_virtual_machine.demo.name == "llm-demo123-vm"
    error_message = "Existing environment resource names must not change."
  }
  assert {
    condition     = azurerm_linux_virtual_machine.demo.tags["managedBy"] == "terraform"
    error_message = "Legacy managed mode must continue ignoring a caller's managedBy tag."
  }
  assert {
    condition     = azurerm_linux_virtual_machine.demo.priority == "Spot" && azurerm_linux_virtual_machine.demo.eviction_policy == "Deallocate" && azurerm_linux_virtual_machine.demo.max_bid_price == -1
    error_message = "Omitted allocation priority must preserve existing Spot behavior."
  }
  assert {
    condition = (
      azurerm_virtual_machine_extension.bootstrap_gate.name == "GpuBootstrapGate"
      && azurerm_virtual_machine_extension.bootstrap_gate.publisher == "Microsoft.Azure.Extensions"
      && azurerm_virtual_machine_extension.bootstrap_gate.type == "CustomScript"
      && azurerm_virtual_machine_extension.bootstrap_gate.type_handler_version == "2.1"
      && jsondecode(azurerm_virtual_machine_extension.bootstrap_gate.settings).script == filebase64("${path.module}/bootstrap-gate.sh")
      && !coalesce(azurerm_virtual_machine_extension.bootstrap_gate.failure_suppression_enabled, false)
      && !coalesce(azurerm_virtual_machine_extension.nvidia_driver.failure_suppression_enabled, false)
    )
    error_message = "First boot must use the shipped bounded observer without suppressing gate or NVIDIA failures."
  }
  assert {
    condition = (
      azurerm_virtual_machine_extension.nvidia_driver.publisher == "Microsoft.HpcCompute"
      && azurerm_virtual_machine_extension.nvidia_driver.type == "NvidiaGpuDriverLinux"
      && jsondecode(azurerm_virtual_machine_extension.nvidia_driver.settings).InstallMethod == 1
      && !jsondecode(azurerm_virtual_machine_extension.nvidia_driver.settings).installCUDA
    )
    error_message = "Ordering must preserve managed NVIDIA driver installation and existing driver settings."
  }
}

run "regular_allocation" {
  command = plan
  variables {
    vm_priority     = "Regular"
    vm_size         = "Standard_NC4as_T4_v3"
    expected_region = "polandcentral"
  }
  assert {
    condition     = azurerm_linux_virtual_machine.demo.priority == "Regular" && azurerm_linux_virtual_machine.demo.eviction_policy == null && azurerm_linux_virtual_machine.demo.size == "Standard_NC4as_T4_v3"
    error_message = "Explicit Regular allocation must use the requested SKU without a Spot eviction policy."
  }
}

run "reject_region_mismatch" {
  command = plan
  variables {
    expected_region = "italynorth"
  }
  expect_failures = [terraform_data.region_guard]
}

run "reject_unknown_priority" {
  command = plan
  variables {
    vm_priority = "spot"
  }
  expect_failures = [var.vm_priority]
}

run "reject_null_priority" {
  command = plan
  variables {
    vm_priority = null
  }
  expect_failures = [var.vm_priority]
}

run "retained_group" {
  command = plan
  variables {
    existing_resource_group_name = "rg-retained"
    tags = {
      managedBy     = "copilot-release"
      project       = "owned-test"
      environmentId = "forged"
    }
  }
  assert {
    condition     = length(azurerm_resource_group.demo) == 0 && length(data.azurerm_resource_group.demo) == 1 && output.resource_group_name == "rg-retained"
    error_message = "Retained mode must not manage or adopt the resource group."
  }
  assert {
    condition     = azurerm_network_interface.demo.resource_group_name == "rg-retained" && azurerm_linux_virtual_machine.demo.resource_group_name == "rg-retained" && azurerm_linux_virtual_machine.demo.location == "polandcentral"
    error_message = "Compute must use the retained group and shared subnet's region, not group metadata location."
  }
  assert {
    condition     = azurerm_linux_virtual_machine.demo.zone == null
    error_message = "GPU allocation must remain regional unless a supported availability zone is explicitly selected."
  }
  assert {
    condition     = azurerm_linux_virtual_machine.demo.tags["managedBy"] == "copilot-release" && azurerm_network_interface.demo.tags["project"] == "owned-test" && azurerm_virtual_machine_extension.nvidia_driver.tags["environmentId"] == "demo123" && azurerm_virtual_machine_extension.bootstrap_gate.tags["managedBy"] == "copilot-release" && azurerm_virtual_machine_extension.bootstrap_gate.tags["environmentId"] == "demo123"
    error_message = "Owned resource tags must preserve operator tags and enforce the environment id."
  }
}

run "reject_blank_group" {
  command = plan
  variables {
    existing_resource_group_name = ""
  }
  expect_failures = [var.existing_resource_group_name]
}
