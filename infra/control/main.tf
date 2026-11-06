# infra/control: the persistent application control plane (rg-llm-control-{stage}) beneath the
# Baseline Azure Pilot Architecture (specs/001-llm-serving-demo/plan.md Target Platform,
# research.md Section 7, spec.md FR-074-FR-090).
#
# Owns: the Container Apps environment + backend/frontend Container Apps (React + FastAPI,
# Entra ID SSO — FR-075), the 5 Container Apps Job *definitions* dispatched by Durable Functions
# (FR-078), the Durable Functions orchestration app (FR-076/FR-077), private-access PostgreSQL,
# and the storage/identities/RBAC/alerts that support them. Applied once per stage, after
# infra/shared. Never touched by a per-environment infra/demo apply (FR-090).

data "terraform_remote_state" "shared" {
  backend = "local"
  config = {
    path = var.shared_state_path
  }
}

data "azurerm_client_config" "current" {}

locals {
  shared              = data.terraform_remote_state.shared.outputs
  retained_group      = var.existing_resource_group_name != null
  resource_group_name = local.retained_group ? data.azurerm_resource_group.control[0].name : azurerm_resource_group.control[0].name
  resource_group_id   = local.retained_group ? data.azurerm_resource_group.control[0].id : azurerm_resource_group.control[0].id
  control_scope_id    = "/subscriptions/${var.subscription_id}/resourceGroups/${local.resource_group_name}"
  location            = local.shared.location
  unique_suffix       = substr(md5("${var.subscription_id}-${var.stage}-control"), 0, 6)
  manage_sso          = var.enable_sso && var.existing_sso_client_id == null
  sso_client_id       = local.manage_sso ? azuread_application.sso[0].client_id : var.existing_sso_client_id
  sso_secret_id       = local.manage_sso ? azurerm_key_vault_secret.sso_client_secret[0].versionless_id : var.existing_sso_secret_id
  sso_tenant_id       = var.existing_sso_tenant_id == null ? data.azurerm_client_config.current.tenant_id : lower(var.existing_sso_tenant_id)

  common_tags = merge(var.tags, {
    feature   = "azure-llm-serving-demo"
    component = "control"
    stage     = var.stage
    managedBy = local.retained_group ? lookup(var.tags, "managedBy", "terraform") : "terraform"
  })

  # Placeholder image tags before the first `az acr build` push, mirroring the superseded
  # infra/app-host module's bring-up order (image pull failures are expected until then).
  backend_image  = coalesce(var.backend_image, "${local.shared.acr_login_server}/llmserving-backend:latest")
  frontend_image = coalesce(var.frontend_image, "${local.shared.acr_login_server}/llmserving-frontend:latest")

  terraform_runner_image   = coalesce(var.terraform_runner_image, "${local.shared.acr_login_server}/llmserving-terraform-runner:latest")
  model_deployment_image   = coalesce(var.model_deployment_image, "${local.shared.acr_login_server}/llmserving-model-deployment:latest")
  evaluation_worker_image  = coalesce(var.evaluation_worker_image, "${local.shared.acr_login_server}/llmserving-evaluation-worker:latest")
  performance_worker_image = coalesce(var.performance_worker_image, "${local.shared.acr_login_server}/llmserving-performance-worker:latest")
  export_worker_image      = coalesce(var.export_worker_image, "${local.shared.acr_login_server}/llmserving-export-worker:latest")
}

moved {
  from = azurerm_resource_group.control
  to   = azurerm_resource_group.control[0]
}

data "azurerm_resource_group" "control" {
  count = local.retained_group ? 1 : 0
  name  = var.existing_resource_group_name
}

resource "azurerm_resource_group" "control" {
  count    = local.retained_group ? 0 : 1
  name     = "rg-llm-control-${var.stage}"
  location = local.location
  tags     = local.common_tags
}

# --- PostgreSQL (private access via VNet Integration into snet-data; FR-081/FR-085) ---

resource "random_password" "db_admin" {
  count   = var.database_admin_password == null ? 1 : 0
  length  = 24
  special = false
}

locals {
  db_admin_password = coalesce(var.database_admin_password, try(random_password.db_admin[0].result, null))
}

