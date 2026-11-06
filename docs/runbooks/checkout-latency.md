# Runbook: CheckoutLatencyBudgetBurn

**What fired:** too many checkouts take longer than 300 ms. The SLO is **95% of checkouts finish
in under 300 ms**, so the budget is 5% of requests being slow.

| Severity | Means | Do this |
|---|---|---|
| `page` | Burning at 14.4x or more: most requests are slow right now | Act now |
| `ticket` | A steady share of slow requests over hours to days | Fix within a business day |

## 1. How bad is it?

```promql
# Share of slow checkouts over the last 5 minutes
slo:sli_error:ratio_rate5m{sloth_slo="latency"}

# p95 latency in seconds
histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{namespace="checkout", route="/checkout"}[5m])))
```

## 2. Check the usual causes, in this order

1. **Chaos latency left on.** If `latency_ms` is not 0, run `scripts/chaos.sh 0 0`.
2. **CPU starved.** `kubectl -n checkout top pod` (needs metrics-server) or check the pod's CPU
   in Grafana. A pod at its limit queues requests.
3. **A bad deploy.** Check `kubectl -n checkout rollout history deployment/checkout` and roll back
   with `kubectl -n checkout rollout undo deployment/checkout` if latency jumped after a rollout.

## 3. Afterwards

Same as availability: postmortem for a page, and the deploy gate holds features while the budget
is spent.
