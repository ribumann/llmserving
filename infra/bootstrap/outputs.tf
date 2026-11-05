output "resource_group_name" {
  description = "Existing group, not owned by bootstrap state."
  value       = data.azapi_resource.shared.name
}

output "location" {
  value = var.location
}

output "state_account_id" {
  value = azapi_resource.state.id
}

output "state_storage_account_name" {
  value = azapi_resource.state.name
}

output "state_container_name" {
  value = azapi_resource.tfstate.name
}

output "backend_configs" {
  description = "Nonsecret candidate azurerm backend configs, not authorization or automatic migration. OIDC client identity comes from the approved environment."
  value = {
    for layer in ["bootstrap", "shared", "control"] :
    layer => merge(local.backend_config, { key = "${layer}.tfstate" })
  }
}
