mock_provider "azurerm" {
  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg-llm-control-dev"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg-llm-control-dev/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-identity"
      principal_id = "77777777-7777-7777-7777-777777777777"
      client_id    = "88888888-8888-8888-8888-888888888888"
    }
  }
  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg-llm-control-dev/providers/Microsoft.App/managedEnvironments/llm-cae"
    }
  }
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "11111111-1111-1111-1111-111111111111"
      subscription_id = "44444444-4444-4444-4444-444444444444"
      object_id       = "55555555-5555-5555-5555-555555555555"
      client_id       = "66666666-6666-6666-6666-666666666666"
    }
  }
}
mock_provider "azuread" {}
mock_provider "azapi" {}
mock_provider "random" {}
mock_provider "time" {}

override_data {
  target = data.terraform_remote_state.shared
  values = {
    outputs = {
      location                               = "polandcentral"
      acr_login_server                       = "testregistry.azurecr.io"
      key_vault_uri                          = "https://isolated-test.vault.azure.net/"
      application_insights_connection_string = "InstrumentationKey=00000000-0000-0000-0000-000000000000"
      data_subnet_id                         = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/virtualNetworks/test/subnets/data"
      private_endpoints_subnet_id            = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/virtualNetworks/test/subnets/private"
      container_apps_subnet_id               = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/virtualNetworks/test/subnets/apps"
      functions_subnet_id                    = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/virtualNetworks/test/subnets/functions"
      postgres_private_dns_zone_id           = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/privateDnsZones/privatelink.postgres.database.azure.com"
      blob_private_dns_zone_id               = "/subscriptions/44444444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
      queue_private_dns_zone_id              = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/privateDnsZones/privatelink.queue.core.windows.net"
      table_private_dns_zone_id              = "/subscriptions/44444444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/privateDnsZones/privatelink.table.core.windows.net"
      log_analytics_workspace_id             = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.OperationalInsights/workspaces/test"
      acr_id                                 = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.ContainerRegistry/registries/test"
      key_vault_id                           = "/subscriptions/44444444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.KeyVault/vaults/isolated-test"
    }
  }
}

variables {
  subscription_id = "44444444-4444-4444-4444-444444444444"
}

run "existing_environment" {
  command   = apply
  state_key = "existing-infrastructure"
  module {
    source = "./tests/migration/legacy"
  }
}

run "matching_name_preserves_environment" {
  command   = plan
  state_key = "existing-infrastructure"
  variables {
    existing_sso_client_id                            = "22222222-2222-2222-2222-222222222222"
    existing_sso_secret_id                            = "https://isolated-test.vault.azure.net/secrets/test-sso"
    container_apps_infrastructure_resource_group_name = "RG-EXISTING-PLATFORM"
  }
  assert {
    condition     = azurerm_container_app_environment.control.id == run.existing_environment.environment_id && azurerm_container_app_environment.control.infrastructure_resource_group_name == "rg-existing-platform"
    error_message = "Matching names must preserve the existing environment, including Azure case-insensitivity."
  }
  assert {
    condition = (
      azurerm_resource_group.control[0].id == run.existing_environment.group_id
      && azurerm_role_assignment.backend_contributor["subscription"].id == run.existing_environment.role_ids.backend
      && azurerm_role_assignment.terraform_runner_contributor["subscription"].id == run.existing_environment.role_ids.terraform_runner
      && azurerm_role_assignment.model_deployment_vm_contributor["subscription"].id == run.existing_environment.role_ids.model_deployment
    )
    error_message = "The original singleton group and all three subscription assignments must survive their address moves without replacement."
  }
}

run "mismatched_name_fails_without_replacement" {
  command   = plan
  state_key = "existing-infrastructure"
  variables {
    existing_sso_client_id                            = "22222222-2222-2222-2222-222222222222"
    existing_sso_secret_id                            = "https://isolated-test.vault.azure.net/secrets/test-sso"
    container_apps_infrastructure_resource_group_name = "rg-different-platform"
  }
  expect_failures = [azurerm_container_app_environment.control]
}
