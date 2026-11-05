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

resource "azurerm_resource_group" "control" {
  name     = "rg-llm-control-dev"
  location = "polandcentral"
  tags = {
    feature   = "azure-llm-serving-demo"
    component = "control"
    stage     = "dev"
    managedBy = "terraform"
  }
}

resource "azurerm_user_assigned_identity" "backend" {
  name                = "llm-backend-id"
  resource_group_name = azurerm_resource_group.control.name
  location            = "polandcentral"
  tags                = azurerm_resource_group.control.tags
}

resource "azurerm_user_assigned_identity" "jobs" {
  for_each            = toset(["terraform_runner", "model_deployment"])
  name                = "llm-job-${replace(each.key, "_", "-")}-id"
  resource_group_name = azurerm_resource_group.control.name
  location            = "polandcentral"
  tags                = azurerm_resource_group.control.tags
}

resource "azurerm_role_assignment" "backend_contributor" {
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

resource "azurerm_role_assignment" "terraform_runner_contributor" {
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.jobs["terraform_runner"].principal_id
}

resource "azurerm_role_assignment" "model_deployment_vm_contributor" {
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Virtual Machine Contributor"
  principal_id         = azurerm_user_assigned_identity.jobs["model_deployment"].principal_id
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

output "group_id" {
  value = azurerm_resource_group.control.id
}

output "role_ids" {
  value = {
    backend          = azurerm_role_assignment.backend_contributor.id
    terraform_runner = azurerm_role_assignment.terraform_runner_contributor.id
    model_deployment = azurerm_role_assignment.model_deployment_vm_contributor.id
  }
}
