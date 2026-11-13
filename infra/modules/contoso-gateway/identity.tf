# ---------------------------------------------------------------------------
# Entra ID: one API app (the gateway's resource, which the tools' tokens are for) and one client app per
# agent. No client secrets: see obo_credential and the connector credentials in powerplatform.tf.
# ---------------------------------------------------------------------------

# The Copilot Studio maker: an EXISTING member (work) account in this tenant. A prerequisite, not created
# here. Copilot Studio refuses personal Microsoft accounts, and a tenant created from one signs its owner
# in as a guest (#EXT#), so makers need a work account. Deliberately a data source: an earlier version
# created this user, and `terraform destroy` deleted it along with its MFA registration and licences.
data "azuread_user" "maker" {
  user_principal_name = var.maker_upn
}

resource "random_uuid" "tools_read" {}
resource "random_uuid" "cost_centres_role" {}

resource "azuread_application" "api" {
  display_name     = "${var.prefix}-gateway-api"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]

  api {
    requested_access_token_version = 2
    oauth2_permission_scope {
      id                         = random_uuid.tools_read.result
      value                      = "Tools.Read"
      type                       = "User"
      enabled                    = true
      admin_consent_display_name = "Use ${var.organisation} agent tools"
      admin_consent_description  = "Call ${var.organisation}'s internal systems through the agent tool gateway, as the signed-in user."
      user_consent_display_name  = "Use ${var.organisation} agent tools"
      user_consent_description   = "Call ${var.organisation}'s internal systems through the agent tool gateway, as you."
    }
  }

  # App role for the app-only tool (finance_list_cost_centres): the gateway requires it on the user's
  # token, because the database can't tell users apart for that tool. See docs/architecture.md.
  app_role {
    id                   = random_uuid.cost_centres_role.result
    allowed_member_types = ["User"]
    display_name         = "Read cost centres"
    description          = "May use the finance_list_cost_centres tool."
    value                = "CostCentres.Read"
    enabled              = true
  }

  # Delegated Graph User.Read, used by the on-behalf-of exchange for directory_get_my_profile.
  required_resource_access {
    resource_app_id = local.graph_app
    resource_access {
      id   = azuread_service_principal.msgraph.oauth2_permission_scope_ids["User.Read"]
      type = "Scope"
    }
  }

  # Delegated Azure SQL user_impersonation, used by the on-behalf-of exchange for finance_query_spend.
  required_resource_access {
    resource_app_id = local.sql_app
    resource_access {
      id   = azuread_service_principal.azuresql.oauth2_permission_scope_ids["user_impersonation"]
      type = "Scope"
    }
  }

  # The identifier URI is owned by azuread_application_identifier_uri below; without this,
  # every apply strips it again (and api://<id>/Tools.Read stops resolving).
  lifecycle {
    ignore_changes = [identifier_uris]
  }
}

resource "azuread_application_identifier_uri" "api" {
  application_id = azuread_application.api.id
  identifier_uri = "api://${azuread_application.api.client_id}"
}

locals {
  obo_uses_managed_identity = var.obo_credential == "managed_identity"
}

resource "azuread_application_password" "api_obo" {
  count          = local.obo_uses_managed_identity ? 0 : 1
  application_id = azuread_application.api.id
  display_name   = "obo-fallback"
}

# Entra ID trusts tokens that each Function's managed identity gets for api://AzureADTokenExchange,
# as if they were this app's secret. Only a user-assigned identity can be used this way. One credential
# per backend Function (finance and budgeting).
resource "azuread_application_federated_identity_credential" "api_obo" {
  count          = local.obo_uses_managed_identity ? 1 : 0
  application_id = azuread_application.api.id
  display_name   = "function-managed-identity"
  description    = "The finance Function's user-assigned managed identity authenticates the on-behalf-of exchange (no client secret)"
  issuer         = "https://login.microsoftonline.com/${local.tenant_id}/v2.0"
  subject        = azurerm_user_assigned_identity.func.principal_id
  audiences      = ["api://AzureADTokenExchange"]
}

resource "azuread_application_federated_identity_credential" "api_obo_budgeting" {
  count          = local.obo_uses_managed_identity ? 1 : 0
  application_id = azuread_application.api.id
  display_name   = "budgeting-function-managed-identity"
  description    = "The budgeting Function's user-assigned managed identity authenticates the on-behalf-of exchange (no client secret)"
  issuer         = "https://login.microsoftonline.com/${local.tenant_id}/v2.0"
  subject        = azurerm_user_assigned_identity.budgeting.principal_id
  audiences      = ["api://AzureADTokenExchange"]
}

resource "azuread_service_principal" "api" {
  client_id = azuread_application.api.client_id
  owners    = [data.azuread_client_config.current.object_id]
}

