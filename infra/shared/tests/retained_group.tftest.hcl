mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "33333333-3333-3333-3333-333333333333"
      subscription_id = "44444444-4444-4444-4444-444444444444"
      object_id       = "55555555-5555-5555-5555-555555555555"
      client_id       = "66666666-6666-6666-6666-666666666666"
    }
  }
  mock_data "azurerm_resource_group" {
    defaults = {
      name     = "rg-retained-shared"
      location = "eastus"
      id       = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg-retained-shared"
    }
  }
}

variables {
  subscription_id = "44444444-4444-4444-4444-444444444444"
  location        = "polandcentral"
}

run "managed_default" {
  command = plan
  variables {
    tags = { managedBy = "previously-ignored" }
  }
  assert {
    condition     = length(azurerm_resource_group.shared) == 1 && length(data.azurerm_resource_group.shared) == 0 && output.resource_group_name == "rg-llm-shared-dev"
    error_message = "Managed shared group must remain the default."
  }
  assert {
    condition     = azurerm_virtual_network.shared.name == "llm-shared-vnet" && azurerm_virtual_network.shared.tags["managedBy"] == "terraform"
    error_message = "Default names and legacy tag precedence must remain unchanged."
  }
}

run "retained_group" {
  command = plan
  variables {
    existing_resource_group_name = "rg-retained-shared"
    tags = {
      managedBy = "copilot-release"
      project   = "owned-test"
      component = "forged"
    }
  }
  assert {
    condition     = length(azurerm_resource_group.shared) == 0 && length(data.azurerm_resource_group.shared) == 1 && output.resource_group_name == "rg-retained-shared"
    error_message = "Retained shared mode must not own or adopt a resource group."
  }
  assert {
    condition     = azurerm_virtual_network.shared.resource_group_name == "rg-retained-shared" && azurerm_subnet.gpu.resource_group_name == "rg-retained-shared" && azurerm_key_vault.shared.resource_group_name == "rg-retained-shared"
    error_message = "Networking and platform resources must target the existing shared group."
  }
  assert {
    condition     = azurerm_virtual_network.shared.location == "polandcentral" && azurerm_private_endpoint.vault.location == "polandcentral" && output.location == "polandcentral"
    error_message = "Deployment region must not come from group metadata."
  }
  assert {
    condition     = azurerm_key_vault.shared.tags["managedBy"] == "copilot-release" && azurerm_virtual_network.shared.tags["project"] == "owned-test" && azurerm_virtual_network.shared.tags["component"] == "shared"
    error_message = "Retained resources must honor operator ownership tags while preserving fixed component tags."
  }
}

run "reject_blank_group" {
  command = plan
  variables {
    existing_resource_group_name = ""
  }
  expect_failures = [var.existing_resource_group_name]
}
