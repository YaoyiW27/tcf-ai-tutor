# infra/k8s/monitoring/ — in-cluster monitoring + autoscaling

Adds **kube-prometheus-stack** (Prometheus + Grafana + Operator) and **prometheus-adapter**
so an HPA can scale the gateway on `gateway_inflight_requests`. Assumes the app is deployed
by the `tcf` chart (see `../README.md`) with `serviceMonitor.enabled` and `hpa.enabled`.

## Install
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# 1) kube-prometheus-stack (release name "kps" — the adapter URL depends on it)
helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f infra/k8s/monitoring/kube-prometheus-stack.values.yaml

# 2) prometheus-adapter (exposes the gateway custom metric)
helm install prometheus-adapter prometheus-community/prometheus-adapter \
  -n monitoring -f infra/k8s/monitoring/prometheus-adapter.values.yaml

# 3) (optional) import the gateway dashboard into the in-cluster Grafana
kubectl -n monitoring create configmap tcf-gateway-dashboard \
  --from-file=gateway.json=infra/observability/grafana/dashboards/gateway.json
kubectl -n monitoring label configmap tcf-gateway-dashboard grafana_dashboard=1
```

## Verify the custom metric + HPA
```bash
# gateway scraped by Prometheus (impl=python):
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 9090:9090 &
#   open :9090 → Status/Targets → the gateway ServiceMonitor target is up

# custom metric is served:
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/tcf/pods/*/gateway_inflight_requests" | jq .

# HPA reads it (not <unknown>):
kubectl -n tcf get hpa
```

## Autoscaling demo (free — gateway forwards to the in-cluster mock)
Install the app with the mock + HPA enabled and the gateway pointed at the mock:
```bash
helm upgrade --install tcf infra/k8s/tcf -n tcf --create-namespace \
  -f infra/k8s/tcf/values-secret.yaml \
  --set serviceMonitor.enabled=true --set hpa.enabled=true \
  --set mockUpstream.enabled=true \
  --set gateway.inferenceBackend=openai \
  --set gateway.upstreamBaseUrl=http://tcf-mock:9000/v1
```
Then drive load and watch it scale:
```bash
kubectl -n tcf get hpa,deploy/tcf-gateway -w        # shell 1
kubectl -n tcf port-forward svc/tcf-gateway 8001:8001 &   # shell 2
python benchmarks/bench_gateway.py --url http://localhost:8001/v1 \
  --model mock-model --concurrency 64 --n 4000
# in-flight per gateway pod rises above the target → HPA scales tcf-gateway up;
# after load stops it scales back to minReplicas.
```

## Teardown
```bash
helm uninstall prometheus-adapter kps -n monitoring
```
