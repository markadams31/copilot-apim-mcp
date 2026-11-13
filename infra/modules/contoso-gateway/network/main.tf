# ---------------------------------------------------------------------------
# Private network: nothing in the secure profile has a public data-plane endpoint.
#
#   VPN client (laptop) ──P2S──▶ GatewaySubnet
#        │ DNS: forwarder VM (snet-infra) → Azure DNS + private zones
#        ▼
#   APIM (internal VNet mode, snet-apim) ──443──▶ Function private endpoint (snet-pe)
#                                                   Function (VNet-integrated, snet-func)
#                                                     ├─1433─▶ SQL private endpoint (snet-pe)
#                                                     ├─443──▶ Storage private endpoints (snet-pe)
#                                                     └─NAT──▶ Entra ID / Graph (internet)
# ---------------------------------------------------------------------------

locals {
  vnet_cidr       = "10.40.0.0/16"
  vpn_client_pool = var.settings.vpn_client_pool
  snet = {
    apim  = "10.40.1.0/27"   # APIM (classic internal mode; no delegation allowed)
    func  = "10.40.2.0/27"   # Function outbound VNet integration (delegated)
    pe    = "10.40.3.0/27"   # Private endpoints for Function, SQL, Storage
    infra = "10.40.4.0/27"   # DNS forwarder
    gw    = "10.40.255.0/27" # VPN gateway (name must be GatewaySubnet)
  }
  dns_forwarder_ip = cidrhost(local.snet.infra, 4)
}

resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-${var.prefix}-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  address_space       = [local.vnet_cidr]
}

resource "azurerm_subnet" "apim" {
  name                 = "snet-apim"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [local.snet.apim]
}

