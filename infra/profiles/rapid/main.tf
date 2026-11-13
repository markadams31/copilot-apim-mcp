# ---------------------------------------------------------------------------
# Rapid profile: for developing and testing the tools, policies and identity quickly. Public endpoints,
# no VNet, no VPN, API Management BasicV2. Identity, allow-lists, rate limits and logging are the same as
# the secure profile; the network is not. A change is proven only on the secure profile.
#
#   terraform -chdir=infra/profiles/rapid init
#   terraform -chdir=infra/profiles/rapid apply -parallelism=1   # first apply only; see AGENTS.md
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm       = { source = "hashicorp/azurerm", version = "~> 4.0" }
    azapi         = { source = "Azure/azapi", version = "~> 2.0" }
    azuread       = { source = "hashicorp/azuread", version = "~> 3.0" }
    random        = { source = "hashicorp/random", version = "~> 3.0" }
    tls           = { source = "hashicorp/tls", version = "~> 4.0" }
    powerplatform = { source = "microsoft/power-platform", version = "~> 4.2" }
  }
}

provider "azurerm" {
  features {}
}
provider "azapi" {}
provider "azuread" {}

# Uses the Azure CLI sign-in. The signed-in identity must be a Power Platform administrator.
provider "powerplatform" {
  use_cli = true
}

variable "sql_firewall_ip_addresses" {
  description = "Your public IP address(es), so the setup scripts can reach the database. Azure services are always allowed."
  type        = list(string)
  default     = []
}

module "gateway" {
  source = "../../modules/contoso-gateway"

  prefix          = coalesce(var.prefix, "contosodev")
  location        = var.location
  publisher_email = var.publisher_email
  maker_upn       = var.maker_upn

  private_networking        = null
  sql_firewall_ip_addresses = var.sql_firewall_ip_addresses

  obo_credential             = var.obo_credential
  allow_test_sign_in         = var.allow_test_sign_in
  cost_centres_user_upns     = var.cost_centres_user_upns
  finance_reader_upns        = var.finance_reader_upns
  environment_type           = var.environment_type
  billing_policy_id          = var.billing_policy_id
  copilot_connectors         = var.copilot_connectors
  allow_agent_triggers       = var.allow_agent_triggers
  allow_workflow_agents      = var.allow_workflow_agents
  allow_triggered_agent_demo = var.allow_triggered_agent_demo
  alert_email                = var.alert_email
}
