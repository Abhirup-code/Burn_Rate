#!/usr/bin/env bash
# Builds the whole lab on your machine: a kind cluster, Prometheus, Alertmanager, Grafana,
# the checkout service, and steady k6 traffic. Safe to run again; it updates what is there.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER="${CLUSTER:-burn-rate}"
IMAGE="burn-rate:dev"
CHART_VERSION="92.21.1" # kube-prometheus-stack

for tool in docker kind kubectl helm; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. See the README for how to install it." >&2; exit 1; }
done

echo "==> Cluster"
if ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER" --config deploy/kind.yaml --wait 120s
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

echo "==> Checkout image"
docker build -t "$IMAGE" .
kind load docker-image "$IMAGE" --name "$CLUSTER"

echo "==> Prometheus, Alertmanager, and Grafana (takes a few minutes the first time)"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update >/dev/null
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  --version "$CHART_VERSION" --namespace monitoring --create-namespace \
  --values deploy/monitoring-values.yaml --wait --timeout 15m

# The operator creates Prometheus after the chart installs, so wait for it separately.
echo "==> Waiting for Prometheus to start"
for _ in $(seq 1 60); do
  kubectl -n monitoring get statefulset prometheus-kps-prometheus >/dev/null 2>&1 && break
  sleep 5
done
kubectl -n monitoring rollout status statefulset/prometheus-kps-prometheus --timeout 300s

echo "==> Checkout service and load generator"
kubectl apply -f deploy/k8s/namespace.yaml
# A random chaos token, made once and kept. It is never written to the repo.
if ! kubectl -n checkout get secret checkout-chaos >/dev/null 2>&1; then
  kubectl -n checkout create secret generic checkout-chaos \
    --from-literal=token="$(openssl rand -hex 16)"
fi
# On a busy laptop the API server can time out mid-apply ("etcdserver: request timed out"),
# which left half the lab missing in the first game day. Apply is safe to repeat, so retry.
for attempt in 1 2 3; do
  kubectl apply -k deploy/k8s && break
  if [ "$attempt" = 3 ]; then
    echo "kubectl apply failed 3 times. Is Docker short on memory? See docs/postmortems/." >&2
    exit 1
  fi
  echo "==> kubectl apply failed, retrying in 10 seconds (attempt $attempt of 3)"
  sleep 10
done
kubectl -n checkout rollout restart deployment/checkout >/dev/null # pick up a rebuilt image
kubectl -n checkout rollout status deployment/checkout --timeout 180s
kubectl -n checkout rollout status deployment/loadgen --timeout 180s

cat <<'MSG'

Done. In separate terminals:

  Prometheus:  kubectl -n monitoring port-forward svc/kps-prometheus 9090
  Grafana:     kubectl -n monitoring port-forward svc/kps-grafana 3000:80
  Checkout:    kubectl -n checkout port-forward svc/checkout 8000:80

Grafana login: admin, and this password:
  kubectl -n monitoring get secret kps-grafana -o jsonpath='{.data.admin-password}' | base64 --decode; echo

Break it on purpose:   scripts/chaos.sh 0.05 0     (5% errors)
Back to healthy:       scripts/chaos.sh 0 0
MSG
