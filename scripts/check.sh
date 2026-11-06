#!/usr/bin/env bash
# Proves the pipeline works end to end: Prometheus is scraping the checkout service,
# k6 traffic is being counted, and the SLO rules are loaded. Used by CI, and handy after up.sh.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
prom_connect

echo "Waiting for Prometheus to scrape checkout traffic (up to 5 minutes)..."
up=0 served=0 rules=0
for _ in $(seq 1 60); do
  up=$(prom_value 'max(up{namespace="checkout", service="checkout"})' 2>/dev/null || echo 0)
  served=$(prom_value 'sum(http_requests_total{namespace="checkout", route="/checkout"})' 2>/dev/null || echo 0)
  rules=$(prom_value 'count(slo:objective:ratio{sloth_service="checkout"})' 2>/dev/null || echo 0)
  if [ "$up" = "1" ] && positive "$served" && [ "$rules" = "2" ]; then
    echo "OK: checkout is up, $served checkout requests recorded, and both SLOs are loaded."
    exit 0
  fi
  sleep 5
done
echo "FAILED: up=$up served=$served slos_loaded=$rules (want 1, >0, 2)" >&2
kubectl -n checkout get pods -o wide >&2 || true
kubectl -n checkout logs deploy/loadgen --tail 20 >&2 || true
exit 1