resource "azuread_service_principal" "msgraph" {
  client_id    = local.graph_app
  use_existing = true
}

# Admin consent: the API may call Graph User.Read on behalf of any user in the tenant.
resource "azuread_service_principal_delegated_permission_grant" "api_graph" {
  service_principal_object_id          = azuread_service_principal.api.object_id
  resource_service_principal_object_id = azuread_service_principal.msgraph.object_id
  claim_values                         = ["User.Read"]
}

# Note: adopting Azure SQL's service principal means `terraform destroy` deletes it from the tenant;
# Azure recreates it on demand.
resource "azuread_service_principal" "azuresql" {
  client_id    = local.sql_app
  use_existing = true
}

# Admin consent: the API may sign in to Azure SQL as any user in the tenant (SQL still decides what each
# user can do; a user with no database user, directly or through a group, is refused).
resource "azuread_service_principal_delegated_permission_grant" "api_sql" {
  service_principal_object_id          = azuread_service_principal.api.object_id
  resource_service_principal_object_id = azuread_service_principal.azuresql.object_id
  claim_values                         = ["user_impersonation"]
}

# ---- Agent apps -----------------------------------------------------------------------------------------

resource "azuread_application" "agent" {
  for_each         = local.agents
  display_name     = "${var.prefix}-${each.key}"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]

  # Public-client sign-in lets anyone in the tenant get a token with this agent's identity (azp), so it
  # is OFF unless var.allow_test_sign_in is set, for the window in which smoke.py and pressure.py run.
  # Copilot Studio doesn't need it: its connector is a confidential client (Web redirect URI below + a
  # federated credential, see powerplatform.tf).
  fallback_public_client_enabled = var.allow_test_sign_in
  dynamic "public_client" {
    for_each = var.allow_test_sign_in ? [1] : []
    content {
      redirect_uris = ["http://localhost/"]
    }
  }

  # Copilot Studio's OAuth callback(s) for this agent (see powerplatform.tf).
  web {
    redirect_uris = [for c in var.copilot_connectors : c.redirect_uri if c.agent == each.key]
  }

  required_resource_access {
    resource_app_id = azuread_application.api.client_id
    resource_access {
      id   = random_uuid.tools_read.result
      type = "Scope"
    }
  }
}

resource "azuread_service_principal" "agent" {
  for_each  = local.agents
  client_id = azuread_application.agent[each.key].client_id
  owners    = [data.azuread_client_config.current.object_id]
}

# Pre-authorise each agent app for Tools.Read, so users aren't prompted for consent.
resource "azuread_application_pre_authorized" "agent" {
  for_each             = local.agents
  application_id       = azuread_application.api.id
  authorized_client_id = azuread_application.agent[each.key].client_id
  permission_ids       = [random_uuid.tools_read.result]
}

# ---- Who may do what ----------------------------------------------------------------------------------
# App-only tool: the gateway checks the CostCentres.Read app role.
# Delegated tool: the database checks membership of the Finance Readers group (granted by
# scripts/sql-setup.py; Terraform only manages the group).

locals {
  cost_centres_users = var.cost_centres_user_upns == null ? [var.maker_upn] : var.cost_centres_user_upns
  finance_readers    = var.finance_reader_upns == null ? [var.maker_upn] : var.finance_reader_upns
  budget_editors     = var.budget_editor_upns == null ? [var.maker_upn] : var.budget_editor_upns
}

data "azuread_user" "cost_centres" {
  for_each            = toset(local.cost_centres_users)
  user_principal_name = each.value
}

resource "azuread_app_role_assignment" "cost_centres" {
  for_each            = data.azuread_user.cost_centres
  app_role_id         = random_uuid.cost_centres_role.result
  principal_object_id = each.value.object_id
  resource_object_id  = azuread_service_principal.api.object_id
}

data "azuread_user" "finance_readers" {
  for_each            = toset(local.finance_readers)
  user_principal_name = each.value
}

resource "azuread_group" "finance_readers" {
  display_name     = "${var.organisation} Finance Readers (${var.prefix})"
  description      = "May query spending through finance_query_spend. The finance database grants this group read access to the spend view."
  security_enabled = true
  owners           = [data.azuread_client_config.current.object_id]
  members          = [for u in data.azuread_user.finance_readers : u.object_id]
}

data "azuread_user" "budget_editors" {
  for_each            = toset(local.budget_editors)
  user_principal_name = each.value
}

resource "azuread_group" "budget_editors" {
  display_name     = "${var.organisation} Budget Editors (${var.prefix})"
  description      = "May read and update cost-centre forecasts in the budgeting system. The budgeting database grants this group access."
  security_enabled = true
  owners           = [data.azuread_client_config.current.object_id]
  members          = [for u in data.azuread_user.budget_editors : u.object_id]
}
