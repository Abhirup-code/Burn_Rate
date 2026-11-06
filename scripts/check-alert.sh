#!/usr/bin/env bash
# Confirms an SLO alert is firing at the expected severity.
# Usage: scripts/check-alert.sh <alertname> <page|ticket> [timeout_seconds]
set -euo pipefail
ALERT="${1:?usage: scripts/check-alert.sh <alertname> <page|ticket> [timeout_seconds]}"
SEVERITY="${2:?usage: scripts/check-alert.sh <alertname> <page|ticket> [timeout_seconds]}"
TIMEOUT="${3:-300}"
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
prom_connect

echo "Waiting up to ${TIMEOUT}s for $ALERT ($SEVERITY) to fire..."
query="count(ALERTS{alertname=\"$ALERT\", severity=\"$SEVERITY\", alertstate=\"firing\"})"
start=$SECONDS
while (( SECONDS - start < TIMEOUT )); do
  if positive "$(prom_value "$query" 2>/dev/null || echo 0)"; then
    echo "OK: $ALERT ($SEVERITY) fired after $(( SECONDS - start ))s."
    exit 0
  fi
  sleep 10
done
echo "FAILED: $ALERT ($SEVERITY) did not fire within ${TIMEOUT}s" >&2
prom_value 'slo:sli_error:ratio_rate5m{sloth_service="checkout"}' >&2 || true
exit 1
