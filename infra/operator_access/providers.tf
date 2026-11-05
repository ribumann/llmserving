terraform {
  required_version = "= 1.16.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 3.117.1"
    }
  }
}

provider "azurerm" {
  subscription_id            = var.subscription_id
  skip_provider_registration = true
  features {}
}
