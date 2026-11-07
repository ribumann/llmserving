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
        actions           = ["Microsoft.Network/virtualNetworks/read", "Microsoft.Network/virtualNetworks/subnets/join/action", "Microsoft.Network/networkInterfaces/*", "Microsoft.Compute/virtualMachines/*"]
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
  target = data.azurerm_role_definition.subnet_reader[0]
  values = {
    id = "/subscriptions/44444444-4444-4444-4444-444444444444/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"
    permissions = [{
      actions           = ["*/read"]
      not_actions       = []
      data_actions      = []
      not_data_actions  = []
      condition         = ""
      condition_version = ""
    }]
  }
}

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
      jsondecode(azapi_resource.frontend_auth_config[0].body).properties.globalValidation.unauthenticatedClientAction == "AllowAnonymous"
      && jsondecode(azapi_resource.frontend_auth_config[0].body).properties.platform.enabled
      && jsondecode(azapi_resource.frontend_auth_config[0].body).properties.identityProviders.azureActiveDirectory.enabled
      && jsondecode(azapi_resource.frontend_auth_config[0].body).properties.identityProviders.azureActiveDirectory.validation.allowedAudiences == [local.sso_client_id]
      && jsondecode(azapi_resource.backend_auth_config[0].body).properties.globalValidation.unauthenticatedClientAction == "RedirectToLoginPage"
      && jsondecode(azapi_resource.backend_auth_config[0].body).properties.globalValidation.excludedPaths == ["/internal/workflows", "/internal/workflows/*"]
      && jsondecode(azapi_resource.backend_auth_config[0].body).properties.platform.enabled
      && one([for env in azurerm_container_app.backend.template[0].container[0].env : env.value if env.name == "AUTH_MODE"]) == "entra-jwt"
    )
    error_message = "Only the static frontend may allow anonymous visitors; frontend SSO and backend EasyAuth/JWT validation must remain enabled."
  }
  assert {
    condition = (
      jsondecode(one([for env in azurerm_container_app.backend.template[0].container[0].env :
      env.value if env.name == "INTERNAL_API_ALLOWED_IDENTITY_RESOURCE_IDS"])) == local.internal_callback_identity_resource_ids
      && length(local.internal_callback_identity_resource_ids) == 6
      && contains(local.internal_callback_identity_resource_ids, local.functions_resource_id)
      && alltrue([for identity in azurerm_user_assigned_identity.jobs :
        contains(local.internal_callback_identity_resource_ids,
      "${local.control_scope_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${identity.name}")])
    )
    error_message = "Callbacks must allow only this deployment's Functions identity and five job identities."
  }
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
      && length(azurerm_role_assignment.runtime_gpu_subnet_reader) == 0
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
  assert {
    condition = (
      length(azurerm_key_vault_secret.database_url) == 0
      && local.database_url_secret_id == "https://isolated-test.vault.azure.net/secrets/database-url"
      && one([for secret in azurerm_container_app.backend.secret : secret.key_vault_secret_id if secret.name == "database-url"]) == local.database_url_secret_id
    )
    error_message = "Default external database secret seeding and backend reference must remain unchanged."
  }
  assert {
    condition = (
      length(azapi_resource.functions_packages) == 0
      && output.functions_package_blob_url == null
      && !contains(keys(azurerm_linux_function_app.orchestrator.app_settings), "WEBSITE_RUN_FROM_PACKAGE")
    )
    error_message = "Omitted Functions package digest must preserve legacy deployment settings."
  }
}

