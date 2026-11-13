#!/usr/bin/env bash
# The two profiles share their variables and outputs. Fail if the copies have drifted apart.
set -euo pipefail
cd "$(dirname "$0")/../infra/profiles"
status=0
for f in variables.tf outputs.tf; do
  if ! diff -u "secure/$f" "rapid/$f"; then
    echo "infra/profiles/{secure,rapid}/$f differ: keep them identical." >&2
    status=1
  fi
done
exit $status
