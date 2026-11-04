output "resource_group_name" {
  description = "The rg-llm-shared-{stage} resource group name."
  value       = azurerm_resource_group.shared.name
}

output "location" {
  description = "Azure region shared by every layer."
  value       = azurerm_resource_group.shared.location
}

output "vnet_id" {
  description = "Shared VNet ID, consumed by infra/control and infra/demo."
  value       = azurerm_virtual_network.shared.id
}

output "vnet_name" {
  value = azurerm_virtual_network.shared.name
}

output "container_apps_subnet_id" {
  description = "snet-containerapps ID — delegated to Microsoft.App/environments (infra/control's Container Apps environment)."
  value       = azurerm_subnet.containerapps.id
}

output "container_apps_subnet_prefix" {
  value = var.container_apps_subnet_prefix
}

output "functions_subnet_id" {
  description = "snet-functions ID — delegated to Microsoft.Web/serverFarms (infra/control's Durable Functions app VNet Integration)."
  value       = azurerm_subnet.functions.id
}

output "data_subnet_id" {
  description = "snet-data ID — delegated to Microsoft.DBforPostgreSQL/flexibleServers (infra/control's private-access PostgreSQL)."
  value       = azurerm_subnet.data.id
}

output "private_endpoints_subnet_id" {
  description = "snet-private-endpoints ID — hosts Key Vault/Storage private endpoints (shared and infra/control)."
  value       = azurerm_subnet.private_endpoints.id
}

output "gpu_subnet_id" {
  description = "snet-gpu ID — hosts each infra/demo environment's GPU VM NIC."
  value       = azurerm_subnet.gpu.id
}

output "postgres_private_dns_zone_id" {
  value = azurerm_private_dns_zone.postgres.id
}

output "postgres_private_dns_zone_name" {
  value = azurerm_private_dns_zone.postgres.name
}

output "vault_private_dns_zone_id" {
  value = azurerm_private_dns_zone.vault.id
}

output "blob_private_dns_zone_id" {
  value = azurerm_private_dns_zone.blob.id
}

output "queue_private_dns_zone_id" {
  value = azurerm_private_dns_zone.queue.id
}

output "table_private_dns_zone_id" {
  value = azurerm_private_dns_zone.table.id
}

output "acr_id" {
  value = azurerm_container_registry.shared.id
}

output "acr_login_server" {
  value = azurerm_container_registry.shared.login_server
}

output "acr_name" {
  value = azurerm_container_registry.shared.name
}

output "key_vault_id" {
  value = azurerm_key_vault.shared.id
}

output "key_vault_uri" {
  value = azurerm_key_vault.shared.vault_uri
}

output "key_vault_name" {
  value = azurerm_key_vault.shared.name
}

output "log_analytics_workspace_id" {
  value = azurerm_log_analytics_workspace.shared.id
}

output "log_analytics_workspace_name" {
  value = azurerm_log_analytics_workspace.shared.name
}

output "application_insights_id" {
  value = azurerm_application_insights.shared.id
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.shared.connection_string
  sensitive = true
}

output "nat_gateway_public_ip" {
  description = "Stable outbound IP for Container Apps/Functions egress traffic."
  value       = azurerm_public_ip.nat.ip_address
}
