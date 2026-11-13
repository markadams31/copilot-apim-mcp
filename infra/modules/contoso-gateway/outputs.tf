output "profile" {
  description = "secure (private networking) or rapid (public endpoints)."
  value       = local.private_networking ? "secure" : "rapid"
}

output "tenant_id" {
  value = local.tenant_id
}

output "api_client_id" {
  value = azuread_application.api.client_id
}

output "agents" {
  description = "Per agent: display name, client app ID, the MCP servers it uses (with their URLs), and the tools it may call."
  value = {
    for name, cfg in local.agents : name => {
      display_name = cfg.display_name
      client_id    = azuread_application.agent[name].client_id
      servers      = { for s in cfg.servers : s => "${local.apim_gateway_url}/${s}-mcp/mcp" }
      tools        = cfg.tools
    }
  }
}

output "servers" {
  description = "Per MCP server: its URL, the agents that use it, and the tools it lists."
  value = {
    for name, cfg in local.servers : name => {
      mcp_url = "${local.apim_gateway_url}/${name}-mcp/mcp"
      agents  = cfg.agents
      tools   = cfg.tools
    }
  }
}

output "gateway_url" {
  value = local.apim_gateway_url
}

output "function_name" {
  value = azurerm_function_app_flex_consumption.func.name
}

output "function_url" {
  value = "https://${azurerm_function_app_flex_consumption.func.default_hostname}/api"
}

output "function_identity_name" {
  description = "The finance Function's user-assigned managed identity: the database user for the app-only tool is created for this name."
  value       = azurerm_user_assigned_identity.func.name
}

output "budgeting_function_name" {
  value = azurerm_function_app_flex_consumption.budgeting.name
}

output "budgeting_function_url" {
  value = "https://${azurerm_function_app_flex_consumption.budgeting.default_hostname}/api"
}

output "sql_server" {
  value = azurerm_mssql_server.sql.fully_qualified_domain_name
}

output "sql_database" {
  value = azurerm_mssql_database.finance.name
}

output "budgeting_sql_database" {
  value = azurerm_mssql_database.budgeting.name
}

output "finance_readers_group" {
  description = "The Entra group the finance database grants read access to spending (finance_query_spend)."
  value       = azuread_group.finance_readers.display_name
}

output "budget_editors_group" {
  description = "The Entra group the budgeting database grants forecast read/write access to."
  value       = azuread_group.budget_editors.display_name
}

output "obo_credential" {
  value = var.obo_credential
}

output "resource_group" {
  value = azurerm_resource_group.rg.name
}

output "powerplatform_environment_id" {
  value = powerplatform_environment.agents.id
}

# ---- Secure profile only (null in rapid) ------------------------------------------------------------

output "apim_private_ip" {
  value = try(local.apim_private_ips[0], null)
}

output "dns_forwarder_ip" {
  description = "Use as the DNS server for private names while on the VPN."
  value       = try(local.net.dns_forwarder_ip, null)
}

output "vpn_gateway" {
  value = try(nonsensitive(local.net.vpn.gateway_name), null)
}

output "vpn_client_cert_pem" {
  value     = try(local.net.vpn.client_cert_pem, null)
  sensitive = true
}

output "vpn_client_key_pem" {
  value     = try(local.net.vpn.client_key_pem, null)
  sensitive = true
}
