#!/usr/bin/env bash
# Turns the SLOs in slos/checkout.yaml into Prometheus rules with Sloth.
# Run it after editing the SLOs, then commit both files.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v sloth >/dev/null || { echo "Missing sloth: brew install sloth, or see the README." >&2; exit 1; }
sloth generate --input slos/checkout.yaml --out deploy/k8s/slo-rules.yaml 2>/dev/null
echo "Wrote deploy/k8s/slo-rules.yaml"
