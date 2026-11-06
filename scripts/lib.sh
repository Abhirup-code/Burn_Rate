#!/usr/bin/env bash
# Shared helpers for the check scripts: open a tunnel to Prometheus and run PromQL queries.
# Source it; do not run it directly.

prom_connect() {
  kubectl -n monitoring port-forward svc/kps-prometheus 9090 >/dev/null 2>&1 &
  PROM_PF=$!
  trap 'kill "$PROM_PF" 2>/dev/null || true' EXIT
  # Wait until the tunnel answers.
  for _ in $(seq 1 30); do
    curl -fsS http://127.0.0.1:9090/-/ready >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "Could not reach Prometheus through port-forward" >&2
  return 1
}

# Prints the first value of an instant query, or 0 when the result is empty.
prom_value() {
  curl -fsS --get http://127.0.0.1:9090/api/v1/query --data-urlencode "query=$1" |
    python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else 0)'
}

# True when a number is greater than zero.
positive() {
  python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) > 0 else 1)' "$1"
}
