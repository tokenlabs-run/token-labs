# Hardware observability verification

Verified October 1, 2026 at 1:59 p.m. America/Chicago.

Applied only the existing DCGM ServiceMonitor, one PrometheusRule and one Grafana ConfigMap. All Token Labs Service and Deployment specifications matched the pre-change snapshots after deployment. No inference rollout, node drain, GPU reset or exporter restart was performed.

## Exact raw samples

| Metric | spark-01 | spark-02 |
|---|---:|---:|
| `DCGM_FI_DEV_DEC_UTIL` | 0 | 0 |
| `DCGM_FI_DEV_ENC_UTIL` | 0 | 0 |
| `DCGM_FI_DEV_GPU_TEMP` | 47 | 49 |
| `DCGM_FI_DEV_GPU_UTIL` | 0 | 0 |
| `DCGM_FI_DEV_MEMORY_TEMP` | 0 | 0 |
| `DCGM_FI_DEV_MEM_COPY_UTIL` | 0 | 0 |
| `DCGM_FI_DEV_PCIE_REPLAY_COUNTER` | 0 | 0 |
| `DCGM_FI_DEV_POWER_USAGE` | 11.689 | 12.044 |
| `DCGM_FI_DEV_SM_CLOCK` | 2405 | 2392 |
| `DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION` | 4.4754414e+07 | 1.16112267098e+11 |
| `DCGM_FI_DEV_VGPU_LICENSE_STATUS` | 0 | 0 |

Raw sample labels and numeric values are in the two `.metrics` files. The collector field list is in `dcgm-metrics.observed.csv`. `verification.json` records live targets, rule health and all Grafana datasource query results. Zero GPU utilization is an observed idle sample, not proof of workload responsiveness. Memory temperature zero and vGPU license status are not used for health decisions.

## Verified changes

- The scrape was already live; the repository now includes its ServiceMonitor and matches the live 15-second interval. Both targets are up with node and cluster labels.
- Twenty-one recording/alert rules evaluate successfully. Alerts detect failed/missing DCGM and host telemetry, five missing GPU fields, recent host OOMs and recent PCIe replay increases.
- The provisioned `Token Labs / GB10 hardware health` dashboard has twelve panels. All eleven non-alert queries returned both nodes through Grafana; the inactive-alert query correctly returned no samples.
- Promtool syntax and eleven scenario tests passed, including healthy idle samples, absent and failed targets, partial scrapes, sentinel values, counter increments, historical values, resets and recovery. Both parent Kustomize bundles render; server dry runs pass.
- Failure behavior was tested with isolated series. No production faults were injected and no external notification delivery was tested.

## Live state differs from repository assumptions

- Live GPU Operator image is `nvcr.io/nvidia/gpu-operator:v26.7.0`; exporter is `4.6.0-4.8.3-distroless`. Homelab `infrastructure/controllers/gpu-operator.yaml` locally specifies `v25.10.x`, while the live Flux HelmRelease specifies `v26.7.0`. The custom collector CSV was not found in either checkout. No infrastructure reconciliation was triggered. Kubernetes reports v1.37.0; this report does not assert the installation is still MicroK8s.
- Node-exporter is healthy on both workers and the controller. Existing network-error/flapping, filesystem and memory alerts are loaded.
- Token Labs SLO rules are loaded, but their scrape-based availability is not a verified public availability or node SLA.
- No Loki or Promtail workload was found. Their repository manifests do not establish a deployed log pipeline.
- No OpenRouter synthetic-monitor workload or its expected Secret was found. Its repository image remains `latest`; activation needs a tested pinned image and dedicated low-quota credentials.
- An OpenTelemetry Collector is running with a trace-only pipeline, requests of 100m CPU/128Mi memory and limits of 500m CPU/512Mi. Its Tempo destination has zero replicas and logs show connection refusals. No additional Collector was deployed.
- The live cluster has no AuthPolicy resource type. Gateway routes and model-aggregator exist, but repository descriptions of Kuadrant tenant policy do not establish live tenant isolation. No tenant access to these operator metrics was added.
- Prometheus has pre-existing failed control-plane scrapes for controller-manager, scheduler, etcd and kube-proxy. Fixing their listener exposure is outside this monitoring-only change.

## Unverified or deferred

Xid is not configured; no Xid detection is claimed. ECC is not configured or observed. Profiling metrics are configured but skipped in exporter logs; no profiling or NVLink throughput claim is made. PCIe replay samples do not establish PCIe AER coverage. Switch forwarding state, fabric internals, multi-tenant isolation, automated remediation, notifications and a 99.9% node SLA remain unverified. Current GPU allocation is exclusive, not time slicing.

Suggested accurate resume wording: "Implemented and live-validated Prometheus/Grafana hardware observability for a two-node NVIDIA GB10 inference lab, including missing-telemetry detection, GPU/host dashboards, and tested OOM/PCIe replay alerts without changing active inference deployments."
