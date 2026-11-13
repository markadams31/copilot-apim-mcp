# Provider requirements only. Providers are configured in each profile (infra/profiles/*), as HashiCorp
# recommends for reusable modules.
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
