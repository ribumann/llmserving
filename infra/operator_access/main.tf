locals {
  group    = var.existing_resource_group_name
  location = "italynorth"
  tags = {
    project         = "llmserving-public-validation"
    managedBy       = "copilot-release"
    target          = "personal-fallback-e2e"
    runId           = "public-release-20261105"
    expiresOn       = "2026-12-05"
    feature         = "azure-llm-serving-demo"
    component       = "operator-access"
    stage           = "release"
    cleanupAfter    = var.expires_at
    rootCertificate = var.root_certificate_sha256
  }
}

data "azurerm_resource_group" "shared" {
  name = local.group
}

data "azurerm_client_config" "current" {}

data "azurerm_virtual_network" "shared" {
  name                = "llmrelease-shared-vnet"
  resource_group_name = local.group
}

data "azurerm_subnet" "endpoints" {
  name                 = "snet-private-endpoints"
  virtual_network_name = data.azurerm_virtual_network.shared.name
  resource_group_name  = local.group
}

data "azurerm_private_dns_zone" "blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = local.group
}

resource "azurerm_subnet" "gateway" {
  name                            = "GatewaySubnet"
  resource_group_name             = local.group
  virtual_network_name            = data.azurerm_virtual_network.shared.name
  address_prefixes                = ["10.20.30.0/27"]
  default_outbound_access_enabled = false
}

resource "azurerm_public_ip" "gateway" {
  name                = "llmrelease-operator-vpn-pip"
  resource_group_name = local.group
  location            = local.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
  lifecycle {
    ignore_changes = [ip_tags, zones]
  }
}

resource "azurerm_private_dns_resolver" "operator" {
  name                = "llmrelease-operator-dns"
  resource_group_name = local.group
  location            = local.location
  virtual_network_id  = data.azurerm_virtual_network.shared.id
  tags                = local.tags
}

resource "azurerm_subnet" "dns" {
  name                            = "snet-operator-dns"
  resource_group_name             = local.group
  virtual_network_name            = data.azurerm_virtual_network.shared.name
  address_prefixes                = ["10.20.31.0/28"]
  default_outbound_access_enabled = false
  delegation {
    name = "dns-resolver"
    service_delegation {
      name    = "Microsoft.Network/dnsResolvers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_private_dns_resolver_inbound_endpoint" "operator" {
  name                    = "llmrelease-operator-dns-inbound"
  private_dns_resolver_id = azurerm_private_dns_resolver.operator.id
  location                = local.location
  ip_configurations {
    subnet_id                    = azurerm_subnet.dns.id
    private_ip_allocation_method = "Static"
    private_ip_address           = "10.20.31.4"
  }
  tags = local.tags
}

resource "azurerm_virtual_network_gateway" "operator" {
  name                = "llmrelease-operator-vpn"
  resource_group_name = local.group
  location            = local.location
  type                = "Vpn"
  vpn_type            = "RouteBased"
  sku                 = "VpnGw1AZ"
  generation          = "Generation1"
  active_active       = false
  enable_bgp          = false
  tags                = local.tags

  ip_configuration {
    name                          = "operator-vpn"
    subnet_id                     = azurerm_subnet.gateway.id
    public_ip_address_id          = azurerm_public_ip.gateway.id
    private_ip_address_allocation = "Dynamic"
  }
  vpn_client_configuration {
    address_space        = ["172.29.240.0/24"]
    vpn_client_protocols = ["OpenVPN"]
    vpn_auth_types       = ["Certificate"]
    root_certificate {
      name             = "llmrelease-operator-root"
      public_cert_data = var.root_certificate_public_data
    }
  }
}

resource "azurerm_private_endpoint" "state" {
  name                = "llmrelease-state-pe"
  resource_group_name = local.group
  location            = local.location
  subnet_id           = data.azurerm_subnet.endpoints.id
  tags                = local.tags
  private_service_connection {
    name                           = "llmrelease-state-blob"
    private_connection_resource_id = "/subscriptions/${var.subscription_id}/resourceGroups/${local.group}/providers/Microsoft.Storage/storageAccounts/llmreleasestate0ea5e6"
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "state-blob-zone-group"
    private_dns_zone_ids = [data.azurerm_private_dns_zone.blob.id]
  }
}
