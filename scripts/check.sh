#!/usr/bin/env bash
# Proves the pipeline works end to end: Prometheus is scraping the checkout service
# and k6 traffic is being counted. Used by CI, and handy after scripts/up.sh.
set -euo pipefail

kubectl -n monitoring port-forward svc/kps-prometheus 9090 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT

query() {
  curl -fsS --get http://127.0.0.1:9090/api/v1/query --data-urlencode "query=$1" |
    python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else 0)'
}

echo "Waiting for Prometheus to scrape checkout traffic (up to 5 minutes)..."
for _ in $(seq 1 60); do
  up=$(query 'max(up{namespace="checkout", service="checkout"})' 2>/dev/null || echo 0)
  served=$(query 'sum(http_requests_total{namespace="checkout", route="/checkout"})' 2>/dev/null || echo 0)
  if [ "$up" = "1" ] && python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) > 0 else 1)' "$served"; then
    echo "OK: checkout target is up and $served checkout requests have been recorded."
    exit 0
  fi
  sleep 5
done
echo "FAILED: up=$up served=$served" >&2
kubectl -n checkout get pods -o wide >&2 || true
kubectl -n checkout logs deploy/loadgen --tail 20 >&2 || true
exit 1
