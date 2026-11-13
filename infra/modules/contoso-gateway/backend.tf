# ---------------------------------------------------------------------------
# The internal systems' API: an Azure Function (Flex Consumption) with built-in auth, in front of
# Microsoft Graph (the directory) and an Azure SQL database (finance).
# Network settings come from the derived flags in main.tf: private in the secure profile, public with
# Entra authentication in the rapid one.
# ---------------------------------------------------------------------------

resource "azurerm_storage_account" "sa" {
  name                     = "st${var.prefix}${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_storage_container" "deploy" {
  name                  = "deploy"
  storage_account_id    = azurerm_storage_account.sa.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "deploy_budgeting" {
  name                  = "deploy-budgeting"
  storage_account_id    = azurerm_storage_account.sa.id
  container_access_type = "private"
}

resource "azurerm_service_plan" "plan" {
  name                = "asp-${var.prefix}-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = "FC1"
}

# Flex Consumption allows only one site per plan, so budgeting needs its own.
resource "azurerm_service_plan" "budgeting" {
  name                = "asp-${var.prefix}-budg-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = "FC1"
}

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-${var.prefix}-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  retention_in_days   = 30
}

resource "azurerm_application_insights" "ai" {
  name                = "appi-${var.prefix}-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  workspace_id        = azurerm_log_analytics_workspace.logs.id
  application_type    = "web"
}

# The Function's identity. User-assigned, because only a user-assigned managed identity can be a
# federated credential on an app registration (the on-behalf-of exchange), and the app-only tool reads
# SQL as this same identity.
resource "azurerm_user_assigned_identity" "func" {
  name                = "id-${var.prefix}-func-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

resource "azurerm_function_app_flex_consumption" "func" {
  name                = "func-${var.prefix}-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  service_plan_id     = azurerm_service_plan.plan.id

  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "${azurerm_storage_account.sa.primary_blob_endpoint}${azurerm_storage_container.deploy.name}"
  storage_authentication_type = "StorageAccountConnectionString"
  storage_access_key          = azurerm_storage_account.sa.primary_access_key

  runtime_name           = "python"
  runtime_version        = "3.12"
  maximum_instance_count = 40
  instance_memory_in_mb  = 2048

  site_config {
    application_insights_connection_string = azurerm_application_insights.ai.connection_string
  }

  # Secure profile: outbound through the VNet (to the SQL and storage private endpoints, and NAT for
  # Entra and Graph); inbound only through its private endpoint, which the NSG opens to APIM alone.
  # Rapid profile: public, protected by Easy Auth below.
  virtual_network_subnet_id     = try(local.net.function_subnet_id, null)
  public_network_access_enabled = local.public_network_access

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.func.id]
  }

  # API_CLIENT_SECRET exists only when var.obo_credential = "secret". With the default, the function
  # proves itself with MANAGED_IDENTITY_CLIENT_ID and no secret is stored anywhere.
  app_settings = merge(
    {
      TENANT_ID                  = local.tenant_id
      API_CLIENT_ID              = azuread_application.api.client_id
      MANAGED_IDENTITY_CLIENT_ID = azurerm_user_assigned_identity.func.client_id
      SQL_SERVER                 = azurerm_mssql_server.sql.fully_qualified_domain_name
      SQL_DATABASE               = azurerm_mssql_database.finance.name
    },
    local.obo_uses_managed_identity ? {} : { API_CLIENT_SECRET = azuread_application_password.api_obo[0].value }
  )

  # Easy Auth: reject anything without a valid token for the API app.
  auth_settings_v2 {
    auth_enabled           = true
    require_authentication = true
    unauthenticated_action = "Return401"
    default_provider       = "azureactivedirectory"

    active_directory_v2 {
      client_id            = azuread_application.api.client_id
      tenant_auth_endpoint = "https://login.microsoftonline.com/${local.tenant_id}/v2.0"
      allowed_audiences    = [azuread_application.api.client_id, "api://${azuread_application.api.client_id}"]
    }

    login {
      token_store_enabled = false
    }
  }
}

