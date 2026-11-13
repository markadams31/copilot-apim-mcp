# The module's outputs, under the same names, so the scripts work with either profile. Identical in both
# profiles (scripts/check-profiles.sh verifies it). Network-only outputs are null in the rapid profile.

output "profile" { value = module.gateway.profile }
output "tenant_id" { value = module.gateway.tenant_id }
output "api_client_id" { value = module.gateway.api_client_id }
output "agents" { value = module.gateway.agents }
output "servers" { value = module.gateway.servers }
output "gateway_url" { value = module.gateway.gateway_url }
output "function_name" { value = module.gateway.function_name }
output "function_url" { value = module.gateway.function_url }
output "function_identity_name" { value = module.gateway.function_identity_name }
output "budgeting_function_name" { value = module.gateway.budgeting_function_name }
output "budgeting_function_url" { value = module.gateway.budgeting_function_url }
output "sql_server" { value = module.gateway.sql_server }
output "sql_database" { value = module.gateway.sql_database }
output "budgeting_sql_database" { value = module.gateway.budgeting_sql_database }
output "finance_readers_group" { value = module.gateway.finance_readers_group }
output "budget_editors_group" { value = module.gateway.budget_editors_group }
output "obo_credential" { value = module.gateway.obo_credential }
output "resource_group" { value = module.gateway.resource_group }
output "powerplatform_environment_id" { value = module.gateway.powerplatform_environment_id }
output "apim_private_ip" { value = module.gateway.apim_private_ip }
output "dns_forwarder_ip" { value = module.gateway.dns_forwarder_ip }
output "vpn_gateway" { value = module.gateway.vpn_gateway }

output "vpn_client_cert_pem" {
  value     = module.gateway.vpn_client_cert_pem
  sensitive = true
}

output "vpn_client_key_pem" {
  value     = module.gateway.vpn_client_key_pem
  sensitive = true
}
