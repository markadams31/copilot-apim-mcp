#!/usr/bin/env bash
# Deploy backend Function apps. The dependencies are built here, for Linux and Python 3.13, and shipped
# in the zip: Flex Consumption's remote build used Python 3.12.2 even when the app was set to 3.13, so it
# couldn't install azure-functions 2.x. Needs uv. Keep `python_version` equal to runtime_version in
# infra/modules/contoso-gateway/backend.tf.
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
python_version="3.13"
tf() { terraform -chdir="$root/infra/profiles/$profile" output -raw "$1"; }

deploy_one() {
  local src_dir="$1" name_output="$2"
  local build
  build="$(mktemp -d)"
  mkdir -p "$build/app/.python_packages/lib"
  # manylinux_2_28: mssql-python publishes no older Linux wheels.
  uv pip install --quiet --target "$build/app/.python_packages/lib/site-packages" \
    --python-platform x86_64-manylinux_2_28 --python-version "$python_version" \
    --only-binary :all: -r "$src_dir/requirements.txt"
  cp "$src_dir/function_app.py" "$src_dir/host.json" "$src_dir/requirements.txt" "$build/app/"
  (cd "$build/app" && zip -q -r "$build/app.zip" .)
  az functionapp deployment source config-zip \
    -g "$(tf resource_group)" -n "$(tf "$name_output")" \
    --src "$build/app.zip" --build-remote false
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
