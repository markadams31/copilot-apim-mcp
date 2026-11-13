# ---------------------------------------------------------------------------
# Inputs. The one that shapes the deployment is private_networking; everything else is the same in
# both profiles (identity, tools, allow-lists, rate limits, logging).
# ---------------------------------------------------------------------------

variable "organisation" {
  description = "The fictional organisation the demonstration is built for; used in display names."
  type        = string
  default     = "Contoso"
}

variable "prefix" {
  description = "Short, lowercase name for this deployment's resources, e.g. contoso or contosodev. Different per profile, so both can exist at once."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,11}$", var.prefix))
    error_message = "prefix must be 2-12 lowercase letters or digits, starting with a letter (it ends up in storage account names)."
  }
}

variable "location" {
  type    = string
  default = "australiaeast"
}

variable "publisher_email" {
  description = "API Management publisher contact (required by Azure; receives API Management system notifications)."
  type        = string
  default     = "noreply@example.com"
}

variable "maker_upn" {
  description = "UPN of the existing work account that builds the Copilot Studio agents (see maker.tf)."
  type        = string
}

# ---- The network ------------------------------------------------------------------------------------

variable "private_networking" {
  description = <<-EOT
    null: public endpoints (the rapid profile, for development only). An object: private networking
    (the secure profile): API Management in internal VNet mode, private endpoints for the backend,
    database and storage, Power Platform network injection, and optionally a point-to-site VPN with a
    DNS forwarder for admin access. The module derives every other network setting from this one input.
  EOT
  type = object({
    vpn                               = optional(bool, true)
    vpn_client_pool                   = optional(string, "10.255.201.0/24")
    allow_vpn_to_backends             = optional(bool, false)
    power_platform_secondary_location = optional(string, "australiasoutheast")
    flow_logs                         = optional(bool, true)
  })
  default = null
}

variable "public_network_access" {
  description = <<-EOT
    Override for the backend's and database's public network access. null (the default) derives it:
    off with private networking, on without. Set true with private networking to test the private path
    before closing the public one.
  EOT
  type        = bool
  default     = null
}

variable "apim_sku" {
  description = "API Management tier. null derives it: Developer (classic, supports internal VNet mode) with private networking, BasicV2 without."
  type        = string
  default     = null
}

variable "sql_firewall_ip_addresses" {
  description = "Without private networking: client IP addresses allowed through the database firewall (for the setup scripts). Azure services are always allowed, so the backend can connect."
  type        = list(string)
  default     = []
}

# ---- Identity and access ----------------------------------------------------------------------------

variable "obo_credential" {
  description = <<-EOT
    How the backend proves itself to Entra ID in the on-behalf-of exchange. managed_identity (the
    default): the Function's user-assigned managed identity, trusted through a federated credential, so
    no secret exists. secret: a client secret, kept as a fallback for comparison and recovery.
  EOT
  type        = string
  default     = "managed_identity"
  validation {
    condition     = contains(["managed_identity", "secret"], var.obo_credential)
    error_message = "obo_credential must be managed_identity or secret."
  }
}

variable "allow_test_sign_in" {
  description = <<-EOT
    Let the agent apps accept public-client sign-in so scripts/smoke.py and scripts/pressure.py can play
    Copilot Studio's part. Leave false: when true, anyone in the tenant can get a token as any agent (the
    agent identity stops being a boundary). Turn on for a test run, then off.
  EOT
  type        = bool
  default     = false
}

variable "cost_centres_user_upns" {
  description = <<-EOT
    Users assigned the CostCentres.Read app role, which the gateway requires for finance_list_cost_centres.
    null (the default) assigns the maker. Set [] to remove everyone (the revocation test), or list more
    people. Production: assign a group (needs Entra ID P1).
  EOT
  type        = list(string)
  default     = null
}

variable "finance_reader_upns" {
  description = <<-EOT
    Members of the Finance Readers group, which the database grants read access to spending
    (finance_query_spend). null (the default) adds the maker. Set [] to show the database refusing.
  EOT
  type        = list(string)
  default     = null
}

variable "budget_editor_upns" {
  description = <<-EOT
    Members of the Budget Editors group, which the budgeting database grants read and write access to
    forecasts (budgeting_get_forecast, budgeting_update_cost_centre_forecast). null (the default) adds
    the maker. Set [] to show the database refusing.
  EOT
  type        = list(string)
  default     = null
}

variable "rate_limit_per_minute" {
  description = "Tool calls allowed per agent per user per minute (API policy rate-limit-by-key)."
  type        = number
  default     = 30
}

# ---- Copilot Studio and Power Platform --------------------------------------------------------------

variable "environment_type" {
  description = <<-EOT
    Sandbox (the default) or Developer. Always prefer Sandbox: Developer can't take a pay-as-you-go
    billing plan or be converted, so the Microsoft Copilot harness Preview fails with
    EnforcementUsageCredits. Publishing and that harness need Sandbox with a billing plan
    (docs/deploy.md, AGENTS.md). Changing this may replace the environment and everything in it.
  EOT
  type        = string
  default     = "Sandbox"
  validation {
    condition     = contains(["Developer", "Sandbox"], var.environment_type)
    error_message = "environment_type must be Developer or Sandbox."
  }
}

variable "billing_policy_id" {
  description = "ID of a Power Platform pay-as-you-go billing plan (Copilot Studio and Dataverse meters) to link the environment to. Needs environment_type = Sandbox. See AGENTS.md for why this is usually done in the admin center and imported."
  type        = string
  default     = null
}

variable "copilot_connectors" {
  description = <<-EOT
    One entry per Copilot Studio MCP connector, keyed by the connector's name (the last part of its
    callback URL). agent: which agent it belongs to (employee-assistant or finance-assistant).
    redirect_uri: the callback URL Copilot Studio shows. subject: the "Subject" Power Apps shows under
    Managed identity.
  EOT
  type = map(object({
    agent        = string
    redirect_uri = string
    subject      = string
  }))
  default = {}
}

variable "allow_agent_triggers" {
  description = <<-EOT
    Allow the Microsoft Copilot Studio connector (shared_microsoftcopilotstudio) as Business. Copilot
    Studio sends every event and recurrence trigger through it, so without it an agent's Triggers section
    says the data policy blocks triggers. Leave false unless an agent needs to run without a user.
  EOT
  type        = bool
  default     = false
}

variable "allow_workflow_agents" {
  description = <<-EOT
    Allow the Microsoft "Agents" connector (shared_agentnode) as Business. A workflow's Agent node needs it:
    without it, creating the node's connection fails with a data policy message. Leave false unless a
    workflow has to call an agent (for example to run an agent on a schedule). It is a governance
    decision, because it lets makers wire agents into workflows in this environment.
  EOT
  type        = bool
  default     = false
}

variable "allow_triggered_agent_demo" {
  description = <<-EOT
    Also allow the Office 365 Outlook and Microsoft Teams connectors as Business, for the triggered-agent
    (shared-mailbox triage) scenario in docs/going-further.md. Leave false unless running that test.
  EOT
  type        = bool
  default     = false
}

# ---- Observability ----------------------------------------------------------------------------------

variable "alert_email" {
  description = "Email address the alert rules notify. Empty (the default) creates no action group. The address must verify itself (a link Azure emails) before alerts arrive."
  type        = string
  default     = ""
}

variable "entra_diagnostics" {
  description = "Send the tenant's Entra sign-in, audit and Graph activity logs to this deployment's workspace (a tenant-wide setting; needs Entra ID P1/P2)."
  type        = bool
  default     = true
}
