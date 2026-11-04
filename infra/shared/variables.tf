# Variables for infra/shared: the rarely-changing platform layer (rg-llm-shared-{stage}) —
# networking, DNS, egress, container registry, Key Vault, and monitoring shared by every
# environment. See specs/001-llm-serving-demo/research.md Section 7 and plan.md's Target
# Platform section for the full rationale.

variable "subscription_id" {
  description = "Azure subscription GUID to provision into."
  type        = string
}

variable "location" {
  description = "Azure region. Must match infra/control and infra/demo. Verify GPU quota, SKU availability, and applicable policies in your subscription."
  type        = string
  default     = "polandcentral"
}

variable "stage" {
  description = "Deployment stage/slot, e.g. 'dev', 'pilot'. Used to name the retained resource groups (rg-llm-shared-{stage}, rg-llm-control-{stage}) per FR-074."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9]{2,12}$", var.stage))
    error_message = "stage must be 2-12 lowercase alphanumeric characters."
  }
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

variable "vnet_address_space" {
  description = "Address space for the shared VNet (plan.md Target Platform: vnet-llm-{stage})."
  type        = list(string)
  default     = ["10.20.0.0/16"]
}

variable "container_apps_subnet_prefix" {
  description = "Address prefix for snet-containerapps (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.20.1.0/24"
}

variable "private_endpoints_subnet_prefix" {
  description = "Address prefix for snet-private-endpoints (hosts Key Vault and Storage private endpoints; not delegated)."
  type        = string
  default     = "10.20.2.0/24"
}

variable "functions_subnet_prefix" {
  description = "Address prefix for snet-functions (delegated to Microsoft.Web/serverFarms, regional VNet Integration for the Durable Functions app)."
  type        = string
  default     = "10.20.3.0/24"
}

variable "data_subnet_prefix" {
  description = "Address prefix for snet-data (delegated to Microsoft.DBforPostgreSQL/flexibleServers, private-access PostgreSQL)."
  type        = string
  default     = "10.20.4.0/26"
}

variable "gpu_subnet_prefix" {
  description = "Address prefix for snet-gpu (hosts each demo environment's GPU VM NIC; no public IP per FR-079)."
  type        = string
  default     = "10.20.10.0/24"
}

variable "log_retention_days" {
  description = "Log Analytics workspace retention, in days."
  type        = number
  default     = 30
}

variable "key_vault_sku" {
  description = "Key Vault SKU."
  type        = string
  default     = "standard"
}

variable "key_vault_allowed_ip_ranges" {
  description = <<-EOT
    CIDR ranges (e.g. an operator's public IP as "a.b.c.d/32") temporarily allowed to reach the
    Key Vault's data plane over the public internet, for bootstrap/admin secret writes from
    outside the VNet before CI/CD has a private network path (e.g. a self-hosted runner or VPN
    Gateway inside snet-container-apps). Leave empty (the default) to keep the vault fully
    private, reachable only via its private endpoint.
  EOT
  type        = list(string)
  default     = []
}
