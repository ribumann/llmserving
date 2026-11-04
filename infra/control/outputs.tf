output "resource_group_name" {
  value = azurerm_resource_group.control.name
}

output "container_app_environment_id" {
  value = azurerm_container_app_environment.control.id
}

output "backend_fqdn" {
  value = azurerm_container_app.backend.ingress[0].fqdn
}

output "frontend_fqdn" {
  value = azurerm_container_app.frontend.ingress[0].fqdn
}

output "acr_login_server" {
  description = "Convenience passthrough of infra/shared's ACR — push images here (`az acr build`)."
  value       = local.shared.acr_login_server
}

output "job_names" {
  description = "Container Apps Job names, keyed by workload — used by functions/ to dispatch job runs."
  value       = { for k, j in azurerm_container_app_job.jobs : k => j.name }
}

output "functions_app_name" {
  value = azurerm_linux_function_app.orchestrator.name
}

output "functions_app_hostname" {
  value = azurerm_linux_function_app.orchestrator.default_hostname
}

output "postgres_fqdn" {
  value = azurerm_postgresql_flexible_server.control.fqdn
}

output "database_url" {
  value     = local.database_url
  sensitive = true
}

output "tfstate_storage_account_name" {
  value = azapi_resource.tfstate_storage.name
}

output "tfstate_container_name" {
  value = azapi_resource.tfstate_container.name
}

output "artifacts_storage_account_name" {
  value = azapi_resource.artifacts_storage.name
}

output "sso_application_client_id" {
  value = var.enable_sso ? azuread_application.sso[0].client_id : null
}
