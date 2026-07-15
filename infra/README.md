# infra/ — Containers, Kubernetes, Observability

**Status: planned.**

Deployment and monitoring for the stack. Planned contents:

- Dockerfiles for the app/workload, the gateway, and the vLLM server (or the official image).
- Kubernetes manifests for local dev (kind / k3s): Deployments, ConfigMaps, resource requests
  (GPU requests for vLLM), packaged as Helm charts or Kustomize.
- `kube-prometheus-stack` (Prometheus + Grafana) with dashboards: inference performance
  (QPS, P50/95/99, TTFT), resources (GPU util %, VRAM, KV-cache), and business (tokens, cost, errors).
- GPU-aware HPA driven by custom Prometheus metrics (e.g. queue depth / GPU utilization).
- Alerting rules (GPU OOM risk, latency spikes, error-rate thresholds).

See [../docs/architecture-v2-infra.md](../docs/architecture-v2-infra.md).
