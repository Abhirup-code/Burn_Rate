#!/usr/bin/env bash
# Runs the error budget deploy gate against the lab's Prometheus.
# Exit 0 deploy, 1 blocked, 2 no data. Extra arguments go to the gate, for example:
#   scripts/gate.sh --hotfix "Roll back the bad release"
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
prom_connect || exit 2
python3 -m gate.budget_gate --prometheus http://127.0.0.1:9090 "$@"
