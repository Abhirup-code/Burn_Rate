#!/usr/bin/env bash
# Prints where every checkout SLO stands: budget left, burn rate per alert window,
# when the budget runs out at this pace, and what is firing.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
prom_connect || exit 2
python3 -m gate.slo_report --prometheus http://127.0.0.1:9090 "$@"
