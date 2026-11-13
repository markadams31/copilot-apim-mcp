# Inputs from the parent module. Everything here exists only in the secure profile: the parent creates
# this module when var.private_networking is set, and passes in the resources it has to connect to.

variable "prefix" {
  type = string
}

variable "suffix" {
  type = string
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "resource_group_id" {
  type = string
}

variable "settings" {
  description = "The parent's var.private_networking object (see its description)."
  type = object({
    vpn                               = bool
    vpn_client_pool                   = string
    allow_vpn_to_backends             = bool
    power_platform_secondary_location = string
    flow_logs                         = bool
  })
}

variable "apim_hostname" {
  description = "API Management's gateway host name, for the private DNS zone scoped to it."
  type        = string
}

variable "apim_private_ips" {
  description = "API Management's private IP addresses (internal mode)."
  type        = list(string)
}

variable "private_endpoint_targets" {
  description = "Resources that get a private endpoint: key => { id, subresource, zone }."
  type = map(object({
    id          = string
    subresource = string
    zone        = string
  }))
}

variable "log_analytics" {
  description = "The workspace that receives Traffic Analytics from the VNet flow logs."
  type = object({
    id           = string
    workspace_id = string
    location     = string
  })
}
