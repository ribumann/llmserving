output "resource_group_name" {
  value = local.resource_group_name
}

output "vm_id" {
  value = azurerm_linux_virtual_machine.demo.id
}

output "vm_name" {
  value = azurerm_linux_virtual_machine.demo.name
}

output "private_ip_address" {
  description = "Private IP of the GPU VM's NIC — Container Apps Jobs reach the vLLM endpoint at http://<this>:8000 over the VNet."
  value       = azurerm_network_interface.demo.private_ip_address
}

output "vllm_endpoint" {
  value = "http://${azurerm_network_interface.demo.private_ip_address}:8000"
}
