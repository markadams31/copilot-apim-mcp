# ---------------------------------------------------------------------------
# The gateway: API Management imports the internal systems' REST API once, then exposes it as one MCP
# server per business domain (see local.server_definitions). Authorization, rate limits and the
# audit trace live in the API policy, so they apply to every path in.
# ---------------------------------------------------------------------------

# Secure profile: internal VNet mode (only a private IP, not in public DNS) on the Developer tier, the
# cheapest classic tier with VNet injection; production would use Premium or Premium v2.
# Rapid profile: BasicV2, public, provisions in minutes. Both tiers support MCP servers.
# Managed with azapi, not azurerm_api_management: azurerm's read of a classic-tier APIM calls the legacy
# Direct Management API, which new instances have disabled, so every create or refresh fails with 405.
# Open upstream as hashicorp/terraform-provider-azurerm#33800.
resource "azapi_resource" "apim" {
  type      = "Microsoft.ApiManagement/service@2025-09-01-preview" # same API version as the MCP resources
  name      = "apim-${var.prefix}-${random_string.suffix.result}"
  parent_id = azurerm_resource_group.rg.id
  location  = azurerm_resource_group.rg.location

  body = {
    sku = { name = local.apim_sku, capacity = 1 }
    # The internal-network settings are merged in only when they apply (a conditional between two
    # differently shaped objects isn't allowed, so the optional part is a zero-or-one element list).
    properties = merge(
      {
        publisherName  = "${var.organisation} agent tool gateway"
        publisherEmail = var.publisher_email
      },
      [for internal in [local.apim_internal] : {
        virtualNetworkType          = "Internal"
        virtualNetworkConfiguration = { subnetResourceId = local.net.apim_subnet_id }
      } if internal]...
    )
  }

  timeouts {
    create = "3h" # internal-mode classic APIM takes 45+ minutes
    update = "3h"
  }

  # The body above is what a fresh deployment sends. On an existing instance, azapi would PUT it back
  # over everything APIM filled in (hostnames, TLS settings), and on a classic tier any update can mean a
  # long infrastructure operation. So drift in the body is ignored: to change the tier, network or
  # publisher deliberately, remove this, plan, and review the diff carefully.
  lifecycle {
    ignore_changes = [body]

    precondition {
      condition     = !local.apim_internal || contains(["Developer", "Premium"], local.apim_sku)
      error_message = "Internal VNet mode needs a classic tier that supports it (Developer or Premium)."
    }
  }

  response_export_values = ["properties.gatewayUrl", "properties.privateIPAddresses"]
}

locals {
  apim_gateway_url = azapi_resource.apim.output.properties.gatewayUrl
  apim_private_ips = coalesce(try(azapi_resource.apim.output.properties.privateIPAddresses, null), [])

  # Tool descriptions come from each system's OpenAPI file (one source of truth per backend).
  tool_descriptions = merge(concat(
    [
      for path, methods in yamldecode(file("${path.module}/../../../backend/openapi.yaml")).paths : {
        for method, op in methods : op.operationId => trimspace(op.description)
      }
    ],
    [
      for path, methods in yamldecode(file("${path.module}/../../../backend/budgeting/openapi.yaml")).paths : {
        for method, op in methods : op.operationId => trimspace(op.description)
      }
    ],
  )...)

  # Shared policy inputs for every REST API the gateway publishes (finance and budgeting).
  api_policy_vars = {
    rate_limit_calls = var.rate_limit_per_minute
    tenant_id        = local.tenant_id
    api_client_id    = azuread_application.api.client_id
    agent_app_ids    = [for a in keys(local.agents) : azuread_application.agent[a].client_id]
    tool_roles       = local.tool_roles
    allowed_pairs = join(", ", [
      for k, v in local.agent_operations : "\"${v.operation}|${azuread_application.agent[v.agent].client_id}\""
    ])
  }

  # Map APIM API name -> resource, so MCP tools can point at the right API.
  apim_apis = {
    "internal-systems" = azurerm_api_management_api.tools.name
    "budgeting"        = azurerm_api_management_api.budgeting.name
  }
}

resource "azurerm_api_management_api" "tools" {
  name                  = "internal-systems"
  resource_group_name   = azurerm_resource_group.rg.name
  api_management_name   = azapi_resource.apim.name
  revision              = "1"
  display_name          = "${var.organisation} internal systems API"
  description           = "Contoso's internal systems, exposed to Copilot Studio agents as MCP tools through the gateway." # matches openapi.yaml; avoids a diff every plan
  path                  = "tools"
  protocols             = ["https"]
  service_url           = "https://${azurerm_function_app_flex_consumption.func.default_hostname}/api"
  subscription_required = false

  import {
    content_format = "openapi"
    content_value  = file("${path.module}/../../../backend/openapi.yaml")
  }
}

