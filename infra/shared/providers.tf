# Terraform + azurerm provider configuration for the shared platform module.
#
# See ../../specs/001-llm-serving-demo/research.md Section 7 for why this module exists as a
# standalone, rarely-changing layer (rg-llm-shared-{stage}) beneath infra/control and infra/demo.

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.116"
    }
  }

  # No backend block here on purpose: local state by default, matching infra/control and
  # infra/demo. A real deployment adds a backend_override.tf (or -backend-config flags)
  # pointing at a shared remote-state storage account without touching this file.
}

provider "azurerm" {
  features {
    key_vault {
      # Dev/pilot-friendly: allow re-creating a Key Vault with the same name shortly after
      # deletion without waiting out/recovering a soft-deleted vault.
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
  }

  subscription_id = var.subscription_id
}
