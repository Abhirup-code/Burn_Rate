# Burn Rate

**SLOs, burn-rate alerts, and an error-budget deploy gate on Kubernetes.**

Teams argue about whether a service is "reliable enough" without numbers to settle it. Burn Rate runs a
small checkout service the way an SRE team runs production: it sets a reliability target (an SLO), tracks
how much failure that target allows (the error budget), pages someone when the budget burns too fast, and
blocks feature deploys once the budget is gone.

## The targets

| SLO | Target | Window | Error budget |
|---|---|---|---|
| Availability: checkout requests that succeed | 99.5% | 30 days | 0.5% of requests, about 3.6 hours of full outage |
| Latency: checkout requests faster than 300 ms | 95% | 30 days | 5% of requests may be slower |

## How it fits together

```
k6 load test ──> checkout service (/metrics) ──> Prometheus
                      ▲                              │
            chaos switch: errors / latency   SLO rules + burn-rate alerts
                                                     │
                    Grafana SLO dashboard <──────────┤
                    Alertmanager: page or ticket <───┤
                                                     ▼
            Deploy pipeline asks "budget left?" ──> deploy, or block unless labeled hotfix
```

## Roadmap

- [x] **1. Checkout service with metrics and a chaos switch**
- [x] **2. Local Kubernetes (kind) with Prometheus and Grafana, plus steady k6 traffic**
- [ ] 3. SLOs as code and multi-window burn-rate alerts
- [ ] 4. Grafana SLO dashboard: budget left, burn rate, time to exhaustion
- [ ] 5. Error-budget deploy gate in GitHub Actions, with a hotfix override
- [ ] 6. Game day: break it on purpose, watch the alerts and the gate, write the postmortem

## The checkout service

| Endpoint | What it does |
|---|---|
| `GET /checkout` | The user-facing request the SLOs measure |
| `GET /healthz` | Health check for Kubernetes. Not counted as user traffic |
| `GET /metrics` | Prometheus metrics |
| `GET /chaos` | Shows the current chaos settings |
| `PUT /chaos` | Makes checkout fail or slow down on purpose. Needs `Authorization: Bearer $CHAOS_TOKEN` |

Metrics the SLOs are built on:

- `http_requests_total{route, method, code}` counts every request. Availability is the share that are not 5xx.
- `http_request_duration_seconds` is a histogram with a bucket at **0.3 s**, so the latency SLO can count requests under 300 ms exactly.

Design choices:

- **Labels use the route template, not the raw URL.** Unknown paths all share `route="unmatched"`, so a scanner hitting random URLs cannot create thousands of time series.
- **Health checks and metric scrapes are left out** of the numbers, because they are not user traffic and would make the service look more reliable than it is.
- **Chaos is locked unless a token is set**, and the token is compared in constant time.

## Run the whole lab on Kubernetes

Everything runs on your laptop for free: a one-node [kind](https://kind.sigs.k8s.io/) cluster, the
kube-prometheus-stack chart (Prometheus, Alertmanager, Grafana), the checkout service, and a k6 load
generator sending 10 checkout requests per second.

**You need:** Docker Desktop (give it at least 6 GB of memory), plus `kind`, `kubectl`, and `helm`:

```bash
brew install kind kubectl helm
```

**Start it** (about 5 minutes the first time):

```bash
scripts/up.sh
```

**Look around** (each in its own terminal):

```bash
kubectl -n monitoring port-forward svc/kps-prometheus 9090
kubectl -n monitoring port-forward svc/kps-grafana 3000:80
```

- Prometheus at http://localhost:9090, try `sum by (code) (rate(http_requests_total{route="/checkout"}[1m]))`
- Grafana at http://localhost:3000, user `admin`, password from
  `kubectl -n monitoring get secret kps-grafana -o jsonpath='{.data.admin-password}' | base64 --decode`

**Break it on purpose, then fix it:**

```bash
scripts/chaos.sh 0.05 0     # 5% of checkouts fail
scripts/chaos.sh 0 400      # every checkout takes 400 ms more
scripts/chaos.sh 0 0        # healthy again
```

**Check it end to end, or tear it down:**

```bash
scripts/check.sh            # Prometheus is scraping checkout traffic
scripts/down.sh             # deletes the cluster
```

### What runs where

| Namespace | What | Why |
|---|---|---|
| `monitoring` | Prometheus, Alertmanager, Grafana (chart `kube-prometheus-stack` 92.21.1) | Collects metrics, will fire alerts, shows dashboards |
| `checkout` | `checkout` Deployment, Service, and ServiceMonitor | The service the SLOs measure. Prometheus scrapes it every 15 s |
| `checkout` | `loadgen` (k6) | Steady traffic, so the SLOs always have data |

Hardening, even in a lab: the `checkout` namespace enforces the Kubernetes **restricted** Pod Security
standard, both containers run as non-root with a read-only filesystem and no Linux capabilities, and
the chaos token is a random Kubernetes Secret created at setup, never stored in the repo.

The checkout service runs **one replica on purpose**: the chaos switch lives in memory, so every
request has to reach the same pod for an injected error rate to mean what it says.

## Run just the service

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
CHAOS_TOKEN=change-me uvicorn app.main:app --port 8000
```

Then, in a second terminal:

```bash
curl localhost:8000/checkout
curl -X PUT localhost:8000/chaos -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" -d '{"error_rate": 0.05, "latency_ms": 0}'
curl -s localhost:8000/metrics | grep http_requests_total
```

Or with Docker:

```bash
docker build -t burn-rate .
docker run -p 8000:8000 -e CHAOS_TOKEN=change-me burn-rate
```

## Quality

- 13 tests cover metrics, label safety, the chaos switch, its token, and input limits.
- CI runs lint, tests, a container build, and a smoke test on every push. Actions are pinned to commit hashes, and the workflows have read-only permissions.
- A second workflow validates the Kubernetes manifests (kubeconform) and scripts (ShellCheck), then **builds the whole lab on kind with the same `scripts/up.sh` you run locally**, checks that Prometheus is scraping checkout traffic, turns on chaos, and confirms the injected errors show up in the metrics.
- The container runs as a non-root user.

## License

Apache 2.0
