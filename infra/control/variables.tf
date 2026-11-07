# Variables for infra/control: the persistent application control plane (rg-llm-control-{stage})
# — Container Apps (React + FastAPI), Container Apps Jobs, the Durable Functions app, and
# PostgreSQL. Reads infra/shared's outputs via a local terraform_remote_state data source (see
# main.tf), so infra/shared must be applied first.

variable "subscription_id" {
  description = "Azure subscription GUID to provision into. Must match infra/shared."
  type        = string
}

variable "stage" {
  description = "Deployment stage/slot, e.g. 'dev', 'pilot'. Must match the infra/shared stage this module reads state from."
  type        = string
  default     = "dev"
}

variable "existing_resource_group_name" {
  description = "Optional retained control group. Fresh isolated state only; Terraform reads the group and manages its children, never the group itself."
  type        = string
  default     = null

  validation {
    condition = var.existing_resource_group_name == null ? true : (
      can(regex("^[A-Za-z0-9._()-]{1,90}$", var.existing_resource_group_name))
      && !endswith(var.existing_resource_group_name, ".")
    )
    error_message = "existing_resource_group_name must be a nonempty Azure resource group name, not ending with a period."
  }
}

variable "shared_state_path" {
  description = "Path to infra/shared's local state file, relative to this module's working directory."
  type        = string
  default     = "../shared/terraform.tfstate"
}

variable "name_prefix" {
  description = "Short, DNS-safe prefix for all resources in this module."
  type        = string
  default     = "llm"
}

variable "tags" {
  description = "Resource tags applied to every resource in this module (FR-088)."
  type        = map(string)
  default     = {}
}

variable "demo_resource_group_name" {
  description = "Optional retained demo group selected by the operator, never by browser input. Fresh demo state only."
  type        = string
  default     = null

  validation {
    condition = var.demo_resource_group_name == null ? true : (
      can(regex("^[A-Za-z0-9._()-]{1,90}$", var.demo_resource_group_name))
      && !endswith(var.demo_resource_group_name, ".")
    )
    error_message = "demo_resource_group_name must be a nonempty Azure resource group name, not ending with a period."
  }
}

variable "demo_resource_tags" {
  description = "Operator-enforced demo ownership tags; these override browser-supplied tags."
  type        = map(string)
  default     = {}
}

variable "container_apps_workload_profile" {
  description = "Workload profile used by the Container Apps environment and every app/job in it. Consumption is the cheapest profile that still supports VNet integration."
  type        = string
  default     = "Consumption"
}

variable "container_apps_infrastructure_resource_group_name" {
  description = "Optional explicitly approved platform-created Container Apps infrastructure group name. This does not adopt an existing group or grant cleanup permissions."
  type        = string
  default     = null

  validation {
    condition = var.container_apps_infrastructure_resource_group_name == null ? true : (
      can(regex("^[A-Za-z0-9._()-]{1,90}$", var.container_apps_infrastructure_resource_group_name))
      && !endswith(var.container_apps_infrastructure_resource_group_name, ".")
    )
    error_message = "container_apps_infrastructure_resource_group_name must be a nonblank Azure resource group name, not ending in a period."
  }
}

# --- Backend/frontend Container Apps ---

variable "backend_image" {
  description = "Full ACR image reference for the backend container. Left as a placeholder default pointing at a tag that doesn't exist yet; update after the first `az acr build` push (infra/control/README.md's bring-up order)."
  type        = string
  default     = null
}

variable "frontend_image" {
  description = "Full ACR image reference for the frontend container."
  type        = string
  default     = null
}

variable "backend_cpu" {
  # 1.0 (not the Consumption plan's smaller fractional options) is required so
  # Ray - used internally by the performance-test run type's llmperf runner -
  # sees at least one whole CPU. Ray truncates fractional CPU counts (e.g. the
  # previous 0.5) down to 0, which then made every `@ray.remote` client actor
  # wait forever for a CPU that would never become available, hanging every
  # performance run until it hit its own wall-clock timeout.
  type    = number
  default = 1.0
}

