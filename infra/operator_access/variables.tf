variable "subscription_id" {
  type = string
  validation {
    condition     = var.subscription_id == var.operator_target.subscription_id
    error_message = "Subscription must exactly match the independently reviewed operator target."
  }
}

variable "root_certificate_public_data" {
  description = "Base64 DER public root certificate only; no PEM markers, private key or client certificate."
  type        = string
  validation {
    condition     = length(var.root_certificate_public_data) >= 128 && can(regex("^[A-Za-z0-9+/]+={0,2}$", var.root_certificate_public_data))
    error_message = "Supply only a base64-encoded public X.509 root certificate."
  }
}

variable "root_certificate_sha256" {
  description = "Independently verified lowercase SHA256 of the DER public root certificate."
  type        = string
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.root_certificate_sha256))
    error_message = "A SHA256 public-certificate fingerprint is required."
  }
}

variable "expires_at" {
  description = "Fixed UTC operator-access cleanup deadline, verified independently before apply."
  type        = string
  validation {
    condition     = can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.expires_at))
    error_message = "A fixed UTC deadline is required."
  }
}
variable "existing_resource_group_name" {
  type = string
  validation {
    condition     = var.existing_resource_group_name == var.operator_target.resource_group_name
    error_message = "Resource group must exactly match the independently reviewed operator target."
  }
}

variable "operator_target" {
  description = "Independent reviewed exact target; must match the private Python operator configuration."
  type = object({
    subscription_id     = string
    resource_group_name = string
    resource_prefix     = string
    state_account       = string
    region              = string
    target_tag          = string
    campaign_tag        = string
    expires_on          = string
  })
  validation {
    condition = (
      can(regex("^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", var.operator_target.subscription_id)) &&
      var.operator_target.subscription_id != "00000000-0000-0000-0000-000000000000" &&
      alltrue([for value in [var.operator_target.resource_group_name, var.operator_target.resource_prefix, var.operator_target.target_tag, var.operator_target.campaign_tag] : can(regex("^[a-z][a-z0-9-]{1,39}$", value))]) &&
      can(regex("^[a-z0-9]{3,24}$", var.operator_target.state_account)) &&
      can(regex("^[a-z]{3,30}$", var.operator_target.region)) &&
      can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}$", var.operator_target.expires_on))
    )
    error_message = "Supply explicit, well-formed operator target identifiers, names, region and expiry."
  }
}
