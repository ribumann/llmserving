terraform {
  required_version = ">= 1.7.0"

  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = "= 2.4.0"
    }
  }

  # Deliberately local for first bootstrap. Backend migration is a separate approval.
}

provider "azapi" {
  subscription_id            = var.subscription_id
  skip_provider_registration = true
  enable_preflight           = false
  disable_default_output     = true
}
