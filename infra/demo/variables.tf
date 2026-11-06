# Variables for infra/demo: the disposable, per-environment GPU layer (rg-llm-demo-{environmentId}).
# See main.tf's header and specs/001-llm-serving-demo/research.md Section 7 for why this is now
# fully private (no public IP, no Bastion) instead of the superseded infra/azure module's model.

variable "subscription_id" {
  description = "Azure subscription GUID to provision into. Must match infra/shared and infra/control."
  type        = string
}

variable "shared_state_path" {
  description = "Path to infra/shared's local state file, relative to this module's working directory."
  type        = string
  default     = "../shared/terraform.tfstate"
}

variable "expected_region" {
  description = "Preflighted region, which must match the shared network location. Null preserves legacy manual workflows."
  type        = string
  default     = null
}

variable "environment_id" {
  description = "Demo Environment id (data-model.md); used to name rg-llm-demo-{environmentId} (FR-074)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.environment_id))
    error_message = "environment_id must be 3-20 lowercase alphanumeric/hyphen characters."
  }
}

variable "existing_resource_group_name" {
  description = "Operator-owned, retained resource group. Use only with fresh environment state; null preserves the original managed-group deployment."
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

variable "name_prefix" {
  description = "Short, DNS-safe prefix for all resources in this module."
  type        = string
  default     = "llm"
}

variable "profile_size_class" {
  description = "Cloud Deployment Profile size class: small (3B/7B), medium (27B/32B), or large (70B). Selects the VM SKU per research.md Section 4."
  type        = string
  default     = "small"

  validation {
    condition     = contains(["small", "medium", "large"], var.profile_size_class)
    error_message = "profile_size_class must be one of: small, medium, large."
  }
}

variable "vm_size" {
  description = "Explicit VM SKU override. Leave null to use the research.md-recommended default for profile_size_class."
  type        = string
  default     = null
}

variable "vm_priority" {
  description = "Explicit Spot or Regular allocation. Spot preserves the legacy default; Regular uses family and total regional quota, not low-priority quota."
  type        = string
  default     = "Spot"

  validation {
    condition     = var.vm_priority == null ? false : contains(["Spot", "Regular"], var.vm_priority)
    error_message = "vm_priority must be Spot or Regular."
  }
}

variable "admin_username" {
  description = "Local admin username for the GPU VM (SSH access only, no password auth). No inbound SSH path exists in this architecture (FR-079); retained for VM provisioning requirements and any future diagnostic path."
  type        = string
  default     = "azureuser"
}

variable "admin_ssh_public_key" {
  description = "SSH public key content for admin access to the VM."
  type        = string
}

variable "vllm_image" {
  description = "vLLM serving image and tag (research.md Section 1). Pre-pulled by cloud-init so the first model_deployment run-command invocation doesn't pay the image-pull cost."
  type        = string
  default     = "vllm/vllm-openai:latest"
}

variable "tags" {
  description = "Resource tags applied to every resource in this module, including expiry/teardown metadata (FR-088)."
  type        = map(string)
  default     = {}
}
