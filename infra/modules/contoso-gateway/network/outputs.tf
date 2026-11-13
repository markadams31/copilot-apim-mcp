# What the parent module needs from the network. Outputs that other resources must wait for carry
# depends_on, so the parent never needs a module-wide depends_on (which would create cycles).

output "apim_subnet_id" {
  description = "API Management's subnet, available only once its NSG and NAT are attached (APIM checks them at deployment)."
  value       = azurerm_subnet.apim.id
  depends_on = [
    azurerm_subnet_network_security_group_association.nsg,
    azurerm_subnet_nat_gateway_association.egress,
  ]
}

output "function_subnet_id" {
  value = azurerm_subnet.func.id
}

output "power_platform_policy_system_id" {
  value = azapi_resource.pp_network_policy.output.properties.systemId
}

output "dns_forwarder_ip" {
  value = var.settings.vpn ? local.dns_forwarder_ip : null
}

output "vpn" {
  description = "The VPN gateway's name and the client certificate and key (null without a VPN)."
  sensitive   = true
  value = var.settings.vpn ? {
    gateway_name    = azurerm_virtual_network_gateway.vpn[0].name
    client_cert_pem = tls_locally_signed_cert.vpn_client[0].cert_pem
    client_key_pem  = tls_private_key.vpn_client[0].private_key_pem
  } : null
}
