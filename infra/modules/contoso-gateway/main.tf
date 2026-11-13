# ---------------------------------------------------------------------------
# Contoso agent tool gateway: Copilot Studio agents reach Contoso's internal systems through one
# governed front door (Azure API Management). See docs/architecture.md.
#
# This module builds the whole solution. One input, var.private_networking, decides the network shape;
# the locals below derive every network setting from it, in one place.
# ---------------------------------------------------------------------------

locals {
  # ---- The network, decided once --------------------------------------------------------------------
  private_networking = var.private_networking != null

  # Backend and database public access: off with private networking, unless overridden for debugging.
  public_network_access = coalesce(var.public_network_access, !local.private_networking)

  # Internal VNet mode needs a classic tier; without private networking a v2 tier provisions in minutes.
  apim_internal = local.private_networking
  apim_sku      = coalesce(var.apim_sku, local.private_networking ? "Developer" : "BasicV2")

  # Power Platform runs the connectors in our VNet only when there is one.
  link_power_platform = local.private_networking

  # The network module's outputs, or null in the rapid profile. Each is read on its own: referring to the
  # whole module would make everything here wait for every resource in it, which is a cycle (the network
  # also needs API Management's address).
  net = {
    apim_subnet_id                  = local.private_networking ? module.network[0].apim_subnet_id : null
    function_subnet_id              = local.private_networking ? module.network[0].function_subnet_id : null
    power_platform_policy_system_id = local.private_networking ? module.network[0].power_platform_policy_system_id : null
    dns_forwarder_ip                = local.private_networking ? module.network[0].dns_forwarder_ip : null
    vpn                             = local.private_networking ? module.network[0].vpn : null
  }

  # ---- MCP servers, agents and tools ------------------------------------------------------------------
  # An MCP server groups the tools of one business domain, so each tool is defined once. An agent is a
  # client app (its Copilot Studio connectors' identity) and lists the servers it uses; it gets one
  # connector per server, all on its own client app. A server accepts the apps of every agent that uses
  # it, and lists all of its tools to each of them; the API policy's allow-list still decides, per agent,
  # which tool it may call. Tool names are OpenAPI operationIds; which APIM API each lives on is
  # local.tool_api.
  server_definitions = {
    directory = {
      tools = ["directory_get_my_profile"]
    }
    finance = {
      tools = [
        "finance_list_cost_centres",
        "finance_query_spend",
        "budgeting_get_forecast",
        "budgeting_update_cost_centre_forecast",
      ]
    }
  }

  agent_definitions = {
    employee-assistant = {
      display_name = "${var.organisation} Employee Assistant"
      servers      = ["directory"]
    }
    finance-assistant = {
      display_name = "${var.organisation} Finance Assistant"
      servers      = ["directory", "finance"]
    }
  }

  # What each agent may call: the union of its servers' tools.
  agents = {
    for a, cfg in local.agent_definitions : a => merge(cfg, {
      tools = distinct(flatten([for s in cfg.servers : local.server_definitions[s].tools]))
    })
  }

  # Which APIM API each tool's REST operation lives on. Finance and directory share internal-systems;
  # budgeting is a second Contoso system with its own API and backend.
  tool_api = {
    directory_get_my_profile              = "internal-systems"
    finance_list_cost_centres             = "internal-systems"
    finance_query_spend                   = "internal-systems"
    diagnostics_caller                    = "internal-systems"
    budgeting_get_forecast                = "budgeting"
    budgeting_update_cost_centre_forecast = "budgeting"
  }

  # Tools whose backend access is app-only: the gateway also requires this app role on the user's token,
  # because the data source can't tell users apart.
  tool_roles = {
    finance_list_cost_centres = "CostCentres.Read"
  }

  # Operations every agent may call on the REST API but that are not MCP tools (the smoke test uses them).
  diagnostic_operations = ["diagnostics_caller"]

  servers = {
    for s, cfg in local.server_definitions : s => {
      agents = [for a, def in local.agent_definitions : a if contains(def.servers, s)]
      tools  = cfg.tools
    }
  }
  server_tools = merge([
    for s, cfg in local.servers : {
      for t in cfg.tools : "${s}/${t}" => {
        server = s
        tool   = t
        api    = local.tool_api[t]
      }
    }
  ]...)

  # Per agent and operation: the allow-list the API policy enforces.
  agent_operations = merge([
    for agent, cfg in local.agents : {
      for op in concat(cfg.tools, local.diagnostic_operations) : "${agent}/${op}" => { agent = agent, operation = op }
    }
  ]...)

  tenant_id = data.azuread_client_config.current.tenant_id
  graph_app = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  sql_app   = data.azuread_application_published_app_ids.well_known.result["AzureSqlDatabase"]
}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

data "azuread_client_config" "current" {}
data "azuread_application_published_app_ids" "well_known" {}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${var.prefix}-agent-gateway"
  location = var.location
}

# ---- Private networking (secure profile only) ---------------------------------------------------------
# The network receives what it connects to (dependency inversion): API Management's address, the
# resources that get private endpoints, and the log workspace. Nothing outside reads it except via local.net.

module "network" {
  source = "./network"
  count  = local.private_networking ? 1 : 0

  prefix              = var.prefix
  suffix              = random_string.suffix.result
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  resource_group_id   = azurerm_resource_group.rg.id
  settings            = var.private_networking

  apim_hostname    = trimprefix(local.apim_gateway_url, "https://")
  apim_private_ips = local.apim_private_ips

  private_endpoint_targets = {
    func      = { id = azurerm_function_app_flex_consumption.func.id, subresource = "sites", zone = "sites" }
    budgeting = { id = azurerm_function_app_flex_consumption.budgeting.id, subresource = "sites", zone = "sites" }
    sql       = { id = azurerm_mssql_server.sql.id, subresource = "sqlServer", zone = "sql" }
    blob      = { id = azurerm_storage_account.sa.id, subresource = "blob", zone = "blob" }
    queue     = { id = azurerm_storage_account.sa.id, subresource = "queue", zone = "queue" }
    table     = { id = azurerm_storage_account.sa.id, subresource = "table", zone = "table" }
  }

  log_analytics = {
    id           = azurerm_log_analytics_workspace.logs.id
    workspace_id = azurerm_log_analytics_workspace.logs.workspace_id
    location     = azurerm_log_analytics_workspace.logs.location
  }
}