resource "azurerm_postgresql_flexible_server" "control" {
  name                = "${var.name_prefix}-control-pg-${local.unique_suffix}"
  resource_group_name = local.resource_group_name
  location            = local.location
  tags                = local.common_tags

  version    = var.postgres_version
  sku_name   = var.postgres_sku_name
  storage_mb = var.postgres_storage_mb

  administrator_login    = var.database_admin_user
  administrator_password = local.db_admin_password

  delegated_subnet_id           = local.shared.data_subnet_id
  private_dns_zone_id           = local.shared.postgres_private_dns_zone_id
  public_network_access_enabled = false

  backup_retention_days        = 7
  geo_redundant_backup_enabled = false

  lifecycle {
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.control.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

locals {
  database_url = "postgresql+psycopg://${var.database_admin_user}:${local.db_admin_password}@${azurerm_postgresql_flexible_server.control.fqdn}:5432/${var.database_name}?sslmode=require"

  # Private execution can seed the URL within the full apply's graph. The default retains
  # external seeding for executors that cannot reach the private vault data plane.
  database_url_secret_id = var.manage_database_url_secret ? azurerm_key_vault_secret.database_url[0].versionless_id : "${trimsuffix(local.shared.key_vault_uri, "/")}/secrets/database-url"
}

resource "azurerm_key_vault_secret" "database_url" {
  count = var.manage_database_url_secret ? 1 : 0

  name         = "database-url"
  value        = local.database_url
  key_vault_id = local.shared.key_vault_id

  depends_on = [azurerm_postgresql_flexible_server_database.app]
}

# --- Storage accounts (Functions task-hub state, Terraform remote state, exports/artifacts) ---
# All three are private-endpoint-only. Access is via managed identity + RBAC,
# not account keys.
#
# Provisioned via azapi_resource rather than azurerm_storage_account: the azurerm provider polls
# each storage account's data-plane blob endpoint right after creation to confirm it's "ready"
# (https://github.com/hashicorp/terraform-provider-azurerm/issues/32474), and that poll always
# fails here — the account has no network path (public access disabled,
# private endpoints not created yet at that point in the graph) and no account keys
# (shared_access_key_enabled = false). azapi only calls the ARM control plane, so it never hits
# that data-plane check.

resource "azapi_resource" "functions_storage" {
  type      = "Microsoft.Storage/storageAccounts@2023-01-01"
  name      = "${replace(var.name_prefix, "-", "")}func${local.unique_suffix}"
  parent_id = local.resource_group_id
  location  = local.location
  tags      = local.common_tags

  body = jsonencode({
    sku  = { name = "Standard_LRS" }
    kind = "StorageV2"
    properties = {
      minimumTlsVersion     = "TLS1_2"
      allowSharedKeyAccess  = false
      publicNetworkAccess   = "Disabled"
      allowBlobPublicAccess = false
      networkAcls           = { defaultAction = "Deny" }
    }
  })

  response_export_values = ["*"]
}

resource "azapi_resource" "functions_packages" {
  count = var.functions_package_sha256 == null ? 0 : 1

  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01"
  name      = "functions-packages"
  parent_id = "${azapi_resource.functions_storage.id}/blobServices/default"

  body = jsonencode({
    properties = { publicAccess = "None" }
  })
}

resource "azapi_resource" "frontend_auth_tokens" {
  count = var.enable_sso ? 1 : 0

  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01"
  name      = "frontend-auth-tokens"
  parent_id = "${azapi_resource.functions_storage.id}/blobServices/default"

  body = jsonencode({
    properties = { publicAccess = "None" }
  })
}

resource "azapi_resource" "tfstate_storage" {
  type      = "Microsoft.Storage/storageAccounts@2023-01-01"
  name      = "${replace(var.name_prefix, "-", "")}tfstate${local.unique_suffix}"
  parent_id = local.resource_group_id
  location  = local.location
  tags      = local.common_tags

  body = jsonencode({
    sku  = { name = "Standard_LRS" }
    kind = "StorageV2"
    properties = {
      minimumTlsVersion     = "TLS1_2"
      allowSharedKeyAccess  = false
      publicNetworkAccess   = "Disabled"
      allowBlobPublicAccess = false
      networkAcls           = { defaultAction = "Deny" }
    }
  })

  response_export_values = ["*"]
}

resource "azapi_resource" "tfstate_container" {
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01"
  name      = "tfstate"
  parent_id = "${azapi_resource.tfstate_storage.id}/blobServices/default"

  body = jsonencode({
    properties = { publicAccess = "None" }
  })
}

resource "azapi_resource" "artifacts_storage" {
  type      = "Microsoft.Storage/storageAccounts@2023-01-01"
  name      = "${replace(var.name_prefix, "-", "")}art${local.unique_suffix}"
  parent_id = local.resource_group_id
  location  = local.location
  tags      = local.common_tags

  body = jsonencode({
    sku  = { name = "Standard_LRS" }
    kind = "StorageV2"
    properties = {
      minimumTlsVersion     = "TLS1_2"
      allowSharedKeyAccess  = false
      publicNetworkAccess   = "Disabled"
      allowBlobPublicAccess = false
      networkAcls           = { defaultAction = "Deny" }
    }
  })

  response_export_values = ["*"]
}

resource "azapi_resource" "exports_container" {
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01"
  name      = "exports"
  parent_id = "${azapi_resource.artifacts_storage.id}/blobServices/default"

  body = jsonencode({
    properties = { publicAccess = "None" }
  })
}

resource "azurerm_private_endpoint" "functions_blob" {
  name                = "${var.name_prefix}-func-blob-pe"
  resource_group_name = local.resource_group_name
  location            = local.location
  subnet_id           = local.shared.private_endpoints_subnet_id
  tags                = local.common_tags

  private_service_connection {
    name                           = "${var.name_prefix}-func-blob-psc"
    private_connection_resource_id = azapi_resource.functions_storage.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "blob-zone-group"
    private_dns_zone_ids = [local.shared.blob_private_dns_zone_id]
  }
}

resource "azurerm_private_endpoint" "functions_queue" {
  name                = "${var.name_prefix}-func-queue-pe"
  resource_group_name = local.resource_group_name
  location            = local.location
  subnet_id           = local.shared.private_endpoints_subnet_id
  tags                = local.common_tags

  private_service_connection {
    name                           = "${var.name_prefix}-func-queue-psc"
    private_connection_resource_id = azapi_resource.functions_storage.id
    subresource_names              = ["queue"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "queue-zone-group"
    private_dns_zone_ids = [local.shared.queue_private_dns_zone_id]
  }
}

resource "azurerm_private_endpoint" "functions_table" {
  name                = "${var.name_prefix}-func-table-pe"
  resource_group_name = local.resource_group_name
  location            = local.location
  subnet_id           = local.shared.private_endpoints_subnet_id
  tags                = local.common_tags

  private_service_connection {
    name                           = "${var.name_prefix}-func-table-psc"
    private_connection_resource_id = azapi_resource.functions_storage.id
    subresource_names              = ["table"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "table-zone-group"
    private_dns_zone_ids = [local.shared.table_private_dns_zone_id]
  }
}

resource "azurerm_private_endpoint" "tfstate" {
  name                = "${var.name_prefix}-tfstate-pe"
  resource_group_name = local.resource_group_name
  location            = local.location
  subnet_id           = local.shared.private_endpoints_subnet_id
  tags                = local.common_tags

  private_service_connection {
    name                           = "${var.name_prefix}-tfstate-psc"
    private_connection_resource_id = azapi_resource.tfstate_storage.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "blob-zone-group"
    private_dns_zone_ids = [local.shared.blob_private_dns_zone_id]
  }
}

resource "azurerm_private_endpoint" "artifacts" {
  name                = "${var.name_prefix}-artifacts-pe"
  resource_group_name = local.resource_group_name
  location            = local.location
  subnet_id           = local.shared.private_endpoints_subnet_id
  tags                = local.common_tags

  private_service_connection {
    name                           = "${var.name_prefix}-artifacts-psc"
    private_connection_resource_id = azapi_resource.artifacts_storage.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "blob-zone-group"
    private_dns_zone_ids = [local.shared.blob_private_dns_zone_id]
  }
}

# --- Container Apps environment ---

resource "azurerm_container_app_environment" "control" {
  name                               = "${var.name_prefix}-cae"
  resource_group_name                = local.resource_group_name
  location                           = local.location
  log_analytics_workspace_id         = local.shared.log_analytics_workspace_id
  infrastructure_subnet_id           = local.shared.container_apps_subnet_id
  infrastructure_resource_group_name = var.container_apps_infrastructure_resource_group_name
  tags                               = local.common_tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  # Azure auto-populates infrastructure_resource_group_name when it's left unset. Ignore drift
  # on it so terraform doesn't force-replace the whole environment (and everything inside it)
  # on every subsequent plan.
  lifecycle {
    ignore_changes = [infrastructure_resource_group_name]

    postcondition {
      condition = var.container_apps_infrastructure_resource_group_name == null ? true : (
        self.infrastructure_resource_group_name == null ? false :
        lower(self.infrastructure_resource_group_name) == lower(var.container_apps_infrastructure_resource_group_name)
      )
      error_message = "The platform infrastructure group does not match the explicitly approved name. Existing environments are not automatically replaced or moved."
    }
  }
}

# --- Backend Container App (FastAPI) ---

# User-assigned (rather than system-assigned) identity for the backend: this breaks a real
# bootstrap circular dependency. Azure provisions a Container App's first revision synchronously
# as part of the create/update call, and that requires AcrPull (and Key Vault secret access) to
# already be in effect — but a system-assigned identity's principal_id doesn't exist until that
# same call returns, so Terraform could never grant the RBAC in time and every apply failed with
# "Operation expired" (confirmed empirically: two consecutive ~19min timeouts before switching to
# this pattern). A user-assigned identity exists independently, so its RBAC can be (and is, below)
# fully granted before the Container App is ever created.
resource "azurerm_user_assigned_identity" "backend" {
  name                = "${var.name_prefix}-backend-id"
  resource_group_name = local.resource_group_name
  location            = local.location
  tags                = local.common_tags
}

resource "azurerm_container_app" "backend" {
  name                         = "${var.name_prefix}-backend"
  resource_group_name          = local.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.control.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.common_tags

  # Waits for the backend's own RBAC (AcrPull, Key Vault Secrets User) to actually propagate,
  # not just for Terraform to have issued the grant — see time_sleep.backend_rbac_propagation.
  depends_on = [time_sleep.backend_rbac_propagation]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.backend.id]
  }

  registry {
    server   = local.shared.acr_login_server
    identity = azurerm_user_assigned_identity.backend.id
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  # Key Vault-backed secrets, resolved via the Container App's own user-assigned identity
  # (granted Key Vault Secrets User below) rather than passing raw values as plain env vars
  # (FR-081/FR-085 secret hygiene).
  secret {
    name                = "database-url"
    key_vault_secret_id = local.database_url_secret_id
    identity            = azurerm_user_assigned_identity.backend.id
  }

  dynamic "secret" {
    for_each = var.enable_sso ? [1] : []
    content {
      name                = "sso-client-secret"
      key_vault_secret_id = local.sso_secret_id
      identity            = azurerm_user_assigned_identity.backend.id
    }
  }

  template {
    min_replicas = var.backend_min_replicas
    max_replicas = var.backend_max_replicas

    container {
      name   = "backend"
      image  = local.backend_image
      cpu    = var.backend_cpu
      memory = var.backend_memory

      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/healthz"
      }
      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/readyz"
      }

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name  = "APP_ENV"
        value = "production"
      }
      env {
        name  = "AUTH_MODE"
        value = "entra-jwt"
      }
      env {
        name  = "AUTH_AUDIENCE"
        value = local.sso_client_id
      }
      env {
        name  = "AUTH_TENANT_ID"
        value = local.sso_tenant_id
      }
      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = var.subscription_id
      }
      # Required for azure-identity's DefaultAzureCredential (used throughout backend/src,
      # e.g. providers/azure/preview.py, container_jobs.py, functions_client.py) to resolve
      # ManagedIdentityCredential correctly: this identity is user-assigned (see
      # azurerm_user_assigned_identity.backend above), and without an explicit client ID,
      # ManagedIdentityCredential only looks for a system-assigned identity and fails with
      # "Unable to load the proper Managed Identity" at call time.
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.backend.client_id
      }
      env {
        name  = "ARM_USE_MSI"
        value = "true"
      }
      env {
        name  = "ARM_SUBSCRIPTION_ID"
        value = var.subscription_id
      }
      env {
        name  = "ARM_TENANT_ID"
        value = data.azurerm_client_config.current.tenant_id
      }
      # Terraform's azurerm provider also needs an explicit client ID for MSI auth against a
      # user-assigned identity (mirrors AZURE_CLIENT_ID's rationale above, ARM_* naming is
      # Terraform's own convention).
      env {
        name  = "ARM_CLIENT_ID"
        value = azurerm_user_assigned_identity.backend.client_id
      }
      env {
        name  = "AZURE_TENANT_ID"
        value = data.azurerm_client_config.current.tenant_id
      }
      env {
        name  = "INTERNAL_API_AUDIENCE"
        value = local.internal_api_audience
      }
      env {
        name  = "TF_STATE_STORAGE_ACCOUNT"
        value = azapi_resource.tfstate_storage.name
      }
      env {
        name  = "TF_STATE_CONTAINER"
        value = azapi_resource.tfstate_container.name
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = local.shared.application_insights_connection_string
      }
      env {
        name  = "AUTH_ALLOWED_EMAIL_DOMAINS"
        value = var.auth_allowed_email_domains
      }
      env {
        name  = "AUTH_BYPASS_PATHS"
        value = var.auth_bypass_paths
      }
      env {
        name  = "CORS_ALLOWED_ORIGINS"
        value = "https://${local.frontend_fqdn}"
      }

      # T140: lets AzureProviderAdapter start/cancel Orchestration Workflows on the Durable
      # Functions app (functions/function_app.py's http_start/raise_cancel_event). Retained mode
      # uses Website Contributor at that exact site; legacy mode uses subscription Contributor.
      # Both grant Microsoft.Web/sites/host/listkeys/action, so the backend can
      # fetch this Function App's own function key via the ARM control plane
      # (POST {id}/host/default/listkeys) using its ordinary ARM-audience managed-identity
      # token, then present that key as the function key on the actual HTTP call - no secret is
      # ever stored in Key Vault or as a plain env var, and no Entra app registration is needed
      # (matches the constraint documented at local.internal_api_audience, above).
      env {
        name  = "ORCHESTRATION_FUNCTIONS_URL"
        value = "https://${local.functions_fqdn}/api"
      }
      env {
        name  = "ORCHESTRATION_FUNCTIONS_RESOURCE_ID"
        value = local.functions_resource_id
      }

      # T140: lets AzureDeployer pre-dispatch the model_deployment Container Apps Job
      # directly (with the real HF credential as a one-off env override) before starting
      # the Durable Functions orchestration that only monitors it - see
      # functions_client.py/container_jobs.py's module docstrings for why `deploy` is the
      # one workflow type FastAPI dispatches itself instead of via dispatch_job.
      env {
        name  = "CONTAINER_APPS_RESOURCE_GROUP"
        value = local.resource_group_name
      }
      env {
        name  = "JOB_NAME_MODEL_DEPLOYMENT"
        value = local.job_names["model_deployment"]
      }
      dynamic "env" {
        for_each = var.demo_resource_group_name == null ? [] : [var.demo_resource_group_name]
        content {
          name  = "AZURE_DEMO_RESOURCE_GROUP_NAME"
          value = env.value
        }
      }
      env {
        name  = "AZURE_RESOURCE_TAGS"
        value = jsonencode(var.demo_resource_tags)
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
    precondition {
      condition = !local.retained_group || (
        var.demo_resource_group_name != null
        && var.enable_sso
        && var.existing_sso_client_id != null
        && var.existing_sso_secret_id != null
        && var.container_apps_infrastructure_resource_group_name != null
      )
      error_message = "Retained control groups require a retained demo group, external SSO with Easy Auth enabled, and an explicitly approved platform infrastructure group name."
    }
    precondition {
      condition = !local.retained_group ? true : (
        length(distinct([for name in [
          var.existing_resource_group_name, var.demo_resource_group_name,
          local.shared.resource_group_name, var.container_apps_infrastructure_resource_group_name
        ] : lower(name) if name != null])) == 4
        && alltrue([for id in local.shared_scope_ids :
          startswith(lower(id), lower("/subscriptions/${var.subscription_id}/resourceGroups/${local.shared.resource_group_name}/providers/"))
        ])
      )
      error_message = "Retained control, shared, demo and platform groups must be distinct; shared resource IDs must belong to the selected subscription and shared group."
    }
    precondition {
      condition     = (var.existing_sso_client_id == null) == (var.existing_sso_secret_id == null)
      error_message = "Supply both existing_sso_client_id and existing_sso_secret_id, or neither."
    }
    precondition {
      condition     = var.existing_sso_tenant_id == null || var.existing_sso_client_id != null
      error_message = "An explicit SSO tenant requires an externally approved application; managed SSO uses the deployment tenant."
    }
    precondition {
      condition     = var.enable_sso || var.existing_sso_client_id != null
      error_message = "Cloud operator authentication requires managed SSO or an external application; disabling SSO is not an authentication bypass."
    }
    precondition {
      condition     = var.existing_sso_secret_id == null ? true : startswith(var.existing_sso_secret_id, "${trimsuffix(local.shared.key_vault_uri, "/")}/secrets/")
      error_message = "The external SSO credential reference must point to the isolated shared layer's Key Vault."
    }
  }
}

