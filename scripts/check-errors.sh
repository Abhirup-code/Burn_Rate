#!/usr/bin/env bash
# After chaos is turned on, confirms Prometheus records the injected 500s.
set -euo pipefail

kubectl -n monitoring port-forward svc/kps-prometheus 9090 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT

echo "Waiting for injected errors to show up (up to 2 minutes)..."
for _ in $(seq 1 24); do
  errors=$(curl -fsS --get http://127.0.0.1:9090/api/v1/query \
    --data-urlencode 'query=sum(http_requests_total{namespace="checkout", route="/checkout", code="500"})' 2>/dev/null |
    python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else 0)' || echo 0)
  if python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) > 0 else 1)' "$errors"; then
    echo "OK: Prometheus recorded $errors failed checkout requests."
    exit 0
  fi
  sleep 5
done
echo "FAILED: no 500s recorded" >&2
exit 1
