"""Error budget deploy gate.

Asks Prometheus how much of each SLO's 30-day error budget is left. If any budget
is used up, feature deploys stop until reliability recovers.

Below 25% budget left (--warn-below) the deploy still goes out, with a warning, so
the team hears about it before deploys stop.

Exit codes: 0 deploy, 1 blocked, 2 could not decide (Prometheus unreachable or no
SLO data). Code 2 also blocks: the gate fails closed.

A hotfix may still go out while the budget is spent, because a reliability fix is
exactly what a spent budget calls for. It needs --hotfix with a written reason, and
the override is recorded in the report and the job summary for later review.

    python -m gate.budget_gate --prometheus http://127.0.0.1:9090 --service checkout
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass

QUERY = 'slo:period_error_budget_remaining:ratio{{sloth_service="{service}"}}'
# Every SLO Sloth knows about, so a missing budget is noticed rather than skipped.
OBJECTIVES = 'slo:objective:ratio{{sloth_service="{service}"}}'
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
    low: tuple[str, ...] = ()  # SLOs still allowed, but close to running out


def _query(prometheus: str, promql: str, timeout: float) -> list[dict]:
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


def fetch_budgets(prometheus: str, service: str, timeout: float = 10.0) -> list[Budget]:
    """Reads the remaining budget for every SLO of a service from Prometheus.

    An SLO that has an objective but no budget yet comes back as NaN, so the gate
    fails closed on it instead of quietly judging the deploy on the other SLOs.
    """
    budgets = {
        r["metric"].get("sloth_slo", "?"): float(r["value"][1])
        for r in _query(prometheus, QUERY.format(service=service), timeout)
    }
    for r in _query(prometheus, OBJECTIVES.format(service=service), timeout):
        budgets.setdefault(r["metric"].get("sloth_slo", "?"), math.nan)
    return [Budget(slo, left) for slo, left in budgets.items()]


def decide(
    budgets: list[Budget], min_remaining: float = 0.0, warn_below: float = 0.25
) -> Decision:
    """Blocks when any SLO has no more than min_remaining of its budget left, and
    flags SLOs under warn_below, so the team hears about it before deploys stop."""
    budgets = sorted(budgets, key=lambda b: b.slo)
    if not budgets:
        return Decision(
            UNKNOWN,
            (),
            "No SLO data in Prometheus, so the gate cannot tell if a deploy is safe.",
        )
    # NaN means the SLO exists but has no traffic in the window yet.
    if any(math.isnan(b.remaining) for b in budgets):
        return Decision(
            UNKNOWN,
            tuple(budgets),
            "An SLO has no budget data yet, so the gate cannot judge the deploy.",
        )
    spent = [b for b in budgets if b.remaining <= min_remaining]
    if spent:
        names = ", ".join(b.slo for b in spent)
        return Decision(
            BLOCK,
            tuple(budgets),
            f"Error budget exhausted for: {names}. Only reliability fixes may deploy.",
        )
    low = tuple(b.slo for b in budgets if b.remaining < warn_below)
    if low:
        return Decision(
            ALLOW,
            tuple(budgets),
            f"Every SLO has error budget left, but it is running low for: "
            f"{', '.join(low)}. Ship carefully and favor reliability work.",
            low,
        )
    return Decision(ALLOW, tuple(budgets), "Every SLO has error budget left.")


def apply_hotfix(decision: Decision, reason: str | None, who: str) -> Decision:
    """Lets a blocked hotfix through, only with a written reason, and records who."""
    if decision.code == ALLOW or reason is None:
        return decision
    reason = reason.strip()
    if len(reason) < 10:
        return Decision(
            decision.code,
            decision.budgets,
            decision.reason + " A hotfix override needs a reason of 10+ characters.",
        )
    return Decision(
        ALLOW,
        decision.budgets,
        f"HOTFIX OVERRIDE by {who}: {reason}. Gate said: {decision.reason}",
    )


def report(decision: Decision) -> str:
    """A short Markdown report, for the terminal and the GitHub Actions job summary."""
    verdict = {
        ALLOW: "✅ Deploy allowed",
        BLOCK: "⛔ Deploy blocked",
        UNKNOWN: "⚠️ Deploy blocked (no data)",
    }[decision.code]
    if decision.reason.startswith("HOTFIX OVERRIDE"):
        verdict = "🚑 Hotfix allowed while the budget is spent"
    elif decision.low:
        verdict = "🟡 Deploy allowed, budget running low"
    lines = [f"### {verdict}", "", decision.reason, ""]
    if decision.budgets:
        lines += ["| SLO | Error budget left |", "|---|---|"]
        lines += [
            f"| {b.slo} | "
            f"{'no data' if math.isnan(b.remaining) else f'{b.remaining:.1%}'} |"
            for b in decision.budgets
        ]
    return "\n".join(lines) + "\n"


def as_json(decision: Decision) -> str:
    """The decision for other tools: a pipeline step, a chat bot, a dashboard."""
    return json.dumps(
        {
            "decision": {ALLOW: "allow", BLOCK: "block", UNKNOWN: "unknown"}[
                decision.code
            ],
            "exit_code": decision.code,
            "hotfix": decision.reason.startswith("HOTFIX OVERRIDE"),
            "reason": decision.reason,
            # NaN (no data yet) is not valid JSON, so it becomes null.
            "budget_left": {
                b.slo: None if math.isnan(b.remaining) else b.remaining
                for b in decision.budgets
            },
            "running_low": list(decision.low),
        },
        allow_nan=False,
    )


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
    parser.add_argument(
        "--warn-below",
        type=float,
        default=0.25,
        help="Warn, but still allow, below this share of budget left (default 0.25)",
    )
    parser.add_argument(
        "--hotfix",
        metavar="REASON",
        default=os.environ.get("HOTFIX_REASON") or None,
        help="Deploy anyway because this is a reliability fix; the reason is recorded",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the decision as JSON instead of Markdown (the job summary stays)",
    )
    args = parser.parse_args(argv)
    who = os.environ.get("GITHUB_ACTOR") or os.environ.get("USER") or "unknown"

    try:
        decision = decide(
            fetch_budgets(args.prometheus, args.service),
            args.min_remaining,
            args.warn_below,
        )
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        decision = Decision(
            UNKNOWN, (), f"Could not read the error budget from Prometheus: {exc}"
        )
    decision = apply_hotfix(decision, args.hotfix, who)

    text = report(decision)
    print(as_json(decision) if args.json else text)
    write_summary(text)
    if decision.low and os.environ.get("GITHUB_ACTIONS") == "true":
        # Shows up as a yellow annotation on the workflow run.
        print(f"::warning title=Error budget running low::{decision.reason}")
    return decision.code


if __name__ == "__main__":
    sys.exit(main())
