# ---------------------------------------------------------------------------
# Admin access: a point-to-site VPN and a DNS forwarder, so a laptop can reach and resolve the private
# endpoints. Optional (settings.vpn): an organisation would normally provide this from its own network.
# ---------------------------------------------------------------------------

locals {
  vpn = var.settings.vpn ? 1 : 0
}

resource "azurerm_subnet" "gateway" {
  count                = local.vpn
  name                 = "GatewaySubnet"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [local.snet.gw]
}

# ---- DNS forwarder: lets VPN clients resolve private names -------------------------------------
# Azure DNS (168.63.129.16) only answers from inside the VNet. This VM relays queries to it, so a
# laptop on the VPN resolves APIM and the privatelink names to private IPs. Production equivalent:
# Azure DNS Private Resolver, or conditional forwarders on corporate DNS.

resource "tls_private_key" "dns_vm" {
  count     = local.vpn
  algorithm = "ED25519"
}

resource "azurerm_network_interface" "dns" {
  count               = local.vpn
  name                = "nic-dns-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  ip_configuration {
    name                          = "ipconfig"
    subnet_id                     = azurerm_subnet.infra.id
    private_ip_address_allocation = "Static"
    private_ip_address            = local.dns_forwarder_ip
  }
}

resource "azurerm_linux_virtual_machine" "dns" {
  count                 = local.vpn
  name                  = "vm-dns-${var.suffix}"
  resource_group_name   = var.resource_group_name
  location              = var.location
  size                  = "Standard_B1s" # B-series v2 had 0 quota in the test subscription
  admin_username        = "azureuser"
  network_interface_ids = [azurerm_network_interface.dns[0].id]

  admin_ssh_key {
    username   = "azureuser"
    public_key = tls_private_key.dns_vm[0].public_key_openssh
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64encode(<<-YAML
    #cloud-config
    package_update: true
    packages: [dnsmasq]
    write_files:
      - path: /etc/dnsmasq.d/forwarder.conf
        content: |
          # Relay everything to Azure DNS, which knows the VNet's private zones.
          no-resolv
          server=168.63.129.16
          interface=eth0
          bind-interfaces
          cache-size=1000
    runcmd:
      - systemctl restart dnsmasq
  YAML
  )

  # NAT must be in place first, or cloud-init can't install dnsmasq.
  depends_on = [azurerm_subnet_nat_gateway_association.egress]
}

# ---- Point-to-site VPN (certificate auth, OpenVPN) ---------------------------------------------
# A self-signed root CA and one client certificate, generated here and kept in Terraform state.
# Production: Entra ID authentication on the gateway, so access follows Conditional Access.

resource "tls_private_key" "vpn_ca" {
  count     = local.vpn
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "tls_self_signed_cert" "vpn_ca" {
  count                 = local.vpn
  private_key_pem       = tls_private_key.vpn_ca[0].private_key_pem
  is_ca_certificate     = true
  validity_period_hours = 24 * 365
  allowed_uses          = ["cert_signing", "crl_signing"]
  subject {
    common_name = "${var.prefix}-vpn-root"
  }
}

resource "tls_private_key" "vpn_client" {
  count     = local.vpn
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_cert_request" "vpn_client" {
  count           = local.vpn
  private_key_pem = tls_private_key.vpn_client[0].private_key_pem
  subject {
    common_name = "${var.prefix}-vpn-client"
  }
}

resource "tls_locally_signed_cert" "vpn_client" {
  count                 = local.vpn
  cert_request_pem      = tls_cert_request.vpn_client[0].cert_request_pem
  ca_private_key_pem    = tls_private_key.vpn_ca[0].private_key_pem
  ca_cert_pem           = tls_self_signed_cert.vpn_ca[0].cert_pem
  validity_period_hours = 24 * 365
  allowed_uses          = ["client_auth", "digital_signature", "key_encipherment"]
}

resource "azurerm_public_ip" "vpn" {
  count               = local.vpn
  name                = "pip-vpn-${var.prefix}-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = ["1", "2", "3"]
}

resource "azurerm_virtual_network_gateway" "vpn" {
  count               = local.vpn
  name                = "vgw-${var.prefix}-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  type                = "Vpn"
  vpn_type            = "RouteBased"
  sku                 = "VpnGw1AZ"
  generation          = "Generation1"

  ip_configuration {
    name                 = "default"
    public_ip_address_id = azurerm_public_ip.vpn[0].id
    subnet_id            = azurerm_subnet.gateway[0].id
  }

  vpn_client_configuration {
    address_space        = [local.vpn_client_pool]
    vpn_client_protocols = ["OpenVPN"]
    vpn_auth_types       = ["Certificate"]
    root_certificate {
      name = "${var.prefix}-vpn-root"
      # Base64 DER body of the PEM, without the BEGIN/END lines.
      public_cert_data = join("", slice(
        split("\n", trimspace(tls_self_signed_cert.vpn_ca[0].cert_pem)), 1,
        length(split("\n", trimspace(tls_self_signed_cert.vpn_ca[0].cert_pem))) - 1
      ))
    }
  }
}
