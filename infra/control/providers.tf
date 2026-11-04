# Terraform + azurerm provider configuration for the control-plane module.
#
# infra/control owns the persistent application control plane (rg-llm-control-{stage}):
# Container Apps (React + FastAPI), Container Apps Jobs, the Durable Functions app, PostgreSQL,
# and their supporting storage/identities. It reads infra/shared's outputs via a local
# terraform_remote_state data source (see main.tf) — no Azure remote-state backend is required
# for local dev; a real deployment can add a backend_override.tf pointing both this and
# infra/shared at the same remote-state storage account without touching this file.

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.116"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    # Creates the Microsoft Entra ID app registration used for Container Apps' built-in
    # (Easy Auth) sign-in (FR-075) — the azurerm provider has no app-registration resource.
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.47"
    }
    # azurerm has no resource for Microsoft.App/containerApps/authConfigs yet; azapi provides
    # direct ARM access for that one resource (FR-075) without dropping to a manual `az` step.
    azapi = {
      source  = "azure/azapi"
      version = "~> 1.13"
    }
    # Used purely for time_sleep: Azure RBAC role assignments are eventually consistent, so a
    # Container App/Job whose own provisioning depends on a just-granted role (AcrPull, Key Vault
    # Secrets User) can still fail even when Terraform's dependency graph and depends_on already
    # sequence the role assignment first — the write succeeds before the grant has propagated to
    # the relevant data plane. See the "*_rbac_propagation" time_sleep resources below.
    time = {
      source  = "hashicorp/time"
      version = "~> 0.11"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
  }

  subscription_id = var.subscription_id
}

provider "random" {}
provider "azuread" {}
provider "azapi" {}
provider "time" {}
