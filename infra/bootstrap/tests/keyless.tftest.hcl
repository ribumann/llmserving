mock_provider "azapi" {
  mock_data "azapi_client_config" {
    defaults = {
      tenant_id       = "33333333-3333-3333-3333-333333333333"
      subscription_id = "44444444-4444-4444-4444-444444444444"
    }
  }
  mock_data "azapi_resource" {
    defaults = {
      id       = "/subscriptions/44444444-4444-4444-4444-444444444444/resourceGroups/rg-retained-shared"
      location = "eastus"
    }
  }
}

variables {
  subscription_id              = "44444444-4444-4444-4444-444444444444"
  location                     = "polandcentral"
  existing_resource_group_name = "rg-retained-shared"
  tags = {
    project   = "synthetic-bootstrap-test"
    managedBy = "test-operator"
    target    = "isolated"
    runId     = "synthetic"
    expiresOn = "2099-01-01"
  }
}

run "keyless_security_and_ownership" {
  command = plan

  assert {
    condition     = data.azapi_resource.shared.type == "Microsoft.Resources/resourceGroups@2024-03-01" && data.azapi_resource.shared.parent_id == "/subscriptions/44444444-4444-4444-4444-444444444444" && output.resource_group_name == "rg-retained-shared"
    error_message = "The existing group must be read as data in the explicit subscription."
  }
  assert {
    condition     = azapi_resource.state.parent_id == data.azapi_resource.shared.id
    error_message = "The new account must stay in the data-only retained group."
  }
  assert {
    condition     = azapi_resource.state.location == "polandcentral" && output.location == "polandcentral" && azapi_resource.state.tags == var.tags
    error_message = "Use explicit deployment location and preserve all operator tags, without mutating group metadata."
  }
  assert {
    condition     = azapi_resource.state.type == "Microsoft.Storage/storageAccounts@2023-05-01" && azapi_resource.blobs.type == "Microsoft.Storage/storageAccounts/blobServices@2023-05-01" && azapi_resource.tfstate.type == "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"
    error_message = "Use pinned ARM storage APIs, including management-plane container creation."
  }
  assert {
    condition     = azapi_resource.state.name == "llmstate08ab7e" && azapi_resource.blobs.name == "default" && output.state_storage_account_name == azapi_resource.state.name && output.state_container_name == "tfstate"
    error_message = "Names and outputs must match shared's actual subscription-stage suffix and the tfstate container."
  }
  assert {
    condition     = azapi_resource.state.body.kind == "StorageV2" && azapi_resource.state.body.sku.name == "Standard_LRS"
    error_message = "The minimal state account must use Standard_LRS StorageV2."
  }
  assert {
    condition     = azapi_resource.state.body.properties.supportsHttpsTrafficOnly && azapi_resource.state.body.properties.minimumTlsVersion == "TLS1_2" && !azapi_resource.state.body.properties.allowSharedKeyAccess && azapi_resource.state.body.properties.defaultToOAuthAuthentication
    error_message = "Require HTTPS/TLS 1.2 and OAuth; shared-key access must remain disabled."
  }
  assert {
    condition     = !azapi_resource.state.body.properties.allowBlobPublicAccess && !azapi_resource.state.body.properties.allowCrossTenantReplication && azapi_resource.tfstate.body.properties.publicAccess == "None"
    error_message = "No anonymous/nested public access or cross-tenant replication."
  }
  assert {
    condition     = azapi_resource.state.body.properties.publicNetworkAccess == "Enabled" && azapi_resource.state.body.properties.networkAcls.defaultAction == "Allow" && azapi_resource.state.body.properties.networkAcls.bypass == "None"
    error_message = "The public TLS OAuth endpoint must not require private networking or a trusted-service bypass."
  }
  assert {
    condition     = azapi_resource.state.body.properties.encryption.keySource == "Microsoft.Storage" && azapi_resource.state.body.properties.encryption.services.blob.enabled && azapi_resource.state.body.properties.encryption.services.blob.keyType == "Account"
    error_message = "State blobs must use Microsoft-managed encryption."
  }
  assert {
    condition     = azapi_resource.blobs.body.properties.isVersioningEnabled && azapi_resource.blobs.body.properties.deleteRetentionPolicy.enabled && azapi_resource.blobs.body.properties.deleteRetentionPolicy.days == 7 && azapi_resource.blobs.body.properties.containerDeleteRetentionPolicy.enabled && azapi_resource.blobs.body.properties.containerDeleteRetentionPolicy.days == 7
    error_message = "Require blob versioning and seven-day blob/container recovery."
  }
  assert {
    condition = alltrue([
      for layer, config in output.backend_configs :
      config == {
        use_azuread_auth     = true
        use_oidc             = true
        subscription_id      = var.subscription_id
        tenant_id            = "33333333-3333-3333-3333-333333333333"
        resource_group_name  = var.existing_resource_group_name
        storage_account_name = azapi_resource.state.name
        container_name       = "tfstate"
        key                  = "${layer}.tfstate"
      }
    ]) && toset(keys(output.backend_configs)) == toset(["bootstrap", "shared", "control"])
    error_message = "Backend configs must be exactly the nonsecret OAuth/OIDC fields with three distinct state keys."
  }
  assert {
    condition     = length(azapi_resource.state.response_export_values) == 0 && length(azapi_resource.blobs.response_export_values) == 0 && length(azapi_resource.tfstate.response_export_values) == 0
    error_message = "Do not export management responses or key material."
  }
}

