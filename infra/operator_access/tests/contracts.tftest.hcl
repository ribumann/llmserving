mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      subscription_id = "11111111-1111-4111-8111-111111111111"
      tenant_id       = "22222222-2222-4222-8222-222222222222"
    }
  }
  mock_data "azurerm_virtual_network" {
    defaults = {
      name = "llmexample-shared-vnet"
      id   = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-example-shared/providers/Microsoft.Network/virtualNetworks/llmexample-shared-vnet"
    }
  }
  mock_data "azurerm_subnet" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-example-shared/providers/Microsoft.Network/virtualNetworks/llmexample-shared-vnet/subnets/snet-private-endpoints"
    }
  }
  mock_data "azurerm_private_dns_zone" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-example-shared/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
    }
  }
}

variables {
  existing_resource_group_name = "rg-example-shared"
  operator_target = {
    subscription_id     = "11111111-1111-4111-8111-111111111111"
    resource_group_name = "rg-example-shared"
    resource_prefix     = "llmexample"
    state_account       = "examplestate123abc"
    region              = "italynorth"
    target_tag          = "example-isolated-e2e"
    campaign_tag        = "example-release"
    expires_on          = "2030-01-01"
  }
  subscription_id              = "11111111-1111-4111-8111-111111111111"
  root_certificate_public_data = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFB"
  root_certificate_sha256      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  expires_at                   = "2030-01-01T00:00:00Z"
}

run "private_operator_scope" {
  command = plan
  assert {
    condition     = azurerm_virtual_network_gateway.operator.sku == "VpnGw1AZ" && azurerm_virtual_network_gateway.operator.vpn_type == "RouteBased" && !azurerm_virtual_network_gateway.operator.enable_bgp && !azurerm_virtual_network_gateway.operator.active_active
    error_message = "Gateway must remain the bounded single route-based VpnGw1AZ."
  }
  assert {
    condition     = toset(azurerm_virtual_network_gateway.operator.vpn_client_configuration[0].vpn_auth_types) == toset(["Certificate"]) && toset(azurerm_virtual_network_gateway.operator.vpn_client_configuration[0].vpn_client_protocols) == toset(["OpenVPN"])
    error_message = "Only certificate/OpenVPN authentication is permitted."
  }
  assert {
    condition     = azurerm_private_endpoint.state.private_service_connection[0].subresource_names == tolist(["blob"]) && !azurerm_private_endpoint.state.private_service_connection[0].is_manual_connection
    error_message = "State endpoint must select only blob without manual/foreign target."
  }
  assert {
    condition     = azurerm_private_dns_resolver_inbound_endpoint.operator.ip_configurations[0].private_ip_address == "10.20.31.4" && azurerm_private_dns_resolver_inbound_endpoint.operator.ip_configurations[0].private_ip_allocation_method == "Static"
    error_message = "VPN profile must have the verified static private DNS inbound address."
  }
  assert {
    condition     = azurerm_subnet.gateway.name == "GatewaySubnet" && azurerm_subnet.gateway.address_prefixes == tolist(["10.20.30.0/27"]) && azurerm_subnet.dns.address_prefixes == tolist(["10.20.31.0/28"])
    error_message = "Operator subnets must not change existing shared subnet ranges."
  }
}

run "reject_foreign_subscription" {
  command = plan
  variables {
    subscription_id = "00000000-0000-0000-0000-000000000000"
  }
  expect_failures = [var.subscription_id]
}

run "reject_private_key_input" {
  command = plan
  variables {
    root_certificate_public_data = "-----BEGIN PRIVATE KEY-----"
  }
  expect_failures = [var.root_certificate_public_data]
}

run "reject_missing_fingerprint" {
  command = plan
  variables {
    root_certificate_sha256 = ""
  }
  expect_failures = [var.root_certificate_sha256]
}
