#!/usr/bin/env bash
# Checks the Alertmanager config is valid and that each kind of alert lands with the right
# receiver: pages to the pager, tickets to the ticket queue, the heartbeat nowhere.
set -euo pipefail
cd "$(dirname "$0")/.."
for tool in amtool yq; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. See the README." >&2; exit 1; }
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
yq '.alertmanager.config' deploy/monitoring-values.yaml > "$work/alertmanager.yml"
amtool check-config "$work/alertmanager.yml"

expect() {
  local want="$1"; shift
  amtool config routes test --config.file="$work/alertmanager.yml" --verify.receivers="$want" "$@" >/dev/null ||
    { echo "FAILED: $* should go to $want, got $(amtool config routes test --config.file="$work/alertmanager.yml" "$@")" >&2; exit 1; }
  echo "ok: $* -> $want"
}

expect pager   alertname=CheckoutAvailabilityBudgetBurn severity=page sloth_id=checkout-availability
expect tickets alertname=CheckoutAvailabilityBudgetBurn severity=ticket sloth_id=checkout-availability
expect pager   alertname=CheckoutLatencyBudgetBurn severity=page sloth_id=checkout-latency
expect null    alertname=Watchdog severity=none
expect null    alertname=SomethingElse severity=warning