variable "backend_memory" {
  # Container Apps requires a fixed cpu/memory pairing; 2Gi is the required
  # partner for cpu = 1.0.
  type    = string
  default = "2Gi"
}

variable "frontend_cpu" {
  type    = number
  default = 0.25
}

variable "frontend_memory" {
  type    = string
  default = "0.5Gi"
}

variable "backend_min_replicas" {
  type    = number
  default = 1
}

variable "backend_max_replicas" {
  type    = number
  default = 2
}

variable "database_admin_password" {
  description = "PostgreSQL admin password. Leave null to generate one (stored only in Key Vault + Terraform state, never in an app setting — FR-081/FR-085)."
  type        = string
  default     = null
  sensitive   = true
}

variable "database_admin_user" {
  type    = string
  default = "llmadmin"
}

variable "manage_database_url_secret" {
  description = "Write database-url into the shared private vault after PostgreSQL/database creation and before the backend revision. Requires a private-network Terraform executor with separately approved vault secret-write access. False preserves external seeding."
  type        = bool
  default     = false
}

variable "database_name" {
  type    = string
  default = "llmserving"
}

variable "postgres_version" {
  type    = string
  default = "16"
}

variable "postgres_sku_name" {
  description = "PostgreSQL Flexible Server SKU, e.g. 'B_Standard_B1ms' (burstable, cheapest) for a pilot."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  type    = number
  default = 32768
}

# --- Container Apps Jobs (FR-078) ---

variable "terraform_runner_image" {
  type    = string
  default = null
}

variable "model_deployment_image" {
  type    = string
  default = null
}

variable "evaluation_worker_image" {
  type    = string
  default = null
}

variable "performance_worker_image" {
  type    = string
  default = null
}

variable "export_worker_image" {
  type    = string
  default = null
}

variable "job_cpu" {
  type    = number
  default = 1.0
}

variable "job_memory" {
  type    = string
  default = "2Gi"
}

# --- Durable Functions app (FR-077) ---

variable "functions_plan_sku" {
  description = "Elastic Premium SKU for the Functions app's hosting plan. Premium (not Consumption) is required for regional VNet Integration to reach private PostgreSQL/Key Vault."
  type        = string
  default     = "EP1"
}

variable "functions_package_sha256" {
  description = "Optional reviewed ready-to-run Functions ZIP SHA-256. Uses a private digest-named blob in the Functions host account instead of Azure Files or ZIP push. Upload that exact ZIP with OAuth after full apply, then restart/sync triggers. Null preserves legacy deployment settings."
  type        = string
  default     = null

  validation {
    condition     = var.functions_package_sha256 == null ? true : can(regex("^[0-9a-f]{64}$", var.functions_package_sha256))
    error_message = "functions_package_sha256 must be the reviewed ZIP's 64-character lowercase SHA-256, never a URL, SAS or tag."
  }
}

# --- Entra ID SSO (FR-075) ---

variable "additional_frontend_sso_redirect_uris" {
  description = "Additional HTTPS Easy Auth callback URIs for externally managed frontend custom domains, used only with a Terraform-managed SSO application."
  type        = list(string)
  default     = []
  nullable    = false

  validation {
    condition = alltrue([for uri in var.additional_frontend_sso_redirect_uris : try(
      length(split("/", uri)[2]) <= 253 &&
      can(regex("^https://([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\\.)+[A-Za-z]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?/\\.auth/login/aad/callback$", uri)),
      false
    )])
    error_message = "Additional frontend SSO redirects must be HTTPS DNS hostnames with the exact /.auth/login/aad/callback path and no port, query, fragment or credentials."
  }
}

