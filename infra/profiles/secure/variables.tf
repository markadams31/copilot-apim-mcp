# Operator settings, identical in both profiles (infra/profiles/secure and infra/profiles/rapid keep this
# file the same; scripts/check-profiles.sh verifies it). Descriptions of each setting are on the module's
# variables in infra/modules/contoso-gateway/variables.tf.

variable "prefix" {
  description = "Resource name prefix. null uses the profile's default (contoso or contosodev)."
  type        = string
  default     = null
}

variable "location" {
  type    = string
  default = "australiaeast"
}

variable "publisher_email" {
  type    = string
  default = "noreply@example.com"
}

variable "maker_upn" {
  description = "UPN of the existing work account that builds the Copilot Studio agents."
  type        = string
}

variable "obo_credential" {
  type    = string
  default = "managed_identity"
}

variable "allow_test_sign_in" {
  type    = bool
  default = false
}

variable "cost_centres_user_upns" {
  type    = list(string)
  default = null
}

variable "finance_reader_upns" {
  type    = list(string)
  default = null
}

variable "environment_type" {
  type    = string
  default = "Sandbox"
}

variable "billing_policy_id" {
  type    = string
  default = null
}

variable "copilot_connectors" {
  type = map(object({
    agent        = string
    redirect_uri = string
    subject      = string
  }))
  default = {}
}

variable "allow_agent_triggers" {
  type    = bool
  default = false
}

variable "allow_workflow_agents" {
  type    = bool
  default = false
}

variable "allow_triggered_agent_demo" {
  type    = bool
  default = false
}

variable "alert_email" {
  type    = string
  default = ""
}
