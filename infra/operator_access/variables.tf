variable "subscription_id" {
  type = string
  validation {
    condition     = var.subscription_id == "86677b6e-28fc-48e4-8988-5ab9e568eece"
    error_message = "Only the isolated main subscription is supported."
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
  type    = string
  default = "rg-llmserving-e2e-shared"
  validation {
    condition     = var.existing_resource_group_name == "rg-llmserving-e2e-shared"
    error_message = "Only the retained main shared group is supported."
  }
}
