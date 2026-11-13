# ---- VNet flow logs (optional: settings.flow_logs) --------------------------------------------------
# Denied flows to the private endpoint subnet are the network-level signal of someone trying to reach
# a backend without going through API Management.

resource "azurerm_storage_account" "flowlogs" {
  count                           = var.settings.flow_logs ? 1 : 0
  name                            = substr("st${replace(var.prefix, "-", "")}flow${var.suffix}", 0, 24)
  resource_group_name             = var.resource_group_name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
}

resource "azurerm_network_watcher_flow_log" "vnet" {
  count                = var.settings.flow_logs ? 1 : 0
  name                 = "flowlog-${var.prefix}-${var.suffix}"
  network_watcher_name = "NetworkWatcher_${var.location}"
  resource_group_name  = "NetworkWatcherRG" # Azure creates one watcher per region per subscription
  target_resource_id   = azurerm_virtual_network.vnet.id
  storage_account_id   = azurerm_storage_account.flowlogs[0].id
  enabled              = true
  version              = 2

  retention_policy {
    enabled = true
    days    = 30
  }

  traffic_analytics {
    enabled               = true
    workspace_id          = var.log_analytics.workspace_id
    workspace_region      = var.log_analytics.location
    workspace_resource_id = var.log_analytics.id
    interval_in_minutes   = 10
  }
}
