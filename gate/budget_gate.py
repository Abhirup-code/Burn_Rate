"""Error budget deploy gate.

Asks Prometheus how much of each SLO's 30-day error budget is left. If any budget
is used up, feature deploys stop until reliability recovers.

Exit codes: 0 deploy, 1 blocked, 2 could not decide (Prometheus unreachable or no
SLO data). Code 2 also blocks: the gate fails closed.

    python -m gate.budget_gate --prometheus http://127.0.0.1:9090 --service checkout
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass

QUERY = 'slo:period_error_budget_remaining:ratio{{sloth_service="{service}"}}'
ALLOW, BLOCK, UNKNOWN = 0, 1, 2


@dataclass(frozen=True)
class Budget:
    slo: str
    remaining: float  # 1.0 = untouched, 0 = used up, below 0 = SLO broken this period


@dataclass(frozen=True)
class Decision:
    code: int
    budgets: tuple[Budget, ...]
    reason: str


def fetch_budgets(prometheus: str, service: str, timeout: float = 10.0) -> list[Budget]:
    """Reads the remaining budget for every SLO of a service from Prometheus."""
    url = f"{prometheus.rstrip('/')}/api/v1/query?" + urllib.parse.urlencode(
        {"query": QUERY.format(service=service)}
    )
    if not url.startswith(("http://", "https://")):
        raise ValueError("Prometheus URL must start with http:// or https://")
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (scheme checked above)
        body = json.load(resp)
    if body.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {body.get('error', body)}")
    return [
        Budget(r["metric"].get("sloth_slo", "?"), float(r["value"][1]))
        for r in body["data"]["result"]
    ]


def decide(budgets: list[Budget], min_remaining: float = 0.0) -> Decision:
    """Blocks when any SLO has no more than min_remaining of its budget left."""
    budgets = sorted(budgets, key=lambda b: b.slo)
    if not budgets:
        return Decision(
            UNKNOWN,
            (),
            "No SLO data in Prometheus, so the gate cannot tell if a deploy is safe.",
        )
    if any(
        b.remaining != b.remaining for b in budgets
    ):  # NaN: no traffic in the window
        return Decision(
            UNKNOWN,
            tuple(budgets),
            "An SLO has no data yet (NaN), so the gate cannot judge the deploy.",
        )
    spent = [b for b in budgets if b.remaining <= min_remaining]
    if spent:
        names = ", ".join(b.slo for b in spent)
        return Decision(
            BLOCK,
            tuple(budgets),
            f"Error budget exhausted for: {names}. Only reliability fixes may deploy.",
        )
    return Decision(ALLOW, tuple(budgets), "Every SLO has error budget left.")


def report(decision: Decision) -> str:
    """A short Markdown report, for the terminal and the GitHub Actions job summary."""
    verdict = {
        ALLOW: "✅ Deploy allowed",
        BLOCK: "⛔ Deploy blocked",
        UNKNOWN: "⚠️ Deploy blocked (no data)",
    }[decision.code]
    lines = [f"### {verdict}", "", decision.reason, ""]
    if decision.budgets:
        lines += ["| SLO | Error budget left |", "|---|---|"]
        lines += [f"| {b.slo} | {b.remaining:.1%} |" for b in decision.budgets]
    return "\n".join(lines) + "\n"


def write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Block feature deploys when an SLO's error budget is used up."
    )
    parser.add_argument(
        "--prometheus",
        default=os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090"),
    )
    parser.add_argument("--service", default="checkout")
    parser.add_argument(
        "--min-remaining",
        type=float,
        default=0.0,
        help="Block at or below this share of budget left (default 0)",
    )
    args = parser.parse_args(argv)

    try:
        decision = decide(
            fetch_budgets(args.prometheus, args.service), args.min_remaining
        )
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        decision = Decision(
            UNKNOWN, (), f"Could not read the error budget from Prometheus: {exc}"
        )

    text = report(decision)
    print(text)
    write_summary(text)
    return decision.code


if __name__ == "__main__":
    sys.exit(main())
