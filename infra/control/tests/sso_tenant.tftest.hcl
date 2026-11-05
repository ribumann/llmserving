mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg-retained-control"
      location = "westeurope"
    }
  }
  mock_data "azurerm_role_definition" {
    defaults = {
      id = "/subscriptions/44444444-4444-4444-4444-444444444444/providers/Microsoft.Authorization/roleDefinitions/9980e02c-c2be-4d73-94e8-173b1dc7cf3c"
      permissions = [{
        actions           = ["Microsoft.Network/*/read", "Microsoft.Network/virtualNetworks/subnets/join/action", "Microsoft.Network/networkInterfaces/*", "Microsoft.Compute/virtualMachines/*"]
        not_actions       = []
        data_actions      = []
        not_data_actions  = []
        condition         = ""
        condition_version = ""
      }]
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
      resource_group_name                    = "test"
      gpu_subnet_id                          = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/test/providers/Microsoft.Network/virtualNetworks/test/subnets/gpu"
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
    condition = (
      length(azurerm_resource_group.control) == 1 && length(data.azurerm_resource_group.control) == 0
      && azurerm_role_assignment.backend_contributor["subscription"].role_definition_name == "Contributor"
      && azurerm_role_assignment.terraform_runner_contributor["subscription"].role_definition_name == "Contributor"
      && azurerm_role_assignment.model_deployment_vm_contributor["subscription"].role_definition_name == "Virtual Machine Contributor"
      && alltrue([for role in [
        azurerm_role_assignment.backend_contributor["subscription"],
        azurerm_role_assignment.terraform_runner_contributor["subscription"],
        azurerm_role_assignment.model_deployment_vm_contributor["subscription"]
      ] : role.scope == "/subscriptions/44444444-4444-4444-4444-444444444444"])
      && length(azurerm_role_assignment.runtime_gpu_subnet) == 0
      && length(azurerm_role_assignment.backend_functions_keys) == 0
      && length(azurerm_role_assignment.backend_model_job) == 0
    )
    error_message = "Default managed mode must preserve the old group and subscription role contract."
  }
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

run "retained_control_scopes" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
    tags = {
      project   = "owned-test"
      managedBy = "copilot-release"
    }
  }
  assert {
    condition = (
      length(azurerm_resource_group.control) == 0 && length(data.azurerm_resource_group.control) == 1
      && output.resource_group_name == "rg-retained-control"
      && azurerm_postgresql_flexible_server.control.resource_group_name == "rg-retained-control"
      && azurerm_postgresql_flexible_server.control.location == "polandcentral"
      && azurerm_postgresql_flexible_server.control.tags.managedBy == "copilot-release"
      && azapi_resource.functions_storage.parent_id == data.azurerm_resource_group.control[0].id
      && azapi_resource.tfstate_storage.parent_id == data.azurerm_resource_group.control[0].id
      && azapi_resource.artifacts_storage.parent_id == data.azurerm_resource_group.control[0].id
    )
    error_message = "Retained control must be data-only, preserve operator ownership, and use the shared region."
  }
  assert {
    condition = alltrue([for role in [
      azurerm_role_assignment.backend_contributor["demo"],
      azurerm_role_assignment.terraform_runner_contributor["demo"],
      azurerm_role_assignment.model_deployment_vm_contributor["demo"]
      ] : role.scope == "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg-retained-demo"
      && role.role_definition_name == "Virtual Machine Contributor"
    ])
    error_message = "All three VM actors must have only the explicit demo-group VM role, not subscription Contributor."
  }
  assert {
    condition = (
      azurerm_role_assignment.backend_functions_keys[0].scope == "${local.control_scope_id}/providers/Microsoft.Web/sites/${local.functions_app_name}"
      && azurerm_role_assignment.backend_functions_keys[0].role_definition_name == "Website Contributor"
      && azurerm_role_assignment.backend_model_job[0].scope == "${local.control_scope_id}/providers/Microsoft.App/jobs/llm-job-model-deployment"
      && azurerm_role_assignment.backend_model_job[0].role_definition_name == "Container Apps Jobs Operator"
      && alltrue([for key, role in azurerm_role_assignment.functions_start_job :
        role.scope == "${local.control_scope_id}/providers/Microsoft.App/jobs/${local.job_names[key]}"
        && role.role_definition_name == "Container Apps Jobs Operator"
      ])
    )
    error_message = "Host-key, backend pre-dispatch and Functions dispatch scopes must be exact and known in the plan."
  }
  assert {
    condition = (
      alltrue([for role in azurerm_role_assignment.runtime_gpu_subnet :
        role.scope == local.shared.gpu_subnet_id
        && role.role_definition_id == data.azurerm_role_definition.subnet_vm[0].id
      ])
      && azurerm_role_assignment.backend_tfstate_blob.scope == local.storage_scope_ids.tfstate
      && azurerm_role_assignment.terraform_runner_tfstate_blob.scope == local.storage_scope_ids.tfstate
      && azurerm_role_assignment.backend_artifacts_blob.scope == local.storage_scope_ids.artifacts
      && azurerm_role_assignment.export_worker_artifacts_blob.scope == local.storage_scope_ids.artifacts
      && azurerm_role_assignment.functions_storage_blob.scope == local.storage_scope_ids.functions
      && azurerm_role_assignment.functions_storage_queue.scope == local.storage_scope_ids.functions
      && azurerm_role_assignment.functions_storage_table.scope == local.storage_scope_ids.functions
    )
    error_message = "Subnet and all storage scopes must be exact and known before apply."
  }
}

