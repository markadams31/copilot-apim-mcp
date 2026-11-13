# ---------------------------------------------------------------------------
# Secure profile: the documented deployment. Private networking throughout, API Management in internal
# VNet mode, Power Platform network injection, a point-to-site VPN for admin access.
#
#   terraform -chdir=infra/profiles/secure init
#   terraform -chdir=infra/profiles/secure apply -parallelism=1   # first apply only; see AGENTS.md
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
  features {
    # Manage storage through ARM only, so plans still work once storage has no public endpoint.
    storage {
      data_plane_available = false
    }
  }
}
provider "azapi" {}
provider "azuread" {}

# Uses the Azure CLI sign-in. The signed-in identity must be a Power Platform administrator.
provider "powerplatform" {
  use_cli = true
}

variable "allow_vpn_to_backends" {
  description = <<-EOT
    Open the private-endpoint subnet to VPN clients on 443 and 1433, e.g. to deploy Function code or run
    the SQL setup scripts from a laptop. Leave false: when true, anyone on the VPN with a valid token can
    skip API Management. Production deploys from a runner inside the network instead.
  EOT
  type        = bool
  default     = false
}

variable "public_network_access" {
  description = "Debugging only: true keeps the backend and database publicly reachable while the private path is tested. null derives it (off)."
  type        = bool
  default     = null
}

module "gateway" {
  source = "../../modules/contoso-gateway"

  prefix          = coalesce(var.prefix, "contoso")
  location        = var.location
  publisher_email = var.publisher_email
  maker_upn       = var.maker_upn

  private_networking = {
    vpn                   = true
    allow_vpn_to_backends = var.allow_vpn_to_backends
  }
  public_network_access = var.public_network_access

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
