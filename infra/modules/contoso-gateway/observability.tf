# ---------------------------------------------------------------------------
# Observability: one Log Analytics workspace (log-*) behind everything, so a tool call can be followed
# from Copilot Studio, through API Management and the network, to the backend and Entra ID.
#
#   Copilot Studio  -> Application Insights (environment-level OpenTelemetry export; admin center step)
#   API Management  -> Application Insights (requests with MCP gen_ai.* dimensions + authz trace with
#                      agent and user), and resource logs (GatewayLogs) to Log Analytics
#   Backend         -> Application Insights (already wired via the Function's connection string)
#   Network         -> VNet flow logs with Traffic Analytics (secure profile; network/flowlogs.tf)
#   Entra ID        -> sign-in logs (incl. OBO and managed identity), audit logs, Graph activity logs
#
# Payloads are NOT logged anywhere (tool arguments and results can contain user data).
# ---------------------------------------------------------------------------

# ---- API Management -------------------------------------------------------------------------------

resource "azurerm_api_management_logger" "appinsights" {
  name                = "appinsights"
  api_management_name = azapi_resource.apim.name
  resource_group_name = azurerm_resource_group.rg.name
  resource_id         = azurerm_application_insights.ai.id

  application_insights {
    connection_string = azurerm_application_insights.ai.connection_string
  }
}

# All APIs, including the MCP servers. "information" verbosity lets the API policy's trace (agent,
# user, operation, decision) reach Application Insights as custom dimensions.
resource "azurerm_api_management_diagnostic" "appinsights" {
  identifier               = "applicationinsights"
  api_management_name      = azapi_resource.apim.name
  resource_group_name      = azurerm_resource_group.rg.name
  api_management_logger_id = azurerm_api_management_logger.appinsights.id

  sampling_percentage       = 100
  always_log_errors         = true
  log_client_ip             = true
  verbosity                 = "information"
  http_correlation_protocol = "W3C"

  # Never log bodies: MCP tool arguments and results can carry user data.
  frontend_request {
    body_bytes = 0
  }
  frontend_response {
    body_bytes = 0
  }
  backend_request {
    body_bytes = 0
  }
  backend_response {
    body_bytes = 0
  }
}

resource "azurerm_monitor_diagnostic_setting" "apim" {
  name                           = "to-log-analytics"
  target_resource_id             = azapi_resource.apim.id
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.logs.id
  log_analytics_destination_type = "Dedicated" # resource-specific tables (ApiManagementGatewayLogs)

  enabled_log {
    category_group = "allLogs"
  }
  enabled_metric {
    category = "AllMetrics"
  }
}

# ---- Microsoft Entra ID ---------------------------------------------------------------------------
# Tenant-wide: sends sign-in, audit and Microsoft Graph activity logs to the workspace. Needs Entra ID
# P1/P2 (included in E5). Note: on-behalf-of sign-ins record the ORIGINAL user's IP address, not the
# backend's, so they show who and when, not which network path the backend used.

resource "azapi_resource" "entra_diagnostics" {
  count                     = var.entra_diagnostics ? 1 : 0
  type                      = "microsoft.aadiam/diagnosticSettings@2017-04-01"
  name                      = "${var.prefix}-to-log-analytics"
  parent_id                 = "/"
  schema_validation_enabled = false

  body = {
    properties = {
      workspaceId = azurerm_log_analytics_workspace.logs.id
      logs = [for c in [
        "AuditLogs",
        "SignInLogs",
        "NonInteractiveUserSignInLogs",
        "ServicePrincipalSignInLogs",
        "ManagedIdentitySignInLogs",
        "MicrosoftGraphActivityLogs",
        ] : {
        category        = c
        enabled         = true
        retentionPolicy = { enabled = false, days = 0 }
      }]
    }
  }
}

# ---- Alerts ---------------------------------------------------------------------------------------
# Fired alerts always show in Azure Monitor. They notify someone only when var.alert_email is set:
# an action group sends an email, and both rules below use it.

resource "azurerm_monitor_action_group" "alerts" {
  count               = var.alert_email == "" ? 0 : 1
  name                = "${var.prefix}-alerts"
  resource_group_name = azurerm_resource_group.rg.name
  short_name          = substr(var.prefix, 0, 12)

  email_receiver {
    name                    = "owner"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "authz_denials" {
  name                 = "${var.prefix}-authz-denial-spike"
  resource_group_name  = azurerm_resource_group.rg.name
  location             = azurerm_resource_group.rg.location
  description          = "Many 401/403 responses from API Management: an agent probing tools it isn't allowed, or a misconfigured connection."
  severity             = 2
  scopes               = [azurerm_log_analytics_workspace.logs.id]
  evaluation_frequency = "PT5M"
  window_duration      = "PT15M"

  criteria {
    query                   = <<-KQL
      ApiManagementGatewayLogs
      | where ResponseCode in (401, 403)
      | summarize Denials = count() by ApiId
    KQL
    time_aggregation_method = "Total"
    metric_measure_column   = "Denials"
    threshold               = 20
    operator                = "GreaterThan"
    dimension {
      name     = "ApiId"
      operator = "Include"
      values   = ["*"]
    }
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  dynamic "action" {
    for_each = azurerm_monitor_action_group.alerts
    content {
      action_groups = [action.value.id]
    }
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "backend_errors" {
  name                 = "${var.prefix}-backend-errors"
  resource_group_name  = azurerm_resource_group.rg.name
  location             = azurerm_resource_group.rg.location
  description          = "Backend 5xx through API Management: the internal API or a downstream system (Graph, SQL) is failing."
  severity             = 2
  scopes               = [azurerm_log_analytics_workspace.logs.id]
  evaluation_frequency = "PT5M"
  window_duration      = "PT15M"

  criteria {
    query                   = <<-KQL
      ApiManagementGatewayLogs
      | where BackendResponseCode >= 500
      | summarize Errors = count()
    KQL
    time_aggregation_method = "Total"
    metric_measure_column   = "Errors"
    threshold               = 5
    operator                = "GreaterThan"
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  dynamic "action" {
    for_each = azurerm_monitor_action_group.alerts
    content {
      action_groups = [action.value.id]
    }
  }
}