run "retained_requires_explicit_platform_name" {
  command = plan
  variables {
    existing_resource_group_name = "rg-retained-control"
    demo_resource_group_name     = "rg-retained-demo"
  }
  expect_failures = [azurerm_container_app.backend]
}

run "retained_requires_demo_group" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }
  expect_failures = [azurerm_container_app.backend]
}

run "retained_requires_external_auth" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
    existing_sso_client_id                            = null
    existing_sso_secret_id                            = null
  }
  expect_failures = [azurerm_container_app.backend]
}

run "retained_cannot_disable_easy_auth" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
    enable_sso                                        = false
  }
  expect_failures = [azurerm_container_app.backend]
}

run "retained_rejects_overlapping_groups" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "RG-RETAINED-CONTROL"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }
  expect_failures = [azurerm_container_app.backend]
}

run "retained_rejects_foreign_shared_scope" {
  command = plan
  variables {
    subscription_id                                   = "77777777-7777-7777-7777-777777777777"
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }
  expect_failures = [azurerm_container_app.backend]
}

run "retained_rejects_broad_subnet_role" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }
  override_data {
    target = data.azurerm_role_definition.subnet_vm[0]
    values = {
      permissions = [{
        actions           = ["Microsoft.Network/*"]
        not_actions       = []
        data_actions      = []
        not_data_actions  = []
        condition         = ""
        condition_version = ""
      }]
    }
  }
  expect_failures = [
    azurerm_role_assignment.runtime_gpu_subnet["backend"],
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"]
  ]
}

run "retained_rejects_insufficient_subnet_role" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }
  override_data {
    target = data.azurerm_role_definition.subnet_vm[0]
    values = {
      permissions = [{
        actions           = ["Microsoft.Network/*/read"]
        not_actions       = []
        data_actions      = []
        not_data_actions  = []
        condition         = ""
        condition_version = ""
      }]
    }
  }
  expect_failures = [
    azurerm_role_assignment.runtime_gpu_subnet["backend"],
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"]
  ]
}

run "retained_rejects_conditional_subnet_role" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }
  override_data {
    target = data.azurerm_role_definition.subnet_vm[0]
    values = {
      permissions = [{
        actions           = ["Microsoft.Network/*/read", "Microsoft.Network/virtualNetworks/subnets/join/action"]
        not_actions       = []
        data_actions      = []
        not_data_actions  = []
        condition         = "not proof of unconditional access"
        condition_version = "2.0"
      }]
    }
  }
  expect_failures = [
    azurerm_role_assignment.runtime_gpu_subnet["backend"],
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"]
  ]
}

run "retained_rejects_subnet_denial_metadata" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }
  override_data {
    target = data.azurerm_role_definition.subnet_vm[0]
    values = {
      permissions = [{
        actions           = ["Microsoft.Network/*/read", "Microsoft.Network/virtualNetworks/subnets/join/action"]
        not_actions       = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
        data_actions      = []
        not_data_actions  = []
        condition         = ""
        condition_version = ""
      }]
    }
  }
  expect_failures = [
    azurerm_role_assignment.runtime_gpu_subnet["backend"],
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"]
  ]
}

run "retained_rejects_missing_subnet_metadata" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }
  override_data {
    target = data.azurerm_role_definition.subnet_vm[0]
    values = {
      permissions = []
    }
  }
  expect_failures = [
    azurerm_role_assignment.runtime_gpu_subnet["backend"],
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"]
  ]
}

run "rejects_blank_retained_group" {
  command = plan
  variables {
    existing_resource_group_name = ""
  }
  expect_failures = [var.existing_resource_group_name]
}
