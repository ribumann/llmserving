variable "subscription_id" {
  description = "Explicit target Azure subscription UUID."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a UUID."
  }
}

variable "location" {
  description = "Deployment region, independent of the retained group's metadata location."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][a-z0-9]+$", var.location))
    error_message = "location must be a nonblank lowercase Azure region identifier."
  }
}

variable "stage" {
  description = "Stage used in the shared module's subscription-stage naming suffix."
  type        = string
  default     = "dev"
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9]{2,12}$", var.stage))
    error_message = "stage must be 2-12 lowercase alphanumeric characters."
  }
}

variable "name_prefix" {
  description = "1-13 lowercase alphanumeric characters; account name appends state and a six-character suffix."
  type        = string
  default     = "llm"
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9]{1,13}$", var.name_prefix))
    error_message = "name_prefix must be 1-13 lowercase alphanumeric characters, keeping the account within 24 characters."
  }
}

variable "existing_resource_group_name" {
  description = "Required existing group, read only. Use fresh bootstrap state, never group-owning or shared/control state."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[A-Za-z0-9._()-]{1,90}$", var.existing_resource_group_name)) && !endswith(var.existing_resource_group_name, ".")
    error_message = "existing_resource_group_name must be a nonblank Azure resource group name, not ending in a period."
  }
}

variable "tags" {
  description = "Operator ownership/campaign tags on the new storage account; never applied to the retained group."
  type        = map(string)
  default     = {}
  nullable    = false
}
