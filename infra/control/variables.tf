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

variable "container_apps_workload_profile" {
  description = "Workload profile used by the Container Apps environment and every app/job in it. Consumption is the cheapest profile that still supports VNet integration."
  type        = string
  default     = "Consumption"
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

# --- Entra ID SSO (FR-075) ---

variable "enable_sso" {
  description = <<-EOT
    Whether to provision the Entra ID app registration/service principal and wire Container
    Apps' built-in (Easy Auth) sign-in. Requires the identity running Terraform to hold the
    Application Administrator (or equivalent Microsoft Graph Application.ReadWrite.All)
    directory role. Set to false to deploy the rest of the stack when that role isn't
    available (e.g. in a restricted sandbox tenant) — the apps come up without SSO enforced
    until an admin grants the role and this is re-applied with the default true.
  EOT
  type        = bool
  default     = true
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
