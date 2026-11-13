# ---------------------------------------------------------------------------
# Copilot Studio -> private APIM, via Power Platform VNet support (subnet delegation).
#
# Copilot Studio is SaaS. Its custom connectors (which is what an MCP tool is underneath) run in a
# subnet you delegate to Power Platform, so their calls to APIM stay on your network. Requirements:
#   - Two delegated subnets, one per region of the Power Platform geography (Australia:
#     australiaeast + australiasoutheast), each able to reach APIM: here, peered VNets.
#   - An enterprise policy (kind NetworkInjection) naming both subnets. The parent module links it to
#     the environment (powerplatform_enterprise_policy).
#   - The environment is a Managed Environment; its users need an E5-class licence.
#   - Only API calls use the VNet. OAuth/token calls to Entra stay public.
# ---------------------------------------------------------------------------

locals {
  pp_secondary_cidr = "10.41.0.0/16"
  pp_subnet = {
    primary   = "10.40.5.0/26"
    secondary = "10.41.1.0/26"
  }
}

resource "azurerm_subnet" "pp_primary" {
  name                 = "snet-powerplatform"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [local.pp_subnet.primary]
  delegation {
    name = "powerplatform"
    service_delegation {
      name    = "Microsoft.PowerPlatform/enterprisePolicies"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"] # Azure adds this anyway
    }
  }
}

resource "azurerm_virtual_network" "pp_secondary" {
  name                = "vnet-${var.prefix}-pp2-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.settings.power_platform_secondary_location
  address_space       = [local.pp_secondary_cidr]
}

resource "azurerm_subnet" "pp_secondary" {
  name                 = "snet-powerplatform"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.pp_secondary.name
  address_prefixes     = [local.pp_subnet.secondary]
  delegation {
    name = "powerplatform"
    service_delegation {
      name    = "Microsoft.PowerPlatform/enterprisePolicies"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"] # Azure adds this anyway
    }
  }
}

# Power Platform may run the connector in either region, so both must reach APIM.
resource "azurerm_virtual_network_peering" "main_to_secondary" {
  name                      = "to-pp2"
  resource_group_name       = var.resource_group_name
  virtual_network_name      = azurerm_virtual_network.vnet.name
  remote_virtual_network_id = azurerm_virtual_network.pp_secondary.id
  allow_forwarded_traffic   = false
}

resource "azurerm_virtual_network_peering" "secondary_to_main" {
  name                      = "to-main"
  resource_group_name       = var.resource_group_name
  virtual_network_name      = azurerm_virtual_network.pp_secondary.name
  remote_virtual_network_id = azurerm_virtual_network.vnet.id
  allow_forwarded_traffic   = false
}

# Delegated subnets resolve with their VNet's DNS, so the secondary VNet needs APIM's name too.
resource "azurerm_private_dns_zone_virtual_network_link" "apim_secondary" {
  name                  = "link-apim-pp2"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.apim.name
  virtual_network_id    = azurerm_virtual_network.pp_secondary.id
}

resource "azapi_resource" "pp_network_policy" {
  type      = "Microsoft.PowerPlatform/enterprisePolicies@2020-10-30-preview"
  name      = "ep-${var.prefix}-vnet-${var.suffix}"
  parent_id = var.resource_group_id
  location  = "australia" # the Power Platform geography, not an Azure region

  response_export_values = ["properties.systemId"]

  body = {
    kind = "NetworkInjection"
    properties = {
      networkInjection = {
        virtualNetworks = [
          { id = azurerm_virtual_network.vnet.id, subnet = { name = azurerm_subnet.pp_primary.name } },
          { id = azurerm_virtual_network.pp_secondary.id, subnet = { name = azurerm_subnet.pp_secondary.name } },
        ]
      }
    }
  }
}
