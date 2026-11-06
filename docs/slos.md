# SLOs and alerting policy

## The SLOs

| SLO | SLI (what is measured) | Objective | Window | Error budget |
|---|---|---|---|---|
| Availability | Share of `/checkout` requests that are not 5xx | 99.5% | 30 days | 0.5% of requests, about 3.6 hours of full outage |
| Latency | Share of `/checkout` requests under 300 ms | 95% | 30 days | 5% of requests |

The source of truth is [`slos/checkout.yaml`](../slos/checkout.yaml). Sloth generates the Prometheus
rules in [`deploy/k8s/slo-rules.yaml`](../deploy/k8s/slo-rules.yaml); CI fails if the two drift apart.

**Why 99.5% and not 99.9%?** 99.9% allows only about 43 minutes of outage a month, which a single
bad deploy on a one-replica lab service would blow through. 99.5% is a target this service can
actually keep, so the alerts mean something when they fire. Tighten it once the service runs more
replicas.

## Why burn rate instead of "error rate above X%"

A plain threshold either pages on every short blip or misses slow leaks. A **burn rate** asks how
fast the error budget is being used: a burn rate of 1 uses the whole budget in exactly 30 days, 14.4
uses it in about 2 days.

Each alert checks **a long and a short window together**. The long window proves the problem is
real; the short window proves it is still happening, so the alert clears quickly after a fix.

| Severity | Burn rate | Long window | Short window | Budget spent before it fires |
|---|---|---|---|---|
| page | 14.4x | 1 hour | 5 minutes | 2% |
| page | 6x | 6 hours | 30 minutes | 5% |
| ticket | 3x | 1 day | 2 hours | 10% |
| ticket | 1x | 3 days | 6 hours | 10% |

This is the multi-window, multi-burn-rate method from the Google SRE Workbook, chapter "Alerting on SLOs".

## Proof the alerts behave

`scripts/test-slo-rules.sh` runs promtool unit tests ([`tests/slo/checkout_test.yaml`](../tests/slo/checkout_test.yaml))
with 3 days of healthy history before each scenario:

| Scenario | Expected | Result |
|---|---|---|
| Healthy traffic | No alerts | Pass |
| Full outage | Nothing at 2 minutes, **page** at 8 minutes, latency stays quiet | Pass |
| 2% of checkouts fail | Nothing after 1 hour, **ticket** after 20 hours, never a page | Pass |
| Every checkout slower than 300 ms | **Latency page** within 50 minutes, availability stays quiet | Pass |

CI also runs the full lab on kind, turns on a 100% error rate, and checks that the real page alert
fires in Prometheus.
