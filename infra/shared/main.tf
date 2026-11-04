# infra/shared: the rarely-changing platform layer (rg-llm-shared-{stage}) beneath the Baseline
# Azure Pilot Architecture (specs/001-llm-serving-demo/plan.md Target Platform,
# research.md Section 7, spec.md FR-074/FR-090).
#
# Owns: the VNet + subnets every other layer plugs into, private DNS zones, a NAT Gateway for
# stable Container Apps/Functions egress, the shared Container Registry, the shared Key Vault
# (platform/DB secrets — never presenter-supplied Hugging Face credentials, FR-082), and the
# shared Log Analytics workspace + Application Insights every other layer sends telemetry to
# (FR-086). Applied once per stage; never touched by a per-environment infra/demo apply (FR-090).

locals {
  resource_group_name = "rg-llm-shared-${var.stage}"

  common_tags = merge(var.tags, {
    feature   = "azure-llm-serving-demo"
    component = "shared"
    stage     = var.stage
    managedBy = "terraform"
  })

  # Globally-unique resource names (ACR, Key Vault, Storage) get a short suffix derived from the
  # resource group id so re-running this module for a second stage/subscription never collides.
  unique_suffix = substr(md5("${var.subscription_id}-${var.stage}"), 0, 6)
}

resource "azurerm_resource_group" "shared" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.common_tags
}

# --- Networking ---

resource "azurerm_virtual_network" "shared" {
  name                = "${var.name_prefix}-shared-vnet"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  address_space       = var.vnet_address_space
  tags                = local.common_tags
}

