#!/usr/bin/env bash
# Unit tests for the alerts: feeds Prometheus fake traffic (healthy, a slow leak, a full
# outage, a slowdown) and checks exactly which alerts fire. No cluster needed.
set -euo pipefail
cd "$(dirname "$0")/.."
for tool in promtool yq; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. See the README." >&2; exit 1; }
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# promtool reads plain rule groups, so pull them out of the PrometheusRule resource.
yq '.spec' deploy/k8s/slo-rules.yaml > "$work/rules.yml"
cp tests/slo/*_test.yaml "$work/"

promtool check rules "$work/rules.yml"
promtool test rules "$work"/*_test.yaml
