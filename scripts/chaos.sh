#!/usr/bin/env bash
# Sets the checkout service's chaos switch from inside the pod, so no port-forward is needed.
# Usage: scripts/chaos.sh <error_rate 0..1> <latency_ms> [duration_s]
# With a duration, chaos switches itself off after that many seconds, so a forgotten
# experiment cannot keep burning the error budget.
set -euo pipefail
USAGE="usage: scripts/chaos.sh <error_rate 0..1> <latency_ms> [duration_s]"
ERROR_RATE="${1:?$USAGE}"
LATENCY_MS="${2:-0}"
DURATION_S="${3:-0}"

kubectl -n checkout exec deploy/checkout -- python -c '
import json, os, sys, urllib.request
body = json.dumps({"error_rate": float(sys.argv[1]), "latency_ms": int(sys.argv[2]),
                   "duration_s": int(sys.argv[3])}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/chaos", data=body, method="PUT", headers={
    "Authorization": "Bearer " + os.environ["CHAOS_TOKEN"], "Content-Type": "application/json"})
print(urllib.request.urlopen(req).read().decode())
' "$ERROR_RATE" "$LATENCY_MS" "$DURATION_S"