variable "enable_sso" {
  description = <<-EOT
    Whether to provision the Entra ID app registration/service principal and wire Container
    Apps' built-in (Easy Auth) sign-in. Requires the identity running Terraform to hold the
    Application Administrator (or equivalent Microsoft Graph Application.ReadWrite.All)
    directory role, unless existing_sso_client_id and existing_sso_secret_id are supplied
    by an authorized external bootstrap. Disabling Easy Auth does not disable backend
    JWT authentication; an unconfigured operator audience fails closed.
  EOT
  type        = bool
  default     = true
}

variable "existing_sso_client_id" {
  description = "Optional externally bootstrapped Entra application client ID. Avoids Graph application/SP/password creation; never use an existing production application's identity."
  type        = string
  default     = null
  validation {
    condition     = var.existing_sso_client_id == null || can(regex("^[0-9a-fA-F-]{36}$", var.existing_sso_client_id))
    error_message = "existing_sso_client_id must be an application client UUID."
  }
}

variable "existing_sso_secret_id" {
  description = "Versionless HTTPS Key Vault secret URI for the external application's credential, not its secret value. A tenant-approved operator must write the secret through private connectivity."
  type        = string
  default     = null
  validation {
    condition     = var.existing_sso_secret_id == null || can(regex("^https://[a-zA-Z0-9-]+\\.vault\\.azure\\.net/secrets/[a-zA-Z0-9-]+/?$", var.existing_sso_secret_id))
    error_message = "existing_sso_secret_id must be a versionless Azure Key Vault secret URI, never a secret value."
  }
}

variable "frontend_token_store_sas_secret_id" {
  description = "Optional versionless shared-vault secret URI containing a short-lived HTTPS user-delegation SAS URL for the private frontend-auth-tokens container. Configure after container creation and secure operator seeding; never pass the SAS value to Terraform."
  type        = string
  default     = null
  validation {
    condition     = var.frontend_token_store_sas_secret_id == null || can(regex("^https://[a-zA-Z0-9-]+\\.vault\\.azure\\.net/secrets/[a-zA-Z0-9-]+/?$", var.frontend_token_store_sas_secret_id))
    error_message = "frontend_token_store_sas_secret_id must be a versionless Key Vault secret URI, never a SAS or secret value."
  }
}

variable "existing_sso_tenant_id" {
  description = "Optional operator SSO tenant UUID for an externally approved application. Null retains the ARM deployment tenant; never changes ARM or internal managed-identity callback tenants."
  type        = string
  default     = null
  validation {
    condition     = var.existing_sso_tenant_id == null || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.existing_sso_tenant_id))
    error_message = "existing_sso_tenant_id must be a tenant UUID."
  }
}

variable "entra_app_display_name" {
  description = "Display name for the Microsoft Entra ID app registration backing Container Apps' built-in (Easy Auth) sign-in."
  type        = string
  default     = "llm-serving-demo-sso"
}

variable "auth_allowed_email_domains" {
  description = "Comma-separated allowed email domains, forwarded to the backend app as a defense-in-depth check in addition to Entra ID SSO. Plain CSV — NOT JSON-array syntax."
  type        = string
  default     = "example.com"
}

variable "auth_bypass_paths" {
  description = "Comma-separated auth-bypass paths (health checks, OpenAPI docs, and /internal - the Internal Orchestration Callback API, which is authenticated separately via managed-identity bearer tokens validated by src/api/internal_auth.py, never by the browser-session headers the SSO middleware checks for). Plain CSV — NOT JSON-array syntax. Must be kept in sync with backend/src/config.py's Settings.auth_bypass_paths default_factory, which this Terraform-injected env var otherwise silently overrides."
  type        = string
  default     = "/healthz,/readyz,/openapi.json,/docs,/docs/oauth2-redirect,/redoc,/internal"
}

variable "backend_extra_app_settings" {
  description = "Additional/override environment variables for the backend Container App. Merged on top of the built-in settings."
  type        = map(string)
  default     = {}
}