# --- Frontend Container App (React) ---

# See azurerm_user_assigned_identity.backend above for why this is user-assigned rather than
# system-assigned: it lets AcrPull (and, when SSO is enabled, Key Vault Secrets User) be granted
# before this resource is created, avoiding the same bootstrap circular dependency.
resource "azurerm_user_assigned_identity" "frontend" {
  name                = "${var.name_prefix}-frontend-id"
  resource_group_name = local.resource_group_name
  location            = local.location
  tags                = local.common_tags
}

resource "azurerm_container_app" "frontend" {
  name                         = "${var.name_prefix}-frontend"
  resource_group_name          = local.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.control.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.common_tags

  # See azurerm_container_app.backend's identical depends_on for why this waits on RBAC
  # propagation, not just the role assignment write.
  depends_on = [time_sleep.frontend_rbac_propagation]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.frontend.id]
  }

  registry {
    server   = local.shared.acr_login_server
    identity = azurerm_user_assigned_identity.frontend.id
  }

  ingress {
    external_enabled = true
    target_port      = 80
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  # Needed by this app's own authConfig (below): Container Apps' Easy Auth resolves
  # clientSecretSettingName against a secret defined on the *same* container app. Only wired
  # when SSO is enabled (var.enable_sso) — see azuread_application.sso and
  # azurerm_key_vault_secret.sso_client_secret.
  dynamic "secret" {
    for_each = var.enable_sso ? [1] : []
    content {
      name                = "sso-client-secret"
      key_vault_secret_id = local.sso_secret_id
      identity            = azurerm_user_assigned_identity.frontend.id
    }
  }

  dynamic "secret" {
    for_each = var.enable_sso && var.frontend_token_store_sas_secret_id != null ? [1] : []
    content {
      name                = "frontend-token-store-sas"
      key_vault_secret_id = var.frontend_token_store_sas_secret_id
      identity            = azurerm_user_assigned_identity.frontend.id
    }
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "frontend"
      image  = local.frontend_image
      cpu    = var.frontend_cpu
      memory = var.frontend_memory

      env {
        name  = "BACKEND_URL"
        value = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
    precondition {
      condition = var.frontend_token_store_sas_secret_id == null ? true : (
        var.enable_sso && startswith(var.frontend_token_store_sas_secret_id, "${trimsuffix(local.shared.key_vault_uri, "/")}/secrets/")
      )
      error_message = "Frontend token-store SAS must reference the existing shared vault with SSO enabled."
    }
    precondition {
      condition     = length(toset(values(local.job_names))) == length(local.jobs)
      error_message = "Computed ACA job names must remain unique; refuse any shortened-name collision."
    }
  }
}

# --- RBAC: ACR pull for both Container Apps ---

resource "azurerm_role_assignment" "backend_acr_pull" {
  scope                = local.shared.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

resource "azurerm_role_assignment" "frontend_acr_pull" {
  scope                = local.shared.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.frontend.principal_id
}

locals {
  vm_scopes = local.retained_group ? (
    var.demo_resource_group_name == null ? {} : {
      demo = "/subscriptions/${var.subscription_id}/resourceGroups/${var.demo_resource_group_name}"
    }
  ) : { subscription = "/subscriptions/${var.subscription_id}" }

  shared_scope_ids = !local.retained_group ? [] : [
    local.shared.acr_id, local.shared.key_vault_id, local.shared.gpu_subnet_id,
    local.shared.data_subnet_id, local.shared.private_endpoints_subnet_id,
    local.shared.container_apps_subnet_id, local.shared.functions_subnet_id,
    local.shared.postgres_private_dns_zone_id, local.shared.blob_private_dns_zone_id,
    local.shared.queue_private_dns_zone_id, local.shared.table_private_dns_zone_id,
    local.shared.log_analytics_workspace_id
  ]

  storage_scope_ids = {
    tfstate   = "${local.control_scope_id}/providers/Microsoft.Storage/storageAccounts/${azapi_resource.tfstate_storage.name}"
    artifacts = "${local.control_scope_id}/providers/Microsoft.Storage/storageAccounts/${azapi_resource.artifacts_storage.name}"
    functions = "${local.control_scope_id}/providers/Microsoft.Storage/storageAccounts/${azapi_resource.functions_storage.name}"
  }
}

moved {
  from = azurerm_role_assignment.backend_contributor
  to   = azurerm_role_assignment.backend_contributor["subscription"]
}

# Preserve legacy subscription grants by default; retained mode never emits one.
resource "azurerm_role_assignment" "backend_contributor" {
  for_each             = local.vm_scopes
  scope                = each.value
  role_definition_name = local.retained_group ? "Virtual Machine Contributor" : "Contributor"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

resource "azurerm_role_assignment" "backend_tfstate_blob" {
  scope                = local.retained_group ? local.storage_scope_ids.tfstate : azapi_resource.tfstate_storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
  depends_on           = [azapi_resource.tfstate_storage]
}

resource "azurerm_role_assignment" "backend_artifacts_blob" {
  scope                = local.retained_group ? local.storage_scope_ids.artifacts : azapi_resource.artifacts_storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
  depends_on           = [azapi_resource.artifacts_storage]
}


# --- Container Apps Jobs (FR-078): manual-trigger, one per isolated workload ---

locals {
  jobs = {
    terraform_runner = {
      image = local.terraform_runner_image
    }
    model_deployment = {
      image = local.model_deployment_image
    }
    evaluation_worker = {
      image = local.evaluation_worker_image
    }
    performance_worker = {
      image = local.performance_worker_image
    }
    export_worker = {
      image = local.export_worker_image
    }
  }

  # T140: deterministic job names (matching azurerm_container_app_job.jobs' own naming
  # below), so the backend Container App can be told the model_deployment job's name to
  # pre-dispatch it directly (the one credential-carrying workflow type, see
  # functions_client.py's module docstring) without referencing
  # azurerm_container_app_job.jobs[...] itself - that resource already depends on
  # azurerm_container_app.backend (via BACKEND_INTERNAL_CALLBACK_URL, below), so a reference
  # the other direction would create the same kind of cycle avoided by local.functions_fqdn.
  full_job_names = { for key in keys(local.jobs) : key => "${var.name_prefix}-job-${replace(key, "_", "-")}" }
  job_names = {
    for key, name in local.full_job_names : key => (
      length(name) <= 32 ? name : "${trimsuffix(substr(name, 0, 23), "-")}-${substr(sha256(name), 0, 8)}"
    )
  }
}

resource "azurerm_user_assigned_identity" "jobs" {
  for_each = local.jobs

  name                = "${var.name_prefix}-job-${replace(each.key, "_", "-")}-id"
  resource_group_name = local.resource_group_name
  location            = local.location
  tags                = local.common_tags
}

resource "azurerm_container_app_job" "jobs" {
  for_each = local.jobs

  name                         = local.job_names[each.key]
  resource_group_name          = local.resource_group_name
  location                     = local.location
  container_app_environment_id = azurerm_container_app_environment.control.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 3600
  replica_retry_limit          = 0 # no-auto-retry (FR-055/FR-089): a failed job stays failed until an explicit new user action
  tags                         = local.common_tags

  # See azurerm_container_app.backend's identical depends_on for why this waits on RBAC
  # propagation, not just the role assignment write. Cannot index [each.key] here (depends_on
  # requires a static reference), so this waits on all 5 jobs' time_sleep together.
  depends_on = [time_sleep.job_rbac_propagation]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.jobs[each.key].id]
  }

  registry {
    server   = local.shared.acr_login_server
    identity = azurerm_user_assigned_identity.jobs[each.key].id
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = replace(each.key, "_", "-")
      image  = each.value.image
      cpu    = var.job_cpu
      memory = var.job_memory

      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = var.subscription_id
      }
      # See azurerm_container_app.backend's identical env vars above for why an explicit
      # client ID is required for both azure-identity's DefaultAzureCredential and Terraform's
      # azurerm provider MSI auth against this job's user-assigned identity.
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.jobs[each.key].client_id
      }
      env {
        name  = "ARM_USE_MSI"
        value = "true"
      }
      env {
        name  = "ARM_SUBSCRIPTION_ID"
        value = var.subscription_id
      }
      env {
        name  = "ARM_TENANT_ID"
        value = data.azurerm_client_config.current.tenant_id
      }
      env {
        name  = "ARM_CLIENT_ID"
        value = azurerm_user_assigned_identity.jobs[each.key].client_id
      }
      env {
        name  = "AZURE_TENANT_ID"
        value = data.azurerm_client_config.current.tenant_id
      }
      env {
        name  = "INTERNAL_API_AUDIENCE"
        value = local.internal_api_audience
      }
      env {
        name  = "TF_STATE_STORAGE_ACCOUNT"
        value = azapi_resource.tfstate_storage.name
      }
      env {
        name  = "TF_STATE_CONTAINER"
        value = azapi_resource.tfstate_container.name
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = local.shared.application_insights_connection_string
      }
      env {
        name  = "BACKEND_INTERNAL_CALLBACK_URL"
        value = "https://${azurerm_container_app.backend.ingress[0].fqdn}/internal/workflows"
      }
      # Only export_worker actually writes here (via azurerm_role_assignment.export_worker_artifacts_blob
      # above), but every job gets the same static env block per this module's existing convention
      # (e.g. terraform_runner-only TF_STATE_STORAGE_ACCOUNT/CONTAINER above) - unused vars on the
      # other 4 jobs are harmless.
      env {
        name  = "ARTIFACTS_STORAGE_ACCOUNT"
        value = azapi_resource.artifacts_storage.name
      }
      env {
        name  = "EXPORTS_CONTAINER"
        value = azapi_resource.exports_container.name
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}

resource "azurerm_role_assignment" "job_acr_pull" {
  for_each = local.jobs

  scope                = local.shared.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.jobs[each.key].principal_id
}

# Only the terraform_runner job needs write access to the per-environment Terraform state
# container — least-privilege per FR-081 (evaluation/performance/export workers don't touch
# Terraform state at all).
resource "azurerm_role_assignment" "terraform_runner_tfstate_blob" {
  scope                = local.retained_group ? local.storage_scope_ids.tfstate : azapi_resource.tfstate_storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.jobs["terraform_runner"].principal_id
  depends_on           = [azapi_resource.tfstate_storage]
}

moved {
  from = azurerm_role_assignment.terraform_runner_contributor
  to   = azurerm_role_assignment.terraform_runner_contributor["subscription"]
}

# Retained demo state owns only the NIC/VM children, never the demo group.
resource "azurerm_role_assignment" "terraform_runner_contributor" {
  for_each             = local.vm_scopes
  scope                = each.value
  role_definition_name = local.retained_group ? "Virtual Machine Contributor" : "Contributor"
  principal_id         = azurerm_user_assigned_identity.jobs["terraform_runner"].principal_id
}

moved {
  from = azurerm_role_assignment.model_deployment_vm_contributor
  to   = azurerm_role_assignment.model_deployment_vm_contributor["subscription"]
}

# The deployment worker uses VM Run Command within the selected demo group.
resource "azurerm_role_assignment" "model_deployment_vm_contributor" {
  for_each             = local.vm_scopes
  scope                = each.value
  role_definition_name = "Virtual Machine Contributor"
  principal_id         = azurerm_user_assigned_identity.jobs["model_deployment"].principal_id
}

resource "azurerm_role_assignment" "export_worker_artifacts_blob" {
  scope                = local.retained_group ? local.storage_scope_ids.artifacts : azapi_resource.artifacts_storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.jobs["export_worker"].principal_id
  depends_on           = [azapi_resource.artifacts_storage]
}

data "azurerm_role_definition" "subnet_vm" {
  count              = local.retained_group ? 1 : 0
  role_definition_id = "9980e02c-c2be-4d73-94e8-173b1dc7cf3c"
  scope              = local.shared.gpu_subnet_id
}

data "azurerm_role_definition" "subnet_reader" {
  count              = local.retained_group ? 1 : 0
  role_definition_id = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
  scope              = local.shared.gpu_subnet_id
}

locals {
  subnet_role_permissions = local.retained_group ? [
    data.azurerm_role_definition.subnet_vm[0].permissions,
    data.azurerm_role_definition.subnet_reader[0].permissions
  ] : []
  subnet_permissions = flatten(local.subnet_role_permissions)
  subnet_actions     = flatten([for permission in local.subnet_permissions : permission.actions])
  subnet_operations = {
    read   = "microsoft.network/virtualnetworks/subnets/read"
    join   = "microsoft.network/virtualnetworks/subnets/join/action"
    write  = "microsoft.network/virtualnetworks/subnets/write"
    delete = "microsoft.network/virtualnetworks/subnets/delete"
  }
  subnet_operation_allowed = {
    for key, operation in local.subnet_operations : key => anytrue([
      for action in local.subnet_actions :
      can(regex("^[a-z0-9./*-]+$", lower(action))) &&
      can(regex("^${replace(replace(lower(action), ".", "\\."), "*", ".*")}$", operation))
    ])
  }
  safe_subnet_permissions = (
    length(local.subnet_role_permissions) == 2
    && alltrue([for permissions in local.subnet_role_permissions : length(permissions) > 0])
    && alltrue([for action in local.subnet_actions : can(regex("^[a-z0-9./*-]+$", lower(action)))])
    && alltrue([for permission in local.subnet_permissions :
      length(permission.not_actions) == 0 &&
      (permission.condition == null || permission.condition == "") &&
      (permission.condition_version == null || permission.condition_version == "")
    ])
    && local.subnet_operation_allowed.read && local.subnet_operation_allowed.join
    && !local.subnet_operation_allowed.write && !local.subnet_operation_allowed.delete
  )
}

# VM Contributor supplies join but not subnet read. Reader supplies read at the same
# exact subnet; validate their combined definitions before assigning either role.
resource "azurerm_role_assignment" "runtime_gpu_subnet" {
  for_each = local.retained_group ? {
    backend          = azurerm_user_assigned_identity.backend.principal_id
    terraform_runner = azurerm_user_assigned_identity.jobs["terraform_runner"].principal_id
  } : {}

  scope              = local.shared.gpu_subnet_id
  role_definition_id = data.azurerm_role_definition.subnet_vm[0].id
  principal_id       = each.value

  lifecycle {
    precondition {
      condition     = local.safe_subnet_permissions
      error_message = "The subnet role must unconditionally allow read/join, with no possible subnet write/delete or not_actions; no automatic broad-role fallback is allowed."
    }
  }
}

resource "azurerm_role_assignment" "runtime_gpu_subnet_reader" {
  for_each = local.retained_group ? {
    backend          = azurerm_user_assigned_identity.backend.principal_id
    terraform_runner = azurerm_user_assigned_identity.jobs["terraform_runner"].principal_id
  } : {}

  scope              = local.shared.gpu_subnet_id
  role_definition_id = data.azurerm_role_definition.subnet_reader[0].id
  principal_id       = each.value

  lifecycle {
    precondition {
      condition     = local.safe_subnet_permissions
      error_message = "The composed subnet roles must unconditionally allow read/join without subnet write/delete, conditions or not_actions."
    }
  }
}

resource "azurerm_role_assignment" "backend_functions_keys" {
  count                = local.retained_group ? 1 : 0
  scope                = local.functions_resource_id
  role_definition_name = "Website Contributor"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
  depends_on           = [azurerm_linux_function_app.orchestrator]
}

resource "azurerm_role_assignment" "backend_model_job" {
  count                = local.retained_group ? 1 : 0
  scope                = local.job_scope_ids["model_deployment"]
  role_definition_name = "Container Apps Jobs Operator"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
  depends_on           = [azurerm_container_app_job.jobs]
}

# Azure RBAC role assignments are eventually consistent: the write can succeed while the grant
# itself takes up to roughly a minute to actually be enforced at the relevant data plane. A
# Container App/Job whose own provisioning needs a role that was *just* granted (image pull via
# AcrPull, Key Vault secret resolution via Key Vault Secrets User) can therefore still fail even
# though Terraform's dependency graph (via the depends_on below) already sequences the role
# assignment strictly before it. This was confirmed necessary in practice: the backend failed
# with a Key Vault secret-resolution error on the first apply attempt after switching from
# system-assigned to user-assigned identities, immediately after its role assignments reported
# "Creation complete". These time_sleep resources add a short buffer between "role assignment
# write acknowledged" and "the dependent resource's own creation begins".
resource "time_sleep" "backend_rbac_propagation" {
  depends_on = [
    azurerm_role_assignment.backend_acr_pull,
    azurerm_role_assignment.backend_kv_secrets_user,
  ]

  create_duration = "30s"
}

resource "time_sleep" "frontend_rbac_propagation" {
  depends_on = [
    azurerm_role_assignment.frontend_acr_pull,
    azurerm_role_assignment.frontend_kv_secrets_user,
  ]

  create_duration = "30s"
}

resource "time_sleep" "job_rbac_propagation" {
  for_each = local.jobs

  # Cannot index each.key here: depends_on requires a static resource reference, so this waits
  # on all 5 jobs' AcrPull grants together (they're created in parallel, so this costs no extra
  # wall-clock time) rather than only this job's own grant.
  depends_on = [azurerm_role_assignment.job_acr_pull]

  create_duration = "30s"
}

# --- Durable Functions app (FR-076/FR-077): workflow coordination only, no web API, no domain
# data. Elastic Premium plan (not Consumption) for regional VNet Integration into snet-functions,
# needed to reach private PostgreSQL-adjacent resources and Key Vault. ---

resource "azurerm_service_plan" "functions" {
  name                = "${var.name_prefix}-functions-plan"
  resource_group_name = local.resource_group_name
  location            = local.location
  os_type             = "Linux"
  sku_name            = var.functions_plan_sku
  tags                = local.common_tags
}

resource "azurerm_linux_function_app" "orchestrator" {
  name                = local.functions_app_name
  resource_group_name = local.resource_group_name
  location            = local.location
  service_plan_id     = azurerm_service_plan.functions.id
  tags                = local.common_tags

  storage_account_name          = azapi_resource.functions_storage.name
  storage_uses_managed_identity = true

  virtual_network_subnet_id = local.shared.functions_subnet_id

  identity {
    type = "SystemAssigned"
  }

  # Explicitly disable basic-auth publishing rather than using the provider's default.
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false

  site_config {
    always_on                              = true
    vnet_route_all_enabled                 = true
    application_insights_connection_string = local.shared.application_insights_connection_string

    application_stack {
      python_version = "3.11"
    }
  }

  app_settings = merge({
    FUNCTIONS_WORKER_RUNTIME = "python"

    AZURE_SUBSCRIPTION_ID = var.subscription_id
    AZURE_TENANT_ID       = data.azurerm_client_config.current.tenant_id
    INTERNAL_API_AUDIENCE = local.internal_api_audience

    # Read by each orchestrator to call FastAPI's internal callback API
    # (contracts/api.md's Internal Orchestration Callback API, FR-076/FR-086).
    BACKEND_INTERNAL_CALLBACK_URL = "https://${azurerm_container_app.backend.ingress[0].fqdn}/internal/workflows"

    # Container Apps Job names this Functions app dispatches (User Story 10 Acceptance Scenario
    # 3/FR-077/FR-078) — one Durable Functions activity per job.
    JOB_NAME_TERRAFORM_RUNNER     = azurerm_container_app_job.jobs["terraform_runner"].name
    JOB_NAME_MODEL_DEPLOYMENT     = azurerm_container_app_job.jobs["model_deployment"].name
    JOB_NAME_EVALUATION_WORKER    = azurerm_container_app_job.jobs["evaluation_worker"].name
    JOB_NAME_PERFORMANCE_WORKER   = azurerm_container_app_job.jobs["performance_worker"].name
    JOB_NAME_EXPORT_WORKER        = azurerm_container_app_job.jobs["export_worker"].name
    CONTAINER_APPS_RESOURCE_GROUP = local.resource_group_name
    }, var.functions_package_sha256 == null ? {} : {
    WEBSITE_RUN_FROM_PACKAGE                     = local.functions_package_blob_url
    WEBSITE_RUN_FROM_PACKAGE_BLOB_MI_RESOURCE_ID = "SystemAssigned"
  })
}

# Grants the Functions app's identity permission to start (and read status of) each Container
# Apps Job, scoped to exactly those 5 job resources — not the whole resource group (FR-081).
resource "azurerm_role_assignment" "functions_start_job" {
  for_each = local.jobs

  scope                = local.retained_group ? local.job_scope_ids[each.key] : azurerm_container_app_job.jobs[each.key].id
  role_definition_name = local.retained_group ? "Container Apps Jobs Operator" : "Container Apps Jobs Contributor"
  principal_id         = azurerm_linux_function_app.orchestrator.identity[0].principal_id
  depends_on           = [azurerm_container_app_job.jobs]
}

resource "azurerm_role_assignment" "functions_storage_blob" {
  scope                = local.retained_group ? local.storage_scope_ids.functions : azapi_resource.functions_storage.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_linux_function_app.orchestrator.identity[0].principal_id
  depends_on           = [azapi_resource.functions_storage]
}

resource "azurerm_role_assignment" "functions_storage_queue" {
  scope                = local.retained_group ? local.storage_scope_ids.functions : azapi_resource.functions_storage.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_linux_function_app.orchestrator.identity[0].principal_id
  depends_on           = [azapi_resource.functions_storage]
}

resource "azurerm_role_assignment" "functions_storage_table" {
  scope                = local.retained_group ? local.storage_scope_ids.functions : azapi_resource.functions_storage.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = azurerm_linux_function_app.orchestrator.identity[0].principal_id
  depends_on           = [azapi_resource.functions_storage]
}

# --- Internal orchestration callback API audience (FR-076/FR-086): the `aud` claim the backend
# validates on every /internal/workflows/* request (src/api/internal_auth.py). Deliberately reuses
# Azure Resource Manager's well-known, always-present first-party audience
# (https://management.azure.com/) instead of a dedicated Entra ID app registration. Every managed identity
# in the tenant (Functions app, Container Apps Jobs) can already acquire an ARM-audience token via
# `DefaultAzureCredential().get_token("https://management.azure.com/.default")` with zero additional
# Entra permissions, since ARM is a pre-existing first-party resource in every tenant. This is not a
# weaker security boundary than the app-registration approach would have been: that design already
# relied on "any managed identity in the tenant can request a token" (no app role assignment
# required) and authorized callers via their RBAC-scoped identity and private VNet placement, not
# Entra app permissions - reusing the ARM audience keeps exactly that same boundary while requiring
# no directory-level write access at all.
locals {
  # No trailing slash: `DefaultAzureCredential().get_token("https://management.azure.com/.default")`
  # goes through the legacy App Service-style MSI endpoint (used by Container Apps/Jobs and
  # Azure Functions alike), which derives the `resource` query param by stripping the "/.default"
  # suffix from the scope - producing "https://management.azure.com" with no trailing slash. Entra
  # ID then issues the token with that exact string as its `aud` claim. src/api/internal_auth.py's
  # PyJWT audience check is an exact string match, so this must match the token's real `aud`
  # verbatim (confirmed empirically: a trailing slash here caused every real callback to fail with
  # "Invalid internal service token: Audience doesn't match", even though ARM itself accepts both
  # forms interchangeably for authorization purposes).
  internal_api_audience = "https://management.azure.com"
}

# T140: computed rather than read from azurerm_linux_function_app.orchestrator's own
# default_hostname/id attributes, on purpose - the backend Container App (below) needs this
# Function App's URL/resource ID to call it, but the Function App's own app_settings already
# reference azurerm_container_app.backend (BACKEND_INTERNAL_CALLBACK_URL) and
# azurerm_container_app_job.jobs (the JOB_NAME_* settings), so a reference the other direction
# would create a cycle (backend -> functions -> jobs -> backend). Both values are deterministic
# once the Function App's name is fixed (Linux Function Apps always resolve to
# `<name>.azurewebsites.net`, and ARM resource IDs are computable from subscription/resource
# group/name), so this avoids the cycle while resolving to the same values.
locals {
  functions_app_name         = "${var.name_prefix}-functions-${local.unique_suffix}"
  functions_fqdn             = "${local.functions_app_name}.azurewebsites.net"
  functions_resource_id      = "${local.control_scope_id}/providers/Microsoft.Web/sites/${local.functions_app_name}"
  functions_package_blob_url = var.functions_package_sha256 == null ? null : "https://${azapi_resource.functions_storage.name}.blob.core.windows.net/${azapi_resource.functions_packages[0].name}/functions-${var.functions_package_sha256}.zip"
  job_scope_ids              = { for key, name in local.job_names : key => "${local.control_scope_id}/providers/Microsoft.App/jobs/${name}" }
}

# --- Entra ID SSO for the Container Apps' built-in auth (FR-075) ---

locals {
  # Computed rather than read from azurerm_container_app.{backend,frontend}.ingress[0].fqdn on
  # purpose: both apps now reference this application's client secret (via a Key Vault-backed
  # `secret` block, FR-081/FR-085), so if the app registration's redirect_uris depended on the
  # apps' own ingress attribute, Terraform would see a dependency cycle (app -> secret -> app
  # registration -> app's own fqdn -> app). Container Apps' FQDN is deterministic
  # (`<app-name>.<environment-default-domain>`) once ingress is enabled without a custom domain,
  # so this avoids the cycle while resolving to the same value.
  backend_fqdn  = "${var.name_prefix}-backend.${azurerm_container_app_environment.control.default_domain}"
  frontend_fqdn = "${var.name_prefix}-frontend.${azurerm_container_app_environment.control.default_domain}"
}

resource "azuread_application" "sso" {
  count = local.manage_sso ? 1 : 0

  display_name = "${var.entra_app_display_name}-${var.stage}"

  web {
    redirect_uris = [
      "https://${local.frontend_fqdn}/.auth/login/aad/callback",
      "https://${local.backend_fqdn}/.auth/login/aad/callback",
    ]

    implicit_grant {
      id_token_issuance_enabled = true
    }
  }
}

resource "azuread_service_principal" "sso" {
  count = local.manage_sso ? 1 : 0

  client_id = azuread_application.sso[0].client_id
}

resource "azuread_application_password" "sso" {
  count = local.manage_sso ? 1 : 0

  application_id = azuread_application.sso[0].id
  display_name   = "container-apps-easy-auth"
}

resource "azurerm_role_assignment" "backend_kv_secrets_user" {
  scope                = local.shared.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

resource "azurerm_role_assignment" "frontend_kv_secrets_user" {
  # Only the SSO client secret needs Key Vault access on the frontend today; skip the RBAC
  # grant along with the rest of the SSO wiring when it's disabled.
  count = var.enable_sso ? 1 : 0

  scope                = local.shared.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.frontend.principal_id
}

resource "azurerm_role_assignment" "functions_kv_secrets_user" {
  scope                = local.shared.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_function_app.orchestrator.identity[0].principal_id
}

resource "azurerm_key_vault_secret" "sso_client_secret" {
  # NOTE: this resource does a data-plane read/write against the Key Vault on every plan/apply,
  # which will fail with 403 ("Public network access is disabled") when applied from outside the
  # VNet with this private-only topology. For managed SSO, this secret needs the same
  # out-of-band, in-VNet bootstrap-job treatment (see infra/README.md runbook) instead of being
  # applied directly.
  count = local.manage_sso ? 1 : 0

  name         = "sso-client-secret"
  value        = azuread_application_password.sso[0].value
  key_vault_id = local.shared.key_vault_id
}

# Microsoft.App/containerApps/authConfigs isn't exposed by the azurerm provider yet; azapi talks
# to the ARM API directly for this one resource so Entra ID sign-in (FR-075) doesn't require a
# manual `az` step outside Terraform.
resource "azapi_resource" "backend_auth_config" {
  count = var.enable_sso ? 1 : 0

  type      = "Microsoft.App/containerApps/authConfigs@2023-05-01"
  name      = "current"
  parent_id = azurerm_container_app.backend.id

  body = jsonencode({
    properties = {
      platform = {
        enabled = true
      }
      globalValidation = {
        unauthenticatedClientAction = "RedirectToLoginPage"
        redirectToProvider          = "azureactivedirectory"
      }
      identityProviders = {
        azureActiveDirectory = {
          enabled = true
          registration = {
            clientId                = local.sso_client_id
            clientSecretSettingName = "sso-client-secret"
            openIdIssuer            = "https://login.microsoftonline.com/${local.sso_tenant_id}/v2.0"
          }
          validation = {
            allowedAudiences = [local.sso_client_id]
          }
        }
      }
    }
  })
}

resource "azapi_resource" "frontend_auth_config" {
  count = var.enable_sso ? 1 : 0

  type      = "Microsoft.App/containerApps/authConfigs@2024-03-01"
  name      = "current"
  parent_id = azurerm_container_app.frontend.id

  body = jsonencode({
    properties = merge({
      platform = {
        enabled = true
      }
      globalValidation = {
        unauthenticatedClientAction = "RedirectToLoginPage"
        redirectToProvider          = "azureactivedirectory"
      }
      identityProviders = {
        azureActiveDirectory = {
          enabled = true
          registration = {
            clientId                = local.sso_client_id
            clientSecretSettingName = "sso-client-secret"
            openIdIssuer            = "https://login.microsoftonline.com/${local.sso_tenant_id}/v2.0"
          }
          validation = {
            allowedAudiences = [local.sso_client_id]
          }
        }
      }
      }, var.frontend_token_store_sas_secret_id == null ? {} : {
      login = {
        tokenStore = {
          enabled = true
          azureBlobStorage = {
            sasUrlSettingName = "frontend-token-store-sas"
          }
        }
      }
    })
  })
}

# --- Alerts (FR-087) ---

resource "azurerm_monitor_action_group" "control" {
  name                = "${var.name_prefix}-control-alerts"
  resource_group_name = local.resource_group_name
  short_name          = "llmalerts"
  tags                = local.common_tags
}

resource "azurerm_monitor_metric_alert" "postgres_unavailable" {
  name                = "${var.name_prefix}-postgres-unavailable"
  resource_group_name = local.resource_group_name
  scopes              = [azurerm_postgresql_flexible_server.control.id]
  description         = "PostgreSQL Flexible Server availability dropped (FR-087)."
  severity            = 1

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "is_db_alive"
    aggregation      = "Minimum"
    operator         = "LessThan"
    threshold        = 1
  }

  action {
    action_group_id = azurerm_monitor_action_group.control.id
  }
}

resource "azurerm_monitor_activity_log_alert" "job_failures" {
  name                = "${var.name_prefix}-container-apps-job-failures"
  resource_group_name = local.resource_group_name
  scopes              = [local.resource_group_id]
  description         = "Any Container Apps Job execution fails (FR-087)."

  criteria {
    resource_type  = "Microsoft.App/jobs"
    category       = "ResourceHealth"
    resource_group = local.resource_group_name
  }

  action {
    action_group_id = azurerm_monitor_action_group.control.id
  }
}
