mock_provider "azurerm" {
  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg-llm-shared-dev"
    }
  }
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "33333333-3333-3333-3333-333333333333"
      subscription_id = "44444444-4444-4444-4444-444444444444"
      object_id       = "55555555-5555-5555-5555-555555555555"
      client_id       = "66666666-6666-6666-6666-666666666666"
    }
  }
}

variables {
  subscription_id = "44444444-4444-4444-4444-444444444444"
}

run "legacy_singleton" {
  command   = apply
  state_key = "singleton-upgrade"
  module {
    source = "./tests/migration/legacy"
  }
}

run "upgrade_default" {
  command   = plan
  state_key = "singleton-upgrade"
  assert {
    condition     = length(azurerm_resource_group.shared) == 1 && azurerm_resource_group.shared[0].id == run.legacy_singleton.resource_group_id
    error_message = "The real moved block must preserve the singleton group ID, not plan replacement."
  }
  assert {
    condition     = azurerm_resource_group.shared[0].name == "rg-llm-shared-dev" && azurerm_resource_group.shared[0].tags["managedBy"] == "terraform"
    error_message = "Upgrading existing managed state must preserve the group name and tags."
  }
}
