# Postmortem: Game day, full checkout outage on my laptop lab

**Date:** 2026-11-09  **Severity:** page (planned drill)  **Author:** Abhirup Khan  **Status:** final

> Blameless: this is about how the system and process let the problem happen, not about who.

## Summary

A planned drill on the Burn_Rate lab, run on my MacBook Air with kind. I made every checkout
request fail on purpose for 69 seconds. The availability page fired 61 seconds after the first
failure, the deploy gate blocked feature releases, a hotfix with a recorded reason got through, and
the 5 minute error rate was back under budget 300 seconds after the fix. No real users were
affected. The drill also found a real problem before it started: setting up the lab failed halfway
on a busy laptop, which left the Grafana dashboard missing.

## Impact

| | |
|---|---|
| User-facing effect | 100% of checkout requests failed (load generator traffic only) |
| Duration | 69 seconds, from first failure (20:25:28) to the fix (20:26:37) |
| Error budget used | availability went from 100% left to **-6152.3%** (see the note under Root cause); latency stayed at 100% |
| Alert that fired | `CheckoutAvailabilityBudgetBurn` (page) |
| Time to detect | 61 seconds |
| Time to recover | 300 seconds after the fix, measured by the 5 minute error rate |

## Timeline (UTC)

Printed by `scripts/game-day.sh`. Local time was 6 hours earlier (CST).

| Time | Event |
|---|---|
| 20:23:29 | Deploy gate checked while checkout is healthy |
| 20:25:28 | **First failure:** chaos switch on, every checkout fails (`scripts/chaos.sh 1 0`) |
| 20:26:32 | **Alert fired:** `CheckoutAvailabilityBudgetBurn` (page), 61 seconds after the first failure |
| 20:26:32 | Deploy gate blocked feature releases: error budget exhausted |
| 20:26:33 | Hotfix allowed through the gate with a recorded reason |
| 20:26:37 | **Mitigated:** chaos switch off |
| 20:31:37 | **Recovered:** 5 minute error rate back under the 0.5% budget, 300 seconds after the fix |

The page itself cleared later, once its 30 minute window recovered. That is by design: it stops a
flapping service from paging again and again.

## Root cause

The outage was intentional: the chaos switch made every checkout return an error.

Two findings came out of the run.

**1. Setting up the lab failed halfway.** `make up` stopped with
`etcdserver: request timed out` while applying the checkout manifests. The Kubernetes API server
inside kind was too busy to answer in time. Why? Prometheus, Alertmanager, Grafana, the app, and
the load generator all start at once on one laptop, inside Docker's memory limit. Why did that
matter? `scripts/up.sh` ran `kubectl apply` once and gave up on the first error, even though apply
is safe to repeat. The Grafana dashboard had been created just before the timeout, but I opened
Grafana before the setup had settled and got "Dashboard not found", which looked like a broken
dashboard rather than a slow cluster.

**2. The budget numbers are extreme because the lab is new.** The cluster had about 20 minutes of
history. The SLO counts failures over 30 days, so one minute of total failure is a huge share of
20 minutes of traffic, and the budget went to -6152.3%. With 30 days of healthy history behind it,
the same outage would use a small part of the budget. The same thing makes the page fire faster
here than in production: the one hour window is mostly outage, so it crosses the 14.4x line in
about a minute. The alert unit tests, which start with 3 days of history, show the same outage
paging after about 4.5 minutes.

## Detection

The right alert fired at the right severity. `CheckoutAvailabilityBudgetBurn` paged 61 seconds in,
and nothing ticketed first or paged twice. In production, with real history, expect about
4.5 minutes for a full outage. A user would probably notice a failed checkout before that, which is
normal for a burn-rate alert: it trades a few minutes of speed for not paging on every blip.

## What went well

- The page fired once, at page severity, about a minute in.
- The deploy gate blocked feature releases as soon as the budget was gone, and still let a hotfix
  through with its reason on record.
- Recovery was measured by the 5 minute error rate, so the drill ended when the service was
  healthy, not 30 minutes later when the page cleared.
- The game day script printed a timeline I could paste straight into this postmortem.

## What went badly

- `make up` failed halfway and I did not notice before starting the drill. The drill worked anyway,
  but only because the parts it needed had been created before the timeout.
- "Dashboard not found" sent me looking for a Grafana bug when the real cause was the setup.
- A budget of -6152.3% looks alarming in a screenshot without the short-history explanation.

## Action items

| Action | Type (prevent, detect, mitigate) | Owner | Due |
|---|---|---|---|
| `scripts/up.sh` retries `kubectl apply` up to 3 times, so a timeout no longer leaves half the lab missing (done in the same change as this postmortem) | Prevent | Abhirup | Done |
| Run `make check` after `make up` and before any drill, and stop if it fails | Detect | Abhirup | Done (README) |
| Give Docker Desktop at least 6 GB of memory on a laptop | Prevent | Abhirup | Done (README) |
| Explain the short-history effect next to any screenshot of the budget | Document | Abhirup | Done (this postmortem) |
