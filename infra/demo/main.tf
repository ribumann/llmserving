# Per-environment GPU demo layer (rg-llm-demo-{environmentId}).
#
# Provisions one resource group containing a private NIC (no public IP — FR-079) and one Linux
# GPU VM on infra/shared's snet-gpu, bootstrapped via the NVIDIA GPU driver extension + cloud-init
# with Docker/the NVIDIA Container Toolkit and the vLLM image pre-pulled (research.md Section 1).
# This module intentionally does NOT start vLLM with a specific model: per
# contracts/provider-interface.md's Azure Implementation Notes, `provisionEnvironment` (this
# module) and `deployRevision` are distinct operations — the model_deployment Container Apps Job
# starts vLLM later via an Azure VM Run Command, passing the Hugging Face checkpoint/token as
# transient command parameters that are never written to Terraform state (FR-082/FR-083; see
# cloud-init.tftpl's run-vllm.sh). This is the Terraform equivalent of the
# `ProviderAdapter.provisionEnvironment` contract in
# ../../specs/001-llm-serving-demo/contracts/provider-interface.md.
#
# Reads infra/shared's outputs via local state only (FR-090: a demo environment's Terraform must
# not be able to read or modify rg-llm-shared-{stage}/rg-llm-control-{stage} resources beyond the
# read-only subnet/DNS references below).

data "terraform_remote_state" "shared" {
  backend = "local"

  config = {
    path = var.shared_state_path
  }
}

locals {
  # Default VM SKU per size class, per research.md Section 4. An explicit var.vm_size always wins.
  default_vm_size_by_class = {
    small  = "Standard_NC16as_T4_v3"
    medium = "Standard_NC24ads_A100_v4"
    large  = "Standard_NC80adis_H100_v5"
  }

  vm_size = coalesce(var.vm_size, local.default_vm_size_by_class[var.profile_size_class])

  resource_group_name = "rg-llm-demo-${var.environment_id}"
  name_prefix         = "${var.name_prefix}-${var.environment_id}"

  common_tags = merge(var.tags, {
    feature       = "azure-llm-serving-demo"
    managedBy     = "terraform"
    profile       = var.profile_size_class
    environmentId = var.environment_id
  })
}

resource "azurerm_resource_group" "demo" {
  name     = local.resource_group_name
  location = data.terraform_remote_state.shared.outputs.location
  tags     = local.common_tags
}

# No public IP, no NSG (snet-gpu's NSG is defined once in infra/shared and applies to every
# environment's NIC automatically), no Bastion. The only inbound path is from other resources
# already inside vnet-llm-{stage} — Container Apps Jobs dispatch HTTP requests to port 8000
# directly over the private network.
resource "azurerm_network_interface" "demo" {
  name                = "${local.name_prefix}-nic"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  tags                = local.common_tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = data.terraform_remote_state.shared.outputs.gpu_subnet_id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "demo" {
  name                = "${local.name_prefix}-vm"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  size                = local.vm_size
  admin_username      = var.admin_username
  network_interface_ids = [
    azurerm_network_interface.demo.id,
  ]
  tags = local.common_tags

  # Spot capacity is interruptible. max_bid_price = -1 allows up to the
  # on-demand price; eviction can still occur when Azure reclaims capacity.
  priority        = "Spot"
  eviction_policy = "Deallocate"
  max_bid_price   = -1

  # Password auth intentionally disabled; SSH key only. With no public IP and no Bastion,
  # this key is only usable from inside the VNet (e.g. a future diagnostic Container Apps Job).
  disable_password_authentication = true

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 256
  }

  # Ubuntu 22.04 LTS Gen2 — Canonical's recommended base image for the NVIDIA GPU driver extension.
  source_image_reference {
    publisher = "canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  custom_data = base64encode(templatefile("${path.module}/cloud-init.tftpl", {
    vllm_image = var.vllm_image
  }))
}

# Installs the NVIDIA GPU driver required for the NC-series accelerator before the vLLM container
# (started by cloud-init) attempts to use the GPU.
#
# `settings` is required: without it the extension's public settings are empty, its install
# script defaults to InstallMethod 0 (legacy direct .deb download keyed off a DRIVER_URL setting)
# and silently fails every step (`wget` with no URL, `dpkg -i` on a nonexistent file, then
# `apt-get install cuda-drivers` with no repo ever added) — confirmed live via
# /var/log/azure/nvidia-vmext-status on both demo VMs. InstallMethod 1 instead adds NVIDIA's own
# apt repo (REPO_URL + KEY_RING) so `apt-get install cuda-drivers` can actually resolve the
# package. installCUDA is set to false because this VM only needs the driver + nvidia-container-
# toolkit for Docker GPU passthrough, not the full host-level CUDA toolkit.
resource "azurerm_virtual_machine_extension" "nvidia_driver" {
  name                       = "NvidiaGpuDriverLinux"
  virtual_machine_id         = azurerm_linux_virtual_machine.demo.id
  publisher                  = "Microsoft.HpcCompute"
  type                       = "NvidiaGpuDriverLinux"
  type_handler_version       = "1.9"
  auto_upgrade_minor_version = true
  tags                       = local.common_tags

  settings = jsonencode({
    InstallMethod = 1
    REPO_URL      = "https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/"
    PIN_URL       = "https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-ubuntu2204.pin"
    KEY_RING      = "cuda-keyring_1.1-1_all.deb"
    installCUDA   = false
  })
}
