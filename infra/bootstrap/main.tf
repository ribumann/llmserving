locals {
  unique_suffix      = substr(md5("${var.subscription_id}-${var.stage}"), 0, 6)
  state_account_name = "${var.name_prefix}state${local.unique_suffix}"
  container_name     = "tfstate"
  backend_config = {
    use_azuread_auth     = true
    use_oidc             = true
    subscription_id      = var.subscription_id
    tenant_id            = data.azapi_client_config.current.tenant_id
    resource_group_name  = data.azapi_resource.shared.name
    storage_account_name = azapi_resource.state.name
    container_name       = local.container_name
  }
}

data "azapi_client_config" "current" {}

data "azapi_resource" "shared" {
  type                   = "Microsoft.Resources/resourceGroups@2024-03-01"
  name                   = var.existing_resource_group_name
  parent_id              = "/subscriptions/${var.subscription_id}"
  response_export_values = []
}

# All writes use ARM. No storage data-plane provider or listKeys action is needed.
resource "azapi_resource" "state" {
  type                   = "Microsoft.Storage/storageAccounts@2023-05-01"
  name                   = local.state_account_name
  parent_id              = data.azapi_resource.shared.id
  location               = var.location
  tags                   = var.tags
  response_export_values = []

  body = {
    kind = "StorageV2"
    sku  = { name = "Standard_LRS" }
    properties = {
      supportsHttpsTrafficOnly     = true
      minimumTlsVersion            = "TLS1_2"
      allowSharedKeyAccess         = false
      allowBlobPublicAccess        = false
      allowCrossTenantReplication  = false
      defaultToOAuthAuthentication = true
      publicNetworkAccess          = "Enabled"
      networkAcls                  = { bypass = "None", defaultAction = "Allow" }
      encryption = {
        keySource = "Microsoft.Storage"
        services = {
          blob = { enabled = true, keyType = "Account" }
        }
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azapi_resource" "blobs" {
  type                   = "Microsoft.Storage/storageAccounts/blobServices@2023-05-01"
  name                   = "default"
  parent_id              = azapi_resource.state.id
  response_export_values = []

  body = {
    properties = {
      isVersioningEnabled            = true
      deleteRetentionPolicy          = { enabled = true, days = 7 }
      containerDeleteRetentionPolicy = { enabled = true, days = 7 }
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azapi_resource" "tfstate" {
  type                   = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"
  name                   = local.container_name
  parent_id              = azapi_resource.blobs.id
  response_export_values = []

  body = {
    properties = {
      publicAccess = "None"
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