run "private_digest_functions_package" {
  command = plan
  variables {
    functions_package_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  assert {
    condition = (
      length(azapi_resource.functions_packages) == 1
      && azapi_resource.functions_packages[0].name == "functions-packages"
      && jsondecode(azapi_resource.functions_packages[0].body).properties.publicAccess == "None"
      && azurerm_linux_function_app.orchestrator.storage_uses_managed_identity
      && azurerm_linux_function_app.orchestrator.app_settings.WEBSITE_RUN_FROM_PACKAGE == "https://${azapi_resource.functions_storage.name}.blob.core.windows.net/functions-packages/functions-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.zip"
      && azurerm_linux_function_app.orchestrator.app_settings.WEBSITE_RUN_FROM_PACKAGE_BLOB_MI_RESOURCE_ID == "SystemAssigned"
      && !contains(keys(azurerm_linux_function_app.orchestrator.app_settings), "WEBSITE_CONTENTAZUREFILECONNECTIONSTRING")
      && !azurerm_linux_function_app.orchestrator.webdeploy_publish_basic_authentication_enabled
    )
    error_message = "Keyless Premium Functions must run the exact private digest-named ZIP using the existing host identity, not Azure Files or basic-auth ZIP publishing."
  }
}

run "reject_mutable_functions_package" {
  command = plan
  variables {
    functions_package_sha256 = "latest"
  }
  expect_failures = [var.functions_package_sha256]
}

run "private_executor_seeds_database_url" {
  command = plan
  variables {
    manage_database_url_secret = true
    database_admin_password    = "synthetic-password-not-a-credential"
  }
  assert {
    condition = (
      length(azurerm_key_vault_secret.database_url) == 1
      && azurerm_key_vault_secret.database_url[0].name == "database-url"
      && azurerm_key_vault_secret.database_url[0].key_vault_id == local.shared.key_vault_id
    )
    error_message = "Opted-in private execution must manage exactly the database URL secret in the shared vault."
  }
  assert {
    condition = (
      length(azuread_application.sso) == 0
      && length(azuread_application_password.sso) == 0
      && length(azurerm_key_vault_secret.sso_client_secret) == 0
    )
    error_message = "Database seeding must not change external SSO ownership."
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
  assert {
    condition = (
      length(var.additional_frontend_sso_redirect_uris) == 0
      && length(local.sso_redirect_uris) == 2
    )
    error_message = "Default managed SSO must retain exactly the generated frontend and backend callbacks."
  }
}

run "managed_additional_frontend_callbacks" {
  command = plan
  variables {
    existing_sso_client_id                = null
    existing_sso_secret_id                = null
    additional_frontend_sso_redirect_uris = ["https://ui.example.com/.auth/login/aad/callback", "https://demo.example.org/.auth/login/aad/callback"]
  }
  assert {
    condition = (
      length(local.sso_redirect_uris) == 4
      && tolist(slice(local.sso_redirect_uris, 2, 4)) == var.additional_frontend_sso_redirect_uris
    )
    error_message = "Managed SSO must add the approved frontend callbacks without removing either generated callback."
  }
}

run "reject_unsafe_frontend_callbacks" {
  command = plan
  variables {
    additional_frontend_sso_redirect_uris = ["http://ui.example.com/.auth/login/aad/callback"]
  }
  expect_failures = [var.additional_frontend_sso_redirect_uris]
}

run "reject_frontend_callback_credentials" {
  command = plan
  variables {
    additional_frontend_sso_redirect_uris = ["https://user@ui.example.com/.auth/login/aad/callback"]
  }
  expect_failures = [var.additional_frontend_sso_redirect_uris]
}

run "reject_frontend_callback_query" {
  command = plan
  variables {
    additional_frontend_sso_redirect_uris = ["https://ui.example.com/.auth/login/aad/callback?next=evil"]
  }
  expect_failures = [var.additional_frontend_sso_redirect_uris]
}

run "reject_frontend_callback_wrong_path" {
  command = plan
  variables {
    additional_frontend_sso_redirect_uris = ["https://ui.example.com/other"]
  }
  expect_failures = [var.additional_frontend_sso_redirect_uris]
}

run "reject_frontend_callback_port" {
  command = plan
  variables {
    additional_frontend_sso_redirect_uris = ["https://ui.example.com:443/.auth/login/aad/callback"]
  }
  expect_failures = [var.additional_frontend_sso_redirect_uris]
}

run "reject_frontend_callback_fragment" {
  command = plan
  variables {
    additional_frontend_sso_redirect_uris = ["https://ui.example.com/.auth/login/aad/callback#fragment"]
  }
  expect_failures = [var.additional_frontend_sso_redirect_uris]
}

run "reject_frontend_callback_invalid_hostname" {
  command = plan
  variables {
    additional_frontend_sso_redirect_uris = ["https://-bad.example.com/.auth/login/aad/callback"]
  }
  expect_failures = [var.additional_frontend_sso_redirect_uris]
}

run "reject_frontend_callback_null" {
  command = plan
  variables {
    additional_frontend_sso_redirect_uris = [null]
  }
  expect_failures = [var.additional_frontend_sso_redirect_uris]
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
      && length(azurerm_role_assignment.runtime_gpu_subnet_reader) == 2
      && keys(azurerm_role_assignment.runtime_gpu_subnet_reader) == keys(azurerm_role_assignment.runtime_gpu_subnet)
      && alltrue([for role in azurerm_role_assignment.runtime_gpu_subnet_reader :
        role.scope == local.shared.gpu_subnet_id
        && role.role_definition_id == data.azurerm_role_definition.subnet_reader[0].id
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
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["backend"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["terraform_runner"]
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
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["backend"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["terraform_runner"]
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
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["backend"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["terraform_runner"]
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
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["backend"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["terraform_runner"]
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
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["backend"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["terraform_runner"]
  ]
}

run "rejects_blank_retained_group" {
  command = plan
  variables {
    existing_resource_group_name = ""
  }
  expect_failures = [var.existing_resource_group_name]
}

run "release_job_names_preserve_valid_names_and_shorten_only_overlong_names" {
  command = plan
  variables {
    name_prefix = "llmexample"
  }
  assert {
    condition = (
      alltrue([for name in values(local.job_names) :
        length(name) <= 32 && can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", name))
      ])
      && length(toset(values(local.job_names))) == length(local.jobs)
      && local.job_names["performance_worker"] == "llmexample-job-performa-${substr(sha256("llmexample-job-performance-worker"), 0, 8)}"
      && alltrue([for key, name in local.full_job_names :
        key == "performance_worker" || local.job_names[key] == name
      ])
      && azurerm_container_app.backend.name == "llmexample-backend"
      && azurerm_container_app.frontend.name == "llmexample-frontend"
      && alltrue([for key, job in azurerm_container_app_job.jobs : job.name == local.job_names[key]])
      && alltrue([for key, scope in local.job_scope_ids :
        scope == "${local.control_scope_id}/providers/Microsoft.App/jobs/${local.job_names[key]}"
      ])
    )
    error_message = "ACA jobs must fit 32 characters with a stable full-name hash, preserving all valid names, app callbacks and shared dispatch/RBAC references."
  }
}

run "retained_rejects_reader_with_subnet_write" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }
  override_data {
    target = data.azurerm_role_definition.subnet_reader[0]
    values = {
      permissions = [{
        actions           = ["*/read", "Microsoft.Network/virtualNetworks/subnets/write"]
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
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["backend"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["terraform_runner"]
  ]
}

run "retained_requires_subnet_read_from_reader" {
  command = plan
  variables {
    existing_resource_group_name                      = "rg-retained-control"
    demo_resource_group_name                          = "rg-retained-demo"
    container_apps_infrastructure_resource_group_name = "rg-approved-platform"
  }

  override_data {
    target = data.azurerm_role_definition.subnet_reader[0]
    values = {
      permissions = [{
        actions           = ["Microsoft.Network/virtualNetworks/read"]
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
    azurerm_role_assignment.runtime_gpu_subnet["terraform_runner"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["backend"],
    azurerm_role_assignment.runtime_gpu_subnet_reader["terraform_runner"]
  ]
}

run "frontend_token_store_container_precedes_secret_bootstrap" {
  command = plan
  assert {
    condition = (
      length(azapi_resource.frontend_auth_tokens) == 1
      && azapi_resource.frontend_auth_tokens[0].name == "frontend-auth-tokens"
      && jsondecode(azapi_resource.frontend_auth_tokens[0].body).properties.publicAccess == "None"
      && !contains(keys(jsondecode(azapi_resource.frontend_auth_config[0].body).properties), "login")
      && length([for secret in azurerm_container_app.frontend.secret : secret if secret.name == "frontend-token-store-sas"]) == 0
    )
    error_message = "The initial full plan must create a private token container without requiring an unseeded SAS secret."
  }
}

run "frontend_token_store_relays_signed_token_without_backend_auth_changes" {
  command = plan
  variables {
    frontend_token_store_sas_secret_id = "https://isolated-test.vault.azure.net/secrets/frontend-token-store-sas"
  }
  assert {
    condition = (
      azapi_resource.frontend_auth_config[0].type == "Microsoft.App/containerApps/authConfigs@2024-03-01"
      && jsondecode(azapi_resource.frontend_auth_config[0].body).properties.login.tokenStore.enabled
      && jsondecode(azapi_resource.frontend_auth_config[0].body).properties.login.tokenStore.azureBlobStorage.sasUrlSettingName == "frontend-token-store-sas"
      && one([for secret in azurerm_container_app.frontend.secret : secret.key_vault_secret_id if secret.name == "frontend-token-store-sas"]) == var.frontend_token_store_sas_secret_id
      && jsondecode(azapi_resource.frontend_auth_config[0].body).properties.globalValidation.unauthenticatedClientAction == "AllowAnonymous"
      && jsondecode(azapi_resource.frontend_auth_config[0].body).properties.platform.enabled
      && jsondecode(azapi_resource.frontend_auth_config[0].body).properties.identityProviders.azureActiveDirectory.enabled
      && jsondecode(azapi_resource.frontend_auth_config[0].body).properties.identityProviders.azureActiveDirectory.validation.allowedAudiences == [local.sso_client_id]
      && !contains(keys(jsondecode(azapi_resource.backend_auth_config[0].body).properties), "login")
      && jsondecode(azapi_resource.backend_auth_config[0].body).properties.globalValidation.unauthenticatedClientAction == "RedirectToLoginPage"
      && jsondecode(azapi_resource.backend_auth_config[0].body).properties.platform.enabled
      && one([for env in azurerm_container_app.backend.template[0].container[0].env : env.value if env.name == "AUTH_MODE"]) == "entra-jwt"
    )
    error_message = "The public frontend shell must retain signed-token relay and SSO using a vault reference, while backend Easy Auth and independent JWT validation remain required."
  }
}

run "frontend_token_store_rejects_foreign_vault" {
  command = plan
  variables {
    frontend_token_store_sas_secret_id = "https://foreign.vault.azure.net/secrets/frontend-token-store-sas"
  }
  expect_failures = [azurerm_container_app.frontend]
}

run "frontend_token_store_rejects_raw_sas_input" {
  command = plan
  variables {
    frontend_token_store_sas_secret_id = "https://synthetic.blob.core.windows.net/frontend-auth-tokens?sig=synthetic"
  }
  expect_failures = [var.frontend_token_store_sas_secret_id]
}