# Contoso budgeting: a second REST API on the same gateway, backed by the budgeting Function.
resource "azurerm_api_management_api" "budgeting" {
  name                  = "budgeting"
  resource_group_name   = azurerm_resource_group.rg.name
  api_management_name   = azapi_resource.apim.name
  revision              = "1"
  display_name          = "${var.organisation} budgeting API"
  description           = "Contoso's budgeting system (forecasts by cost centre). A separate backend from finance spending."
  path                  = "budgeting"
  protocols             = ["https"]
  service_url           = "https://${azurerm_function_app_flex_consumption.budgeting.default_hostname}/api"
  subscription_required = false

  import {
    content_format = "openapi"
    content_value  = file("${path.module}/../../../backend/budgeting/openapi.yaml")
  }
}

# Per-agent, per-operation authorization on every REST API, so it applies to MCP and direct calls.
resource "azurerm_api_management_api_policy" "tools" {
  api_name            = azurerm_api_management_api.tools.name
  resource_group_name = azurerm_resource_group.rg.name
  api_management_name = azapi_resource.apim.name
  xml_content         = templatefile("${path.module}/policies/api-policy.xml.tftpl", local.api_policy_vars)
}

resource "azurerm_api_management_api_policy" "budgeting" {
  api_name            = azurerm_api_management_api.budgeting.name
  resource_group_name = azurerm_resource_group.rg.name
  api_management_name = azapi_resource.apim.name
  xml_content         = templatefile("${path.module}/policies/api-policy.xml.tftpl", local.api_policy_vars)
}

# MCP server resources aren't in the azurerm provider yet, so use azapi on the preview API.
resource "azapi_resource" "mcp" {
  for_each                  = local.servers
  type                      = "Microsoft.ApiManagement/service/apis@2025-09-01-preview"
  name                      = "${each.key}-mcp"
  parent_id                 = azapi_resource.apim.id
  schema_validation_enabled = false

  body = {
    properties = {
      type                 = "mcp"
      displayName          = "${each.key} tools"
      description          = "MCP tools served by ${each.key}"
      path                 = "${each.key}-mcp"
      protocols            = ["https"]
      subscriptionRequired = false
    }
  }

  # Updating an MCP server deletes the tools under it: changing only its description removed the server's
  # existing tool from API Management while Terraform's state still listed it. So the server is created
  # once and never rewritten; tools are managed separately. To change one, taint it.
  lifecycle {
    ignore_changes = [body]
  }
}

resource "azapi_resource" "mcp_tool" {
  for_each = local.server_tools
  type     = "Microsoft.ApiManagement/service/apis/tools@2025-09-01-preview"
  # Tool resource names must be unique across the whole APIM instance, not just per MCP server (a
  # duplicate gets a 502 from ARM). Underscores become hyphens: resource names are safer without.
  name                      = "${each.value.server}-${replace(each.value.tool, "_", "-")}"
  parent_id                 = azapi_resource.mcp[each.value.server].id
  schema_validation_enabled = false

  body = {
    properties = {
      displayName = each.value.tool
      description = local.tool_descriptions[each.value.tool]
      # Built by hand: the azurerm API id carries ";rev=1", which the tool reference rejects.
      # each.value.api selects internal-systems or budgeting (multi-API MCP wiring).
      operationId = "${azapi_resource.apim.id}/apis/${local.apim_apis[each.value.api]}/operations/${each.value.tool}"
    }
  }

  # A create once hung for 19 min with nothing appearing in APIM (concurrent tool writes; the first apply
  # needs -parallelism=1). Fail fast instead; re-running apply creates whatever is missing.
  timeouts {
    create = "5m"
  }
}

resource "azapi_resource" "mcp_policy" {
  for_each                  = local.servers
  type                      = "Microsoft.ApiManagement/service/apis/policies@2025-09-01-preview"
  name                      = "policy"
  parent_id                 = azapi_resource.mcp[each.key].id
  schema_validation_enabled = false

  body = {
    properties = {
      format = "rawxml"
      value = templatefile("${path.module}/policies/mcp-policy.xml.tftpl", {
        tenant_id     = local.tenant_id
        api_client_id = azuread_application.api.client_id
        agent_app_ids = [for a in each.value.agents : azuread_application.agent[a].client_id]
      })
    }
  }
}
