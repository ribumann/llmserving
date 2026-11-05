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

data "terraform_remote_state" "shared" {
  backend = "local"
  config = {
    path = "unused-overridden-test-state.tfstate"
  }
}

resource "azurerm_container_app_environment" "control" {
  name                               = "llm-cae"
  resource_group_name                = "rg-llm-control-dev"
  location                           = "polandcentral"
  log_analytics_workspace_id         = data.terraform_remote_state.shared.outputs.log_analytics_workspace_id
  infrastructure_subnet_id           = data.terraform_remote_state.shared.outputs.container_apps_subnet_id
  infrastructure_resource_group_name = "rg-existing-platform"
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
  tags = {
    feature   = "azure-llm-serving-demo"
    component = "control"
    stage     = "dev"
    managedBy = "terraform"
  }
}

output "environment_id" {
  value = azurerm_container_app_environment.control.id
}
