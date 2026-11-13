#!/usr/bin/env bash
# Deploy backend Function apps (Flex Consumption builds Python dependencies remotely).
#
#   scripts/deploy-function.sh [secure|rapid]              # finance + budgeting
#   scripts/deploy-function.sh [secure|rapid] finance      # finance only
#   scripts/deploy-function.sh [secure|rapid] budgeting    # budgeting only
#
# Secure profile: open a deploy window first (allow_vpn_to_backends=true) and connect the VPN.
# Rapid profile: the Functions are public; just run it.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
profile="${1:-${CONTOSO_PROFILE:-secure}}"
which="${2:-all}"
tf() { terraform -chdir="$root/infra/profiles/$profile" output -raw "$1"; }

deploy_one() {
  local src_dir="$1" name_output="$2"
  local build
  build="$(mktemp -d)"
  (cd "$src_dir" && zip -q -r "$build/app.zip" function_app.py host.json requirements.txt)
  az functionapp deployment source config-zip \
    -g "$(tf resource_group)" -n "$(tf "$name_output")" \
    --src "$build/app.zip" --build-remote true
  rm -rf "$build"
}

case "$which" in
  all)
    deploy_one "$root/backend" function_name
    deploy_one "$root/backend/budgeting" budgeting_function_name
    ;;
  finance)
    deploy_one "$root/backend" function_name
    ;;
  budgeting)
    deploy_one "$root/backend/budgeting" budgeting_function_name
    ;;
  *)
    echo "usage: $0 [secure|rapid] [all|finance|budgeting]" >&2
    exit 1
    ;;
esac
