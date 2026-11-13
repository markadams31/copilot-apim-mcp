#!/usr/bin/env bash
# Point-to-site VPN into the secure profile's VNet, via NetworkManager's OpenVPN plugin.
#
#   scripts/vpn.sh setup   # once after `terraform apply`: build the profile and import it
#   scripts/vpn.sh up      # connect (split tunnel: only 10.40.0.0/16 goes over the VPN)
#   scripts/vpn.sh down
#   scripts/vpn.sh status
#
# While connected, Azure names (APIM, privatelink) resolve through the DNS forwarder in the VNet;
# everything else uses your normal DNS. Needs network-manager-openvpn.
set -euo pipefail
cd "$(dirname "$0")"

CONN=contoso-vpn
DIR=../vpn # gitignored: holds the client private key
DOMAINS="~azure-api.net ~azurewebsites.net ~database.windows.net ~core.windows.net"

tf() { terraform -chdir=../infra/profiles/secure output -raw "$1"; } # the VPN exists only in the secure profile

case "${1:-status}" in
setup)
  mkdir -p "$DIR" && chmod 700 "$DIR"
  url=$(az network vnet-gateway vpn-client generate \
    -g "$(tf resource_group)" -n "$(tf vpn_gateway)" --authentication-method EAPTLS -o tsv)
  curl -fsSL "$url" -o "$DIR/profile.zip"

  # Azure's profile has placeholders for the client certificate and key. (The zip uses Windows
  # path separators, "OpenVPN\vpnconfig.ovpn", which unzip won't match, so read it with Python.)
  CERT="$(tf vpn_client_cert_pem)" KEY="$(tf vpn_client_key_pem)" python3 - "$DIR" "$CONN" <<'EOF'
import os, sys, zipfile
d, conn = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(f"{d}/profile.zip") as z:
    name = next(n for n in z.namelist() if n.replace("\\", "/") == "OpenVPN/vpnconfig.ovpn")
    ovpn = z.read(name).decode()
ovpn = ovpn.replace("$CLIENTCERTIFICATE", os.environ["CERT"].strip())
ovpn = ovpn.replace("$PRIVATEKEY", os.environ["KEY"].strip())
fd = os.open(f"{d}/{conn}.ovpn", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with open(fd, "w") as f:
    f.write(ovpn)
EOF
  rm -f "$DIR/profile.zip"

  nmcli connection delete "$CONN" >/dev/null 2>&1 || true
  nmcli connection import type openvpn file "$DIR/$CONN.ovpn" >/dev/null
  nmcli connection modify "$CONN" \
    ipv4.never-default yes \
    ipv4.ignore-auto-dns yes \
    ipv4.dns "$(tf dns_forwarder_ip)" \
    ipv4.dns-search "$DOMAINS" \
    connection.autoconnect no
  echo "Imported '$CONN'. Connect with: scripts/vpn.sh up"
  ;;
up) nmcli connection up "$CONN" ;;
down) nmcli connection down "$CONN" ;;
status)
  nmcli -g GENERAL.STATE connection show "$CONN" 2>/dev/null || echo "not set up (scripts/vpn.sh setup)"
  host=$(tf gateway_url | sed 's#https://##')
  echo "$host -> $(getent hosts "$host" | awk '{print $1}' || true) (want $(tf apim_private_ip))"
  ;;
*) echo "usage: $0 setup|up|down|status" >&2; exit 2 ;;
esac