resource "azurerm_subnet" "func" {
  name                 = "snet-func"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [local.snet.func]
  delegation {
    name = "flex"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "pe" {
  name                 = "snet-pe"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [local.snet.pe]
  # Without this, NSG rules are ignored for private endpoints and the subnet is open to the VNet.
  private_endpoint_network_policies = "Enabled"
}

resource "azurerm_subnet" "infra" {
  name                 = "snet-infra"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [local.snet.infra]
}

# ---- Explicit egress: one NAT gateway, one known public IP --------------------------------
# New VNets no longer get implicit "default outbound access", and an allow-listable egress IP is
# what enterprise firewalls expect. Needed for Entra ID (token validation, OBO), Graph, Azure Monitor.

resource "azurerm_public_ip" "nat" {
  name                = "pip-nat-${var.prefix}-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_nat_gateway" "nat" {
  name                = "nat-${var.prefix}-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku_name            = "Standard"
}

resource "azurerm_nat_gateway_public_ip_association" "nat" {
  nat_gateway_id       = azurerm_nat_gateway.nat.id
  public_ip_address_id = azurerm_public_ip.nat.id
}

resource "azurerm_subnet_nat_gateway_association" "egress" {
  for_each = {
    apim  = azurerm_subnet.apim.id
    func  = azurerm_subnet.func.id
    infra = azurerm_subnet.infra.id
  }
  subnet_id      = each.value
  nat_gateway_id = azurerm_nat_gateway.nat.id
}

# ---- NSGs ------------------------------------------------------------------------------------

resource "azurerm_network_security_group" "apim" {
  name                = "nsg-apim-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location

  # Minimum rules for classic APIM in internal mode (management plane + internal load balancer).
  security_rule {
    name                       = "apim-management"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = "ApiManagement"
    source_port_range          = "*"
    destination_address_prefix = "VirtualNetwork"
    destination_port_range     = "3443"
  }
  security_rule {
    name                       = "azure-load-balancer"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = "AzureLoadBalancer"
    source_port_range          = "*"
    destination_address_prefix = "VirtualNetwork"
    destination_port_range     = "6390"
  }
  # Clients: anything inside the network (incl. VPN users and Power Platform's delegated subnets).
  security_rule {
    name                       = "clients-https"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefixes    = [local.vnet_cidr, local.vpn_client_pool, local.pp_secondary_cidr]
    source_port_range          = "*"
    destination_address_prefix = local.snet.apim
    destination_port_range     = "443"
  }
}

# Private endpoints only accept the flows the architecture needs. In particular the Function is
# reachable from APIM only, so an agent can't skip APIM's per-agent authorization even from inside.
resource "azurerm_network_security_group" "pe" {
  name                = "nsg-pe-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location

  security_rule {
    name                       = "apim-to-function"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = local.snet.apim
    source_port_range          = "*"
    destination_address_prefix = local.snet.pe
    destination_port_range     = "443"
  }
  security_rule {
    name                       = "function-to-storage"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = local.snet.func
    source_port_range          = "*"
    destination_address_prefix = local.snet.pe
    destination_port_range     = "443"
  }
  security_rule {
    name                       = "function-to-sql"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = local.snet.func
    source_port_range          = "*"
    destination_address_prefix = local.snet.pe
    destination_port_ranges    = ["1433", "11000-11999"] # 11000+ if SQL uses Redirect
  }
  dynamic "security_rule" {
    for_each = var.settings.allow_vpn_to_backends ? [1] : []
    content {
      name                       = "vpn-deploy-window"
      priority                   = 200
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_address_prefix      = local.vpn_client_pool
      source_port_range          = "*"
      destination_address_prefix = local.snet.pe
      # 443: code deploys (Kudu, storage). 1433 + 11000-11999: admin SQL (the scripts/sql-*.py tools).
      destination_port_ranges = ["443", "1433", "11000-11999"]
    }
  }
  security_rule {
    name                       = "deny-everything-else"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_address_prefix      = "*"
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "*"
  }
}

resource "azurerm_network_security_group" "infra" {
  name                = "nsg-infra-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location

  security_rule {
    name                       = "dns"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*" # UDP and TCP 53
    source_address_prefixes    = [local.vnet_cidr, local.vpn_client_pool]
    source_port_range          = "*"
    destination_address_prefix = local.dns_forwarder_ip
    destination_port_range     = "53"
  }
  # No SSH: the VM is managed with `az vm run-command`, which needs no inbound port.
  security_rule {
    name                       = "deny-vnet-else"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_address_prefix      = "VirtualNetwork"
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "nsg" {
  for_each = {
    apim  = { subnet = azurerm_subnet.apim.id, nsg = azurerm_network_security_group.apim.id }
    pe    = { subnet = azurerm_subnet.pe.id, nsg = azurerm_network_security_group.pe.id }
    infra = { subnet = azurerm_subnet.infra.id, nsg = azurerm_network_security_group.infra.id }
  }
  subnet_id                 = each.value.subnet
  network_security_group_id = each.value.nsg
}

# ---- Private DNS -------------------------------------------------------------------------------

locals {
  private_zones = {
    sites = "privatelink.azurewebsites.net"
    sql   = "privatelink.database.windows.net"
    blob  = "privatelink.blob.core.windows.net"
    queue = "privatelink.queue.core.windows.net"
    table = "privatelink.table.core.windows.net"
  }
}

resource "azurerm_private_dns_zone" "pl" {
  for_each            = local.private_zones
  name                = each.value
  resource_group_name = var.resource_group_name
}

resource "azurerm_private_dns_zone_virtual_network_link" "pl" {
  for_each              = local.private_zones
  name                  = "link-${each.key}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.pl[each.key].name
  virtual_network_id    = azurerm_virtual_network.vnet.id
}

# Internal-mode APIM isn't in public DNS. Microsoft's guidance: a zone scoped to the instance's own
# FQDN, never a zone for the whole azure-api.net (that would hijack every other APIM's name).
resource "azurerm_private_dns_zone" "apim" {
  name                = var.apim_hostname
  resource_group_name = var.resource_group_name
}

resource "azurerm_private_dns_a_record" "apim" {
  name                = "@"
  zone_name           = azurerm_private_dns_zone.apim.name
  resource_group_name = var.resource_group_name
  ttl                 = 300
  records             = var.apim_private_ips
}

resource "azurerm_private_dns_zone_virtual_network_link" "apim" {
  name                  = "link-apim"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.apim.name
  virtual_network_id    = azurerm_virtual_network.vnet.id
}

# ---- Private endpoints -------------------------------------------------------------------------

resource "azurerm_private_endpoint" "pe" {
  for_each            = var.private_endpoint_targets
  name                = "pe-${each.key}-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = azurerm_subnet.pe.id

  private_service_connection {
    name                           = "psc-${each.key}"
    private_connection_resource_id = each.value.id
    subresource_names              = [each.value.subresource]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.pl[each.value.zone].id]
  }
}
