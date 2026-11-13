# ---------------------------------------------------------------------------
# The Power Platform environment the agents live in, its Managed Environment settings, its link to the
# private network (secure profile only), and the trust for each agent's Copilot Studio connector.
# ---------------------------------------------------------------------------

# Australia geography, with Dataverse (Copilot Studio stores agents there). Data residency is set here,
# not left to defaults: generative AI may not move data across regions, and Bing-backed features (web
# search, public website knowledge) are off.
resource "powerplatform_environment" "agents" {
  display_name      = "${var.prefix}-agents"
  description       = "${var.organisation} Copilot Studio agents that use internal systems through the agent tool gateway."
  location          = "australia"
  environment_type  = var.environment_type
  owner_id          = var.environment_type == "Developer" ? data.azuread_user.maker.object_id : null
  billing_policy_id = var.billing_policy_id

  allow_moving_data_across_regions = false
  allow_bing_search                = false

  dataverse = {
    language_code     = 1033
    currency_code     = "AUD"
    security_group_id = one(azuread_group.environment_users[*].object_id)
  }

  lifecycle {
    # A Sandbox linked to a billing plan is created in the admin center and imported (see AGENTS.md):
    # the Terraform principal may not be able to read a plan made by another account, any update to this
    # resource makes the provider call the billing API (403 for that principal), and after an import the
    # provider can't read Dataverse back. So these are set at creation and never updated by Terraform.
    ignore_changes = [billing_policy_id, dataverse, allow_bing_search, allow_moving_data_across_regions, cadence, description]
  }
}

# Sandbox and Production environments need a security group that controls who gets a Dataverse user.
resource "azuread_group" "environment_users" {
  count            = var.environment_type == "Developer" ? 0 : 1
  display_name     = "${var.prefix}-agents-environment-users"
  description      = "People who can use the ${var.prefix}-agents Power Platform environment."
  security_enabled = true
  members          = [data.azuread_user.maker.object_id]
}

# Managed Environment: required for VNet support, and where agent sharing limits live.
resource "powerplatform_managed_environment" "agents" {
  environment_id             = powerplatform_environment.agents.id
  is_usage_insights_disabled = false
  is_group_sharing_disabled  = true
  limit_sharing_mode         = "ExcludeSharingToSecurityGroups"
  max_limit_user_sharing     = 10
  solution_checker_mode      = "Warn"
  suppress_validation_emails = true

  # Agents can be shared with at most 10 named people, never with whole security groups.
  copilot_limit_sharing_mode     = "ExcludeSharingToSecurityGroups"
  copilot_max_limit_user_sharing = 10
}

# Secure profile: link the NetworkInjection policy, so the environment's connectors (including MCP tools)
# run in the delegated subnets. Allow up to 30 minutes after linking before tool calls work. Unlink this
# first when tearing down (AGENTS.md).
resource "powerplatform_enterprise_policy" "network" {
  count          = local.link_power_platform ? 1 : 0
  environment_id = powerplatform_environment.agents.id
  system_id      = local.net.power_platform_policy_system_id
  policy_type    = "NetworkInjection"

  depends_on = [powerplatform_managed_environment.agents]
}

# Dataverse auditing is NOT set here: the environment's database belongs to its owner (the maker), and the
# Terraform identity isn't a member of it, which is correct least privilege. The owner turns auditing on:
# Power Platform admin center -> environment -> Settings -> Audit and logs.

# ---- Trust for each Copilot Studio connector ------------------------------------------------------------
# No client secrets. The connector authenticates as its own managed identity, which Entra trusts through a
# federated identity credential on the agent's app registration. Values come from var.copilot_connectors.
resource "azuread_application_federated_identity_credential" "connector" {
  for_each       = var.copilot_connectors
  application_id = azuread_application.agent[each.value.agent].id
  display_name   = substr("copilot-${each.key}", 0, 120)
  description    = "Copilot Studio MCP connector's managed identity (no client secret)"
  issuer         = "https://login.microsoftonline.com/${local.tenant_id}/v2.0"
  subject        = each.value.subject
  audiences      = ["api://AzureADTokenExchange"]
}
