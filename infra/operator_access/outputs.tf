output "vpn_gateway_id" {
  value = azurerm_virtual_network_gateway.operator.id
}

output "private_dns_server" {
  description = "Configure the VPN client profile to query this inbound resolver; do not assume Azure's 168.63.129.16 is reachable across P2S."
  value       = azurerm_private_dns_resolver_inbound_endpoint.operator.ip_configurations[0].private_ip_address
}

output "state_private_endpoint_id" {
  value = azurerm_private_endpoint.state.id
}

output "root_certificate_sha256" {
  value = var.root_certificate_sha256
}
