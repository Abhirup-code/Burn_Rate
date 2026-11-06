#!/usr/bin/env bash
# After chaos is turned on, confirms Prometheus records the injected 500s.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
prom_connect

echo "Waiting for injected errors to show up (up to 2 minutes)..."
errors=0
for _ in $(seq 1 24); do
  errors=$(prom_value 'sum(http_requests_total{namespace="checkout", route="/checkout", code="500"})' 2>/dev/null || echo 0)
  if positive "$errors"; then
    echo "OK: Prometheus recorded $errors failed checkout requests."
    exit 0
  fi
  sleep 5
done
echo "FAILED: no 500s recorded" >&2
exit 1
