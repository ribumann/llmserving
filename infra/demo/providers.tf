# Terraform + azurerm provider configuration for the per-environment demo GPU module.
#
# Applied/destroyed once PER Demo Environment (a Container Apps Job dispatched by the
# terraform_runner workload — infra/control — runs this, not an operator's own machine).
# Reads infra/shared's outputs via a local terraform_remote_state data source for the VNet/
# subnet it plugs into; touches nothing in rg-llm-shared-{stage} or rg-llm-control-{stage}
# (FR-090).

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.2"
    }
  }

  # The runner transfers state to/from private blobs with its managed identity.
  # This is not Terraform remote-backend locking; independent lease/recovery
  # validation remains required before unattended billable provisioning.
}

provider "azurerm" {
  features {}

  subscription_id = var.subscription_id
}