# Contoso budgeting: a second Function app (same plan, own identity and deploy container) in front of
# the budgeting SQL database. Same Entra audience as finance; separate compute and data.
resource "azurerm_user_assigned_identity" "budgeting" {
  name                = "id-${var.prefix}-budgeting-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

resource "azurerm_function_app_flex_consumption" "budgeting" {
  name                = "func-${var.prefix}-budg-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  service_plan_id     = azurerm_service_plan.budgeting.id

  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "${azurerm_storage_account.sa.primary_blob_endpoint}${azurerm_storage_container.deploy_budgeting.name}"
  storage_authentication_type = "StorageAccountConnectionString"
  storage_access_key          = azurerm_storage_account.sa.primary_access_key

  runtime_name           = "python"
  runtime_version        = "3.12"
  maximum_instance_count = 40
  instance_memory_in_mb  = 2048

  site_config {
    application_insights_connection_string = azurerm_application_insights.ai.connection_string
  }

  virtual_network_subnet_id     = try(local.net.function_subnet_id, null)
  public_network_access_enabled = local.public_network_access

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.budgeting.id]
  }

  app_settings = merge(
    {
      TENANT_ID                  = local.tenant_id
      API_CLIENT_ID              = azuread_application.api.client_id
      MANAGED_IDENTITY_CLIENT_ID = azurerm_user_assigned_identity.budgeting.client_id
      SQL_SERVER                 = azurerm_mssql_server.sql.fully_qualified_domain_name
      SQL_DATABASE               = azurerm_mssql_database.budgeting.name
    },
    local.obo_uses_managed_identity ? {} : { API_CLIENT_SECRET = azuread_application_password.api_obo[0].value }
  )

  auth_settings_v2 {
    auth_enabled           = true
    require_authentication = true
    unauthenticated_action = "Return401"
    default_provider       = "azureactivedirectory"

    active_directory_v2 {
      client_id            = azuread_application.api.client_id
      tenant_auth_endpoint = "https://login.microsoftonline.com/${local.tenant_id}/v2.0"
      allowed_audiences    = [azuread_application.api.client_id, "api://${azuread_application.api.client_id}"]
    }

    login {
      token_store_enabled = false
    }
  }
}

# ---------------------------------------------------------------------------
# The finance database: Entra-only authentication, so the only way in is a user or app token.
# ---------------------------------------------------------------------------

data "azuread_user" "me" {
  object_id = data.azuread_client_config.current.object_id
}

resource "azurerm_mssql_server" "sql" {
  name                = "sql-${var.prefix}-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  version             = "12.0"
  minimum_tls_version = "1.2"

  # Secure profile: reachable only through its private endpoint. Rapid profile: the firewall below.
  public_network_access_enabled = local.public_network_access

  # Whoever runs Terraform is the Entra admin, so they can run the setup scripts. Other people get
  # access through database users created FROM EXTERNAL PROVIDER (see scripts/sql-setup.py).
  azuread_administrator {
    login_username              = data.azuread_user.me.user_principal_name
    object_id                   = data.azuread_client_config.current.object_id
    tenant_id                   = local.tenant_id
    azuread_authentication_only = true
  }
}

resource "azurerm_mssql_database" "finance" {
  name        = "finance"
  server_id   = azurerm_mssql_server.sql.id
  sku_name    = "Basic"
  max_size_gb = 2
}

# Budgeting forecasts: a second database on the same server (a separate Contoso system).
resource "azurerm_mssql_database" "budgeting" {
  name        = "budgeting"
  server_id   = azurerm_mssql_server.sql.id
  sku_name    = "Basic"
  max_size_gb = 2
}

# Rapid profile only: the backend's outbound addresses vary, so Azure services are allowed (0.0.0.0 is
# Azure's marker for that), plus any client addresses listed for the setup scripts.
resource "azurerm_mssql_firewall_rule" "azure_services" {
  count            = local.public_network_access ? 1 : 0
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_mssql_firewall_rule" "clients" {
  for_each         = local.public_network_access ? toset(var.sql_firewall_ip_addresses) : toset([])
  name             = "client-${replace(each.value, ".", "-")}"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = each.value
  end_ip_address   = each.value
}
