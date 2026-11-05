terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.116"
    }
  }
}

variable "subscription_id" {
  type = string
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

resource "azurerm_resource_group" "shared" {
  name     = "rg-llm-shared-dev"
  location = "polandcentral"
  tags = {
    feature   = "azure-llm-serving-demo"
    component = "shared"
    stage     = "dev"
    managedBy = "terraform"
  }
}

output "resource_group_id" {
  value = azurerm_resource_group.shared.id
}