run "maximum_account_length" {
  command = plan
  variables {
    name_prefix = "abcdefghijklm"
    stage       = "release"
  }
  assert {
    condition     = length(output.state_storage_account_name) == 24 && can(regex("^[a-z0-9]{3,24}$", output.state_storage_account_name))
    error_message = "The longest accepted prefix must produce a valid 24-character storage account name."
  }
}

run "reject_blank_group" {
  command = plan
  variables {
    existing_resource_group_name = ""
  }
  expect_failures = [var.existing_resource_group_name]
}

run "reject_group_path" {
  command = plan
  variables {
    existing_resource_group_name = "/subscriptions/foreign/resourceGroups/foreign"
  }
  expect_failures = [var.existing_resource_group_name]
}

run "reject_trailing_period" {
  command = plan
  variables {
    existing_resource_group_name = "rg-retained."
  }
  expect_failures = [var.existing_resource_group_name]
}

run "reject_invalid_subscription" {
  command = plan
  variables {
    subscription_id = "not-a-subscription"
  }
  expect_failures = [var.subscription_id]
}

run "reject_blank_location" {
  command = plan
  variables {
    location = ""
  }
  expect_failures = [var.location]
}

run "reject_invalid_stage" {
  command = plan
  variables {
    stage = "../release"
  }
  expect_failures = [var.stage]
}

run "reject_oversize_prefix" {
  command = plan
  variables {
    name_prefix = "abcdefghijklmn"
  }
  expect_failures = [var.name_prefix]
}

run "reject_non_storage_prefix" {
  command = plan
  variables {
    name_prefix = "llm-release"
  }
  expect_failures = [var.name_prefix]
}

run "source_ownership_and_destroy_guards" {
  command = plan
  assert {
    condition = toset(regexall("(?m)^resource\\s+\"[^\"]+\"\\s+\"[^\"]+\"", join("\n", [
      for filename in fileset(path.module, "*.tf") : file("${path.module}/${filename}")
      ]))) == toset([
      "resource \"azapi_resource\" \"state\"",
      "resource \"azapi_resource\" \"blobs\"",
      "resource \"azapi_resource\" \"tfstate\"",
    ])
    error_message = "Bootstrap may manage only the account, blob service and container, never a group, registry, role or identity."
  }
  assert {
    condition     = can(regex("parent_id\\s*=\\s*azapi_resource.state.id", file("${path.module}/main.tf"))) && can(regex("parent_id\\s*=\\s*azapi_resource.blobs.id", file("${path.module}/main.tf"))) && can(regex("value\\s*=\\s*azapi_resource.state.id", file("${path.module}/outputs.tf")))
    error_message = "Computed child parent IDs and the output must reference the owned resources, not foreign IDs."
  }
  assert {
    condition     = length(regexall("prevent_destroy\\s*=\\s*true", file("${path.module}/main.tf"))) == 3
    error_message = "All three owned storage resources must retain their destruction guards."
  }
}
