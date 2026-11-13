# ---------------------------------------------------------------------------
# Data policy (DLP) for the agents' environment: an allow-list, not a block-list.
#
# Out of the box, a maker in Copilot Studio can add any of ~1,800 connectors, including dozens of
# third-party MCP servers, to an agent. This policy, scoped to this deployment's environment only, allows:
#   - custom connectors whose host is this demonstration's API Management (the MCP servers);
#   - the Teams + Microsoft 365 channel (where Conditional Access on agents is enforced);
#   - Application Insights telemetry from Copilot Studio;
# and blocks everything else by default, including:
#   - every other custom connector (any host);
#   - every certified connector and third-party MCP server not listed here, now or added later;
#   - "Chat without Microsoft Entra ID authentication" (so every agent must authenticate users);
#   - knowledge from public websites, Direct Line/website, Facebook and WhatsApp channels.
#
# Microsoft marks some connectors "unblockable" (SharePoint, Dataverse, Office 365 ...). They can't
# be blocked, so they sit in Non-business, which stops an agent mixing them with the Business ones.
# ---------------------------------------------------------------------------

data "powerplatform_connectors" "all" {}

locals {
  # Environment-level DLP classifies custom connectors by id, not host pattern (patterns are
  # tenant-level). Each Copilot Studio MCP connector must be Business or connection creation is
  # blocked even when custom_connectors_patterns would match the APIM host.
  dlp_copilot_connector_ids = [
    for name in keys(var.copilot_connectors) :
    "/providers/Microsoft.PowerApps/apis/shared_${name}"
  ]

  dlp_business_ids = toset(concat(
    [
      "PvaMicrosoftTeams", # Microsoft Teams + M365 Channel in Copilot Studio
      "CSAppInsights",     # Application Insights in Copilot Studio (telemetry)
    ],
    local.dlp_copilot_connector_ids,
    var.allow_agent_triggers || var.allow_triggered_agent_demo ? [
      "shared_microsoftcopilotstudio", # Copilot Studio: the path every trigger uses
    ] : [],
    var.allow_workflow_agents ? [
      "shared_agentnode", # Agents: the workflow Agent node that calls a published agent
    ] : [],
    var.allow_triggered_agent_demo ? [
      "shared_office365", # Office 365 Outlook: the email trigger and actions
      "shared_teams",     # Microsoft Teams: post a message to a channel
    ] : []
  ))

  dlp_connector_ids = { for c in data.powerplatform_connectors.all.connectors : c.name => c.id... }

  dlp_unblockable = [
    for c in data.powerplatform_connectors.all.connectors : c.id
    if c.unblockable && !contains(local.dlp_business_ids, c.name)
  ]
}

resource "powerplatform_data_loss_prevention_policy" "agents" {
  display_name                      = "${var.prefix} agents: allow-list"
  default_connectors_classification = "Blocked"
  environment_type                  = "OnlyEnvironments"
  environments                      = [powerplatform_environment.agents.id]

  business_connectors = [for id in local.dlp_business_ids : {
    # shared_* connectors are identified by their full /providers/... id. A bare name is accepted by the
    # policy and satisfies the Triggers check, but connection creation still reports the connector blocked.
    id                           = startswith(id, "shared_") ? lookup(local.dlp_connector_ids, id, [id])[0] : id
    default_action_rule_behavior = ""
    action_rules                 = []
    endpoint_rules               = []
  }]

  non_business_connectors = [for id in local.dlp_unblockable : {
    id                           = id
    default_action_rule_behavior = ""
    action_rules                 = []
    endpoint_rules               = []
  }]

  blocked_connectors = [] # everything not listed takes the default: Blocked

  custom_connectors_patterns = [
    {
      order            = 1
      host_url_pattern = "https://${trimprefix(local.apim_gateway_url, "https://")}"
      data_group       = "Business"
    },
    {
      order            = 2
      host_url_pattern = "*"
      data_group       = "Blocked"
    },
  ]
}
