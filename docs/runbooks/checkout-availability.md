# Runbook: CheckoutAvailabilityBudgetBurn

**What fired:** checkout requests are failing (5xx) fast enough to use up the 30-day error budget
early. The SLO is **99.5% of checkouts succeed**, so the budget is 0.5% of requests.

| Severity | Means | Do this |
|---|---|---|
| `page` | Burning at 14.4x or more. At this pace the whole month's budget is gone in about 2 days | Act now |
| `ticket` | Burning at 1x to 3x over hours to days. A slow leak | Fix within a business day |

## 1. How bad is it? (2 minutes)

Open Prometheus (`kubectl -n monitoring port-forward svc/kps-prometheus 9090`) and run:

```promql
# Error ratio right now, over the last 5 minutes
slo:sli_error:ratio_rate5m{sloth_slo="availability"}

# Which status codes, per second
sum by (code) (rate(http_requests_total{namespace="checkout", route="/checkout"}[5m]))
```

## 2. Check the usual causes, in this order

1. **Chaos switch left on.** `kubectl -n checkout exec deploy/checkout -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/chaos').read().decode())"`
   If `error_rate` is not 0: `scripts/chaos.sh 0 0`.
2. **A bad deploy.** `kubectl -n checkout rollout history deployment/checkout`.
   If errors started right after a rollout: `kubectl -n checkout rollout undo deployment/checkout`.
3. **The pod is unhealthy.** `kubectl -n checkout get pods` and `kubectl -n checkout logs deploy/checkout --tail 100`.
   Restarts or `CrashLoopBackOff` point to a startup or memory problem.

## 3. Stop the bleeding, then fix

Mitigate first (roll back, turn chaos off), confirm the 5 minute error ratio drops back to 0,
then look for the root cause. The alert clears once the short window recovers.

## 4. Afterwards

- A **page** gets a short postmortem in `docs/postmortems/`: what happened, impact (budget used),
  how it was detected, what fixed it, and what stops it next time.
- If the budget is spent, feature deploys pause until it recovers (the deploy gate, roadmap step 5).