resource "azurerm_subnet" "containerapps" {
  name                 = "snet-containerapps"
  resource_group_name  = azurerm_resource_group.shared.name
  virtual_network_name = azurerm_virtual_network.shared.name
  address_prefixes     = [var.container_apps_subnet_prefix]

  # Explicit (not the provider's true default) to match Azure's actual behavior for subnets
  # created after platform-wide default-outbound-access deprecation, and this architecture's own
  # intent: egress is via the NAT Gateway association below, never a subnet's implicit default
  # outbound path. Leaving this unset caused `terraform plan` to want to destroy/recreate every
  # subnet (false -> true "forces replacement") even with zero real config drift.
  default_outbound_access_enabled = false

  delegation {
    name = "containerAppsDelegation"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "functions" {
  name                 = "snet-functions"
  resource_group_name  = azurerm_resource_group.shared.name
  virtual_network_name = azurerm_virtual_network.shared.name
  address_prefixes     = [var.functions_subnet_prefix]

  # See snet-containerapps' comment above for why this is explicit.
  default_outbound_access_enabled = false

  delegation {
    name = "functionsDelegation"
    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

resource "azurerm_subnet" "data" {
  name                 = "snet-data"
  resource_group_name  = azurerm_resource_group.shared.name
  virtual_network_name = azurerm_virtual_network.shared.name
  address_prefixes     = [var.data_subnet_prefix]

  # See snet-containerapps' comment above for why this is explicit.
  default_outbound_access_enabled = false

  delegation {
    name = "postgresDelegation"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
      ]
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                 = "snet-private-endpoints"
  resource_group_name  = azurerm_resource_group.shared.name
  virtual_network_name = azurerm_virtual_network.shared.name
  address_prefixes     = [var.private_endpoints_subnet_prefix]

  # See snet-containerapps' comment above for why this is explicit.
  default_outbound_access_enabled = false
}

# Hosts each demo environment's GPU VM NIC (infra/demo). No public IP is ever attached here
# (FR-079) — reachability is limited to snet-containerapps by NSG rule below.
resource "azurerm_subnet" "gpu" {
  name                 = "snet-gpu"
  resource_group_name  = azurerm_resource_group.shared.name
  virtual_network_name = azurerm_virtual_network.shared.name
  address_prefixes     = [var.gpu_subnet_prefix]

  # See snet-containerapps' comment above for why this is explicit.
  default_outbound_access_enabled = false
}

resource "azurerm_network_security_group" "gpu" {
  name                = "${var.name_prefix}-gpu-nsg"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  tags                = local.common_tags

  # vLLM's OpenAI-compatible port, reachable only from the Container Apps subnet (where
  # Container Apps Jobs and the FastAPI control plane run) — never from the public internet, an
  # operator's own IP, or any other subnet (FR-079).
  security_rule {
    name                       = "AllowVllmFromContainerApps"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8000"
    source_address_prefix      = var.container_apps_subnet_prefix
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "gpu" {
  subnet_id                 = azurerm_subnet.gpu.id
  network_security_group_id = azurerm_network_security_group.gpu.id
}

# Stable, predictable outbound IP for Container Apps/Functions (reaching Hugging Face Hub, PyPI,
# the Terraform registry, etc.) — mirrors the old app-host NAT Gateway pattern.
resource "azurerm_public_ip" "nat" {
  name                = "${var.name_prefix}-shared-nat-pip"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.common_tags

  lifecycle {
    ignore_changes = [ip_tags, zones]
  }
}

resource "azurerm_nat_gateway" "shared" {
  name                = "${var.name_prefix}-shared-natgw"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  sku_name            = "Standard"
  tags                = local.common_tags
}

resource "azurerm_nat_gateway_public_ip_association" "shared" {
  nat_gateway_id       = azurerm_nat_gateway.shared.id
  public_ip_address_id = azurerm_public_ip.nat.id
}

resource "azurerm_subnet_nat_gateway_association" "containerapps" {
  subnet_id      = azurerm_subnet.containerapps.id
  nat_gateway_id = azurerm_nat_gateway.shared.id
}

resource "azurerm_subnet_nat_gateway_association" "functions" {
  subnet_id      = azurerm_subnet.functions.id
  nat_gateway_id = azurerm_nat_gateway.shared.id
}

# snet-gpu disables default outbound access (see its resource comment above) but was never given
# a replacement egress path, so the demo GPU VM's cloud-init (infra/demo/cloud-init.tftpl) could
# never reach azure.archive.ubuntu.com/get.docker.com/Hugging Face — every deploy attempt failed
# because Docker itself was never installed, not because of any application-level bug. Inbound
# stays locked down to snet-containerapps only (azurerm_network_security_group.gpu below); this
# only restores outbound.
resource "azurerm_subnet_nat_gateway_association" "gpu" {
  subnet_id      = azurerm_subnet.gpu.id
  nat_gateway_id = azurerm_nat_gateway.shared.id
}

# --- Private DNS zones (linked to the shared VNet; consumed by infra/control's private
# endpoints for PostgreSQL/Key Vault/Storage) ---

resource "azurerm_private_dns_zone" "postgres" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.shared.name
  tags                = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "${var.name_prefix}-postgres-link"
  resource_group_name   = azurerm_resource_group.shared.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.shared.id
  tags                  = local.common_tags
}

resource "azurerm_private_dns_zone" "vault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = azurerm_resource_group.shared.name
  tags                = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "vault" {
  name                  = "${var.name_prefix}-vault-link"
  resource_group_name   = azurerm_resource_group.shared.name
  private_dns_zone_name = azurerm_private_dns_zone.vault.name
  virtual_network_id    = azurerm_virtual_network.shared.id
  tags                  = local.common_tags
}

resource "azurerm_private_dns_zone" "blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.shared.name
  tags                = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "blob" {
  name                  = "${var.name_prefix}-blob-link"
  resource_group_name   = azurerm_resource_group.shared.name
  private_dns_zone_name = azurerm_private_dns_zone.blob.name
  virtual_network_id    = azurerm_virtual_network.shared.id
  tags                  = local.common_tags
}

# Durable Functions' task hub uses Queue + Table storage in addition to Blob; all three need a
# private endpoint because this architecture disables public storage network access.

resource "azurerm_private_dns_zone" "queue" {
  name                = "privatelink.queue.core.windows.net"
  resource_group_name = azurerm_resource_group.shared.name
  tags                = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "queue" {
  name                  = "${var.name_prefix}-queue-link"
  resource_group_name   = azurerm_resource_group.shared.name
  private_dns_zone_name = azurerm_private_dns_zone.queue.name
  virtual_network_id    = azurerm_virtual_network.shared.id
  tags                  = local.common_tags
}

resource "azurerm_private_dns_zone" "table" {
  name                = "privatelink.table.core.windows.net"
  resource_group_name = azurerm_resource_group.shared.name
  tags                = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "table" {
  name                  = "${var.name_prefix}-table-link"
  resource_group_name   = azurerm_resource_group.shared.name
  private_dns_zone_name = azurerm_private_dns_zone.table.name
  virtual_network_id    = azurerm_virtual_network.shared.id
  tags                  = local.common_tags
}

# --- Container Registry ---
# Pulled via managed identity + AcrPull (infra/control), never admin credentials — same pattern
# as the superseded infra/app-host module. Registry access uses its public endpoint;
# every consumer authenticates via Entra ID.

resource "azurerm_container_registry" "shared" {
  name                = "${replace(var.name_prefix, "-", "")}acr${local.unique_suffix}"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.common_tags
}

# --- Key Vault ---
# Platform/DB secrets only (FR-082 excludes presenter Hugging Face credentials from ever landing
# here). RBAC-authorized; reached over a private endpoint from infra/control's Container Apps
# environment / Functions app via their managed identities.

resource "azurerm_key_vault" "shared" {
  name                = "${var.name_prefix}-kv-${local.unique_suffix}"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = var.key_vault_sku
  tags                = local.common_tags

  enable_rbac_authorization     = true
  public_network_access_enabled = length(var.key_vault_allowed_ip_ranges) > 0
  soft_delete_retention_days    = 7
  purge_protection_enabled      = false

  dynamic "network_acls" {
    # Only rendered while an exception is open (see var.key_vault_allowed_ip_ranges); the vault
    # is otherwise fully private (public_network_access_enabled = false above), reachable only
    # via azurerm_private_endpoint.vault.
    for_each = length(var.key_vault_allowed_ip_ranges) > 0 ? [1] : []
    content {
      default_action = "Deny"
      bypass         = "AzureServices"
      ip_rules       = var.key_vault_allowed_ip_ranges
    }
  }
}

resource "azurerm_private_endpoint" "vault" {
  name                = "${var.name_prefix}-vault-pe"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.common_tags

  private_service_connection {
    name                           = "${var.name_prefix}-vault-psc"
    private_connection_resource_id = azurerm_key_vault.shared.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "vault-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.vault.id]
  }
}

data "azurerm_client_config" "current" {}

# --- Observability ---
# Every other layer (Container Apps, Durable Functions, Container Apps Jobs, the GPU VM) sends
# logs to this workspace and telemetry/traces to this Application Insights resource, carrying
# the same correlation/workflow ID end-to-end (FR-086).

resource "azurerm_log_analytics_workspace" "shared" {
  name                = "${var.name_prefix}-law"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = local.common_tags
}

resource "azurerm_application_insights" "shared" {
  name                = "${var.name_prefix}-appi"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  workspace_id        = azurerm_log_analytics_workspace.shared.id
  application_type    = "web"
  tags                = local.common_tags
}
