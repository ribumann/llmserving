mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "11111111-1111-1111-1111-111111111111"
      subscription_id = "44444444-4444-4444-4444-444444444444"
      object_id       = "55555555-5555-5555-5555-555555555555"
      client_id       = "66666666-6666-6666-6666-666666666666"
    }
  }
}
mock_provider "azuread" {
  mock_data "azuread_client_config" {
    defaults = {
      tenant_id = "11111111-1111-1111-1111-111111111111"
      object_id = "55555555-5555-5555-5555-555555555555"
      client_id = "66666666-6666-6666-6666-666666666666"
    }
  }
}
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
      blob_private_dns_zone_id               = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
      queue_private_dns_zone_id              = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/privateDnsZones/privatelink.queue.core.windows.net"
      table_private_dns_zone_id              = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/privateDnsZones/privatelink.table.core.windows.net"
      log_analytics_workspace_id             = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.OperationalInsights/workspaces/test"
      acr_id                                 = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.ContainerRegistry/registries/test"
      key_vault_id                           = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.KeyVault/vaults/isolated-test"
    }
  }
}

variables {
  subscription_id        = "44444444-4444-4444-4444-444444444444"
  existing_sso_client_id = "22222222-2222-2222-2222-222222222222"
  existing_sso_secret_id = "https://isolated-test.vault.azure.net/secrets/test-sso"
}

run "external_same_tenant_default" {
  command = plan
  assert {
    condition     = var.container_apps_infrastructure_resource_group_name == null && azurerm_container_app_environment.control.infrastructure_resource_group_name == null
    error_message = "The existing platform-generated infrastructure group behavior must remain the default."
  }
  assert {
    condition     = length([for env in azurerm_container_app.backend.template[0].container[0].env : env if env.name == "AZURE_DEMO_RESOURCE_GROUP_NAME"]) == 0
    error_message = "Default deployment must not enable retained demo groups."
  }
  assert {
    condition     = local.sso_tenant_id == "11111111-1111-1111-1111-111111111111"
    error_message = "Omitting the external SSO tenant must retain deployment-tenant auth."
  }
  assert {
    condition     = length(azuread_application.sso) == 0 && length(azuread_application_password.sso) == 0
    error_message = "External mode must not create an application or password."
  }
}

run "explicit_platform_group" {
  command = plan
  variables {
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }
  assert {
    condition     = azurerm_container_app_environment.control.infrastructure_resource_group_name == "rg-approved-platform"
    error_message = "The environment must receive the exact explicit infrastructure group name."
  }
}

run "reject_blank_platform_group" {
  command = plan
  variables {
    container_apps_infrastructure_resource_group_name = ""
  }
  expect_failures = [var.container_apps_infrastructure_resource_group_name]
}

run "operator_demo_group_configuration" {
  command = plan
  variables {
    demo_resource_group_name = "rg-retained"
    demo_resource_tags = {
      project   = "owned-test"
      managedBy = "copilot-release"
    }
  }
  assert {
    condition = (
      one([for env in azurerm_container_app.backend.template[0].container[0].env : env.value if env.name == "AZURE_DEMO_RESOURCE_GROUP_NAME"]) == "rg-retained"
      && tomap(jsondecode(one([for env in azurerm_container_app.backend.template[0].container[0].env : env.value if env.name == "AZURE_RESOURCE_TAGS"]))) == var.demo_resource_tags
    )
    error_message = "Backend must receive exact operator-owned demo group and tags."
  }
}

run "external_cross_tenant" {
  command = plan
  variables {
    existing_sso_tenant_id = "abcdefab-abcd-abcd-abcd-abcdefabcdef"
  }
  assert {
    condition = (
      jsondecode(azapi_resource.backend_auth_config[0].body).properties.identityProviders.azureActiveDirectory.registration.openIdIssuer == "https://login.microsoftonline.com/abcdefab-abcd-abcd-abcd-abcdefabcdef/v2.0"
      && jsondecode(azapi_resource.frontend_auth_config[0].body).properties.identityProviders.azureActiveDirectory.registration.openIdIssuer == "https://login.microsoftonline.com/abcdefab-abcd-abcd-abcd-abcdefabcdef/v2.0"
    )
    error_message = "Both real Easy Auth bodies must use the explicit SSO issuer."
  }
  assert {
    condition = (
      one([for env in azurerm_container_app.backend.template[0].container[0].env : env.value if env.name == "AUTH_TENANT_ID"]) == "abcdefab-abcd-abcd-abcd-abcdefabcdef"
      && one([for env in azurerm_container_app.backend.template[0].container[0].env : env.value if env.name == "AZURE_TENANT_ID"]) == "11111111-1111-1111-1111-111111111111"
      && one([for env in azurerm_container_app.backend.template[0].container[0].env : env.value if env.name == "ARM_TENANT_ID"]) == "11111111-1111-1111-1111-111111111111"
    )
    error_message = "Operator tenant must not overwrite backend deployment/internal or ARM tenants."
  }
  assert {
    condition     = length(azuread_application.sso) == 0 && length(azuread_service_principal.sso) == 0 && length(azuread_application_password.sso) == 0
    error_message = "Cross-tenant external auth must not create directory objects or credentials."
  }
}

run "managed_default_unchanged" {
  command = plan
  variables {
    existing_sso_client_id = null
    existing_sso_secret_id = null
  }
  assert {
    condition     = local.sso_tenant_id == "11111111-1111-1111-1111-111111111111" && length(azuread_application.sso) == 1
    error_message = "The existing managed same-tenant path must remain unchanged."
  }
}

run "managed_rejects_foreign_tenant" {
  command = plan
  variables {
    existing_sso_client_id = null
    existing_sso_secret_id = null
    existing_sso_tenant_id = "33333333-3333-3333-3333-333333333333"
  }
  expect_failures = [azurerm_container_app.backend]
}

run "rejects_nontenant_alias" {
  command = plan
  variables {
    existing_sso_tenant_id = "common"
  }
  expect_failures = [var.existing_sso_tenant_id]
}
