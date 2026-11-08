#!/usr/bin/env bash
# A rehearsed outage, start to finish, on the running lab:
#   1. the gate allows a deploy while the service is healthy
#   2. checkout starts failing (chaos switch)
#   3. the availability page fires
#   4. the gate blocks feature deploys, and lets a hotfix through with a reason
#   5. the fix goes in and the error rate drops back under budget
# It prints a timeline you can paste straight into a postmortem (docs/postmortems/).
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
prom_connect

ALERT=CheckoutAvailabilityBudgetBurn
TIMELINE=()
mark() { TIMELINE+=("$(date -u +%H:%M:%S) UTC  $1"); echo "==> $1"; }
gate() { python3 -m gate.budget_gate --prometheus http://127.0.0.1:9090 "$@"; }
firing() { prom_value "count(ALERTS{alertname=\"$ALERT\", severity=\"page\", alertstate=\"firing\"})" 2>/dev/null || echo 0; }

# Always switch chaos back off, even if a step fails.
trap 'scripts/chaos.sh 0 0 >/dev/null 2>&1 || true; kill "$PROM_PF" 2>/dev/null || true' EXIT

mark "Healthy: checking the deploy gate before the incident"
# The budget rules need a few minutes of data after a fresh start, so give the gate time.
for attempt in $(seq 1 18); do
  gate >/dev/null && break
  (( attempt < 18 )) || { gate; echo "FAILED: the gate should allow a deploy on a healthy service" >&2; exit 1; }
  sleep 10
done

mark "Incident starts: every checkout fails (scripts/chaos.sh 1 0)"
# 15 minutes is a safety net: if this script dies, the chaos still ends by itself.
scripts/chaos.sh 1 0 900 >/dev/null
started=$SECONDS

until positive "$(firing)"; do
  (( SECONDS - started < 420 )) || { echo "FAILED: no page within 7 minutes" >&2; exit 1; }
  sleep 10
done
mark "Detected: $ALERT (page) fired $(( SECONDS - started ))s after the first failure"

set +e; gate; code=$?; set -e
[ "$code" = "1" ] || { echo "FAILED: the gate should block feature deploys now (got exit $code)" >&2; exit 1; }
mark "Deploy gate blocks feature releases: error budget exhausted"

gate --hotfix "Game day: turn the chaos switch back off" >/dev/null ||
  { echo "FAILED: a hotfix with a reason should get through" >&2; exit 1; }
mark "Hotfix allowed through the gate with a recorded reason"

scripts/chaos.sh 0 0 >/dev/null
fixed=$SECONDS
mark "Mitigated: chaos switch off"

# Recovered = the last 5 minutes are back under the 0.5% error budget.
ratio='slo:sli_error:ratio_rate5m{sloth_service="checkout", sloth_slo="availability"} > 0.005'
while positive "$(prom_value "count($ratio)" 2>/dev/null || echo 1)"; do
  (( SECONDS - fixed < 480 )) || { echo "FAILED: errors did not drop under budget within 8 minutes" >&2; exit 1; }
  sleep 10
done
mark "Recovered: 5 minute error rate back under the 0.5% budget $(( SECONDS - fixed ))s after the fix"

echo
echo "Timeline (paste into docs/postmortems/):"
printf '  %s\n' "${TIMELINE[@]}"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  { echo "### Game day timeline"; echo; echo '```'; printf '%s\n' "${TIMELINE[@]}"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
fi
echo
echo "Notes:"
echo "- The page clears by itself once its 30 minute window recovers (up to about 30 minutes),"
echo "  and Alertmanager then sends a resolved notice. That delay is by design: it stops a"
echo "  flapping service from paging again and again."
echo "- The 30-day budget stays spent after this drill, so the gate keeps blocking feature"
echo "  deploys in this lab until scripts/down.sh and scripts/up.sh start it fresh."
