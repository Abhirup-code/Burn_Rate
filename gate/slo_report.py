"""SLO status report: where every SLO stands right now, in one table.

Reads the rules Sloth records in Prometheus and prints, per SLO, the budget left,
how fast it is burning over each alert window, and when it runs out at that pace.
Good for a weekly reliability review, a standup, or an incident channel.

    python -m gate.slo_report --prometheus http://127.0.0.1:9090 --service checkout

Exit codes: 0 printed, 2 could not read Prometheus or found no SLOs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# The windows the burn-rate alerts look at, shortest first.
WINDOWS = ("5m", "1h", "6h", "1d", "3d")
PERIOD_SECONDS = 30 * 86400


@dataclass
class SloStatus:
    slo: str
    objective: float = math.nan
    budget_left: float = math.nan
    burn: dict[str, float] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)

    @property
    def state(self) -> str:
        if self.budget_left != self.budget_left:
            return "no data"
        if self.budget_left <= 0:
            return "spent"
        if self.budget_left < 0.25:
            return "low"
        return "ok"

    def gone_in(self) -> float | None:
        """Seconds until the budget is gone at the 5 minute burn rate, or None when
        it is not burning, or is already gone."""
        burn = self.burn.get("5m", math.nan)
        if not self.budget_left > 0 or not burn > 0.001:
            return None
        return self.budget_left * PERIOD_SECONDS / burn


def query(prometheus: str, promql: str, timeout: float = 10.0) -> list[dict]:
    url = f"{prometheus.rstrip('/')}/api/v1/query?" + urllib.parse.urlencode(
        {"query": promql}
    )
    if not url.startswith(("http://", "https://")):
        raise ValueError("Prometheus URL must start with http:// or https://")
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (scheme checked above)
        body = json.load(resp)
    if body.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {body.get('error', body)}")
    return body["data"]["result"]


def collect(prometheus: str, service: str) -> list[SloStatus]:
    sel = f'{{sloth_service="{service}"}}'
    slos: dict[str, SloStatus] = {}

    def each(promql: str):
        for r in query(prometheus, promql):
            name = r["metric"].get("sloth_slo", "?")
            yield slos.setdefault(name, SloStatus(name)), r

    for s, r in each(f"slo:objective:ratio{sel}"):
        s.objective = float(r["value"][1])
    for s, r in each(f"slo:period_error_budget_remaining:ratio{sel}"):
        s.budget_left = float(r["value"][1])
    budget = {
        s.slo: float(r["value"][1]) for s, r in each(f"slo:error_budget:ratio{sel}")
    }
    for window in WINDOWS:
        for s, r in each(f"slo:sli_error:ratio_rate{window}{sel}"):
            if budget.get(s.slo):
                s.burn[window] = float(r["value"][1]) / budget[s.slo]
    alerts = f'ALERTS{{sloth_service="{service}", alertstate="firing"}}'
    for s, r in each(alerts):
        s.alerts.append(r["metric"].get("sloth_severity", "?"))
    return sorted(slos.values(), key=lambda s: s.slo)


def pct(x: float) -> str:
    return "no data" if x != x else f"{x:.1%}"


def rate(x: float | None) -> str:
    return "–" if x is None or x != x else f"{x:.1f}x"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "not at this pace"
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def render(service: str, statuses: list[SloStatus]) -> str:
    head = "| SLO | Objective | State | Budget left | " + " | ".join(
        f"Burn {w}" for w in WINDOWS
    )
    lines = [
        f"### SLO report: {service}",
        "",
        head + " | Budget gone in | Alerts |",
        "|" + "---|" * (len(WINDOWS) + 6),
    ]
    for s in statuses:
        burns = " | ".join(rate(s.burn.get(w)) for w in WINDOWS)
        alerts = ", ".join(sorted(set(s.alerts))) or "none"
        lines.append(
            f"| {s.slo} | {pct(s.objective)} | {s.state} | {pct(s.budget_left)} | "
            f"{burns} | {duration(s.gone_in())} | {alerts} |"
        )
    lines += [
        "",
        "Burn 1x spends the budget in exactly 30 days. The page fires at 14.4x "
        "(1h and 5m) or 6x (6h and 30m), a ticket at 3x (1d and 2h) or 1x (3d and 6h).",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print where every SLO stands.")
    parser.add_argument(
        "--prometheus",
        default=os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090"),
    )
    parser.add_argument("--service", default="checkout")
    args = parser.parse_args(argv)
    try:
        statuses = collect(args.prometheus, args.service)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"Could not read the SLOs from Prometheus: {exc}", file=sys.stderr)
        return 2
    if not statuses:
        print(f"No SLOs found for service {args.service!r}.", file=sys.stderr)
        return 2
    print(render(args.service, statuses))
    return 0


if __name__ == "__main__":
    sys.exit(main())
