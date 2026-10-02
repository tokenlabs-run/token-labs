# GB10 hardware monitoring

This operator-only bundle monitors the two expected physical GPU workers,
`spark-01` and `spark-02`. It adds no workload, tenant endpoint, node agent,
GPU diagnostic process, or automated remediation. The expected-node recording
rule is deliberate inventory: removing a target or node must not silently
remove its missing-telemetry alert. Update it when the intended fleet changes.

## Deploy

The infrastructure Prometheus/Grafana installation is Flux-managed in a separate
infrastructure path. Token Labs integrations use `kubectl apply`, as in the
parent monitoring README. Apply this subset to avoid deploying the parent
bundle's synthetic monitor and incident harness before their prerequisites exist:

```sh
kubectl apply --dry-run=server -f deploy/platform/observability/dcgm-servicemonitor.yaml
kubectl apply --dry-run=server -k deploy/platform/monitoring/hardware
kubectl apply -f deploy/platform/observability/dcgm-servicemonitor.yaml
kubectl apply -k deploy/platform/monitoring/hardware
```

The existing GPU Operator Service is `gpu-operator/nvidia-dcgm-exporter`,
with label `app=nvidia-dcgm-exporter` and named port `gpu-metrics` on 9400.
Prometheus selects the `monitoring/dcgm-exporter` ServiceMonitor through
`release=kube-prometheus-stack`. The Operator-owned ServiceMonitor lacks that
release label and is not selected. Do not enable both and double-scrape the GPUs.
The maintained ServiceMonitor preserves the observed live 15-second interval
and adds `node` from Kubernetes discovery plus `cluster=token-labs`.

## Respond to alerts

- `TokenLabsDCGMTelemetryUnavailable`: inspect exporter readiness, Service
  EndpointSlices, ServiceMonitor selection, and Prometheus target errors.
  A failed scrape and a disappeared target both fire after two minutes.
- `TokenLabsHOSTTelemetryUnavailable`: inspect node-exporter and kube-state-metrics
  discovery. The node identity join also depends on `kube_pod_info`.
- `TokenLabsGPUFieldMissing`: a successful scrape has lost a previously verified
  field for five minutes. Check the named field, collector configuration and logs.
  Negative or very large sentinel samples are excluded from recording rules.
  This alert is suppressed while the exporter-unavailable alert applies.
- `TokenLabsHostOOMObserved`: the host OOM counter increased in the past five
  minutes. Inspect kernel logs and memory pressure; correlate with serving latency.
- `TokenLabsGPUReplayObserved`: the emitted PCIe replay counter increased in a
  five-minute window, with the condition present for two minutes. Investigate
  driver diagnostics and correlate with latency. This is not an AER alert or proof
  that a GPU failed. An isolated increment expires; counter resets are handled.

All added alerts are warnings. Notification delivery has not been validated;
these rules do not install paging or customer-notification integrations.
Do not reset GPUs, delete inference pods, drain nodes, or change active model
Deployments in response. Follow `deploy/models/MODEL_ROLLOUT_RUNBOOK.md` for any
future production intervention, with separate ready capacity and rollback.

The existing kube-prometheus-stack rules already cover memory pressure, CPU,
filesystems, network errors and interface flapping. This bundle reuses their
signals in a focused dashboard rather than duplicating those alerts. Host
network panels sum `en.*` interfaces; they are host NIC observations, not
switch forwarding, firewall synchronization, RoCE or InfiniBand health checks.

## Validate

Requires Python 3, PyYAML, kubectl, and promtool. Validation on 2026-10-01 used
promtool 2.50.1, matching the live Prometheus server.

```sh
python3 scripts/monitoring/test_hardware_rules.py --promtool /path/to/promtool
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 19090:9090
# In another terminal:
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 13000:80
# In another terminal:
python3 scripts/monitoring/verify_hardware.py --output /tmp/hardware-verification
```

The verifier checks raw exporter samples, both healthy scrape targets, live rule
health, Grafana provisioning and each panel's query through Grafana's Prometheus
datasource. It reads the existing Grafana admin Secret into memory without
printing or saving credentials. Run it only with operator access. It does not
send notifications or inject faults into production. Unit tests exercise failure
and recovery with synthetic series outside the cluster.

Dashboard UID: `token-labs-hardware`. Missing hardware samples stay as no data;
only scrape-status panels intentionally display unavailable as zero. These are
physical GPU and host observations, with `cluster`, `node`, and an operator
`service` label on derived metrics. They are not tenant usage or billing data.
No tenant identity is inferred from exporter pod labels.

## Collector configuration and limits

The live collector is ConfigMap `gpu-operator/dcgm-metrics-config`, key
`dcgm-metrics.csv`, mounted at `/etc/dcgm-exporter/dcgm-metrics.csv` and selected
by `DCGM_EXPORTER_COLLECTORS`. Its observed content is saved in
`results/2026-10-01-hardware-observability/dcgm-metrics.observed.csv` as evidence,
not a reconciled manifest. The homelab repository enables DCGM and its exporter
in `infrastructure/controllers/gpu-operator.yaml`, but neither that checkout nor
Token Labs defines this custom ConfigMap. Homelab locally specifies `v25.10.x`;
the live Flux HelmRelease specifies `v26.7.0`. Resolve that drift through the
infrastructure owner before changing Operator configuration.
This deployment does not change it or the exporter
DaemonSet. The ServiceMonitor controls scraping, not the exported field list.

At verification time Xid and ECC fields were not configured. Eight configured
`DCGM_FI_PROF_*` fields were skipped because the profiling module was not loaded.
Framebuffer fields were configured but absent. Memory temperature was emitted
as zero on both nodes and is not treated as a verified temperature sensor.
PCIe replay is emitted; PCIe AER and NVLink throughput were not verified.

Both nodes selected the device plugin's `exclusive` configuration with one GPU
replica and sharing strategy `none`. A time-slicing configuration also exists
but is not the selected node configuration. If sharing is enabled later, these
physical-device samples must not be presented as per-tenant utilization.

The exporter connects to a shared `nvidia-dcgm:5555` Service. Current samples
match each worker's hostname and distinct UUID. This check is a snapshot, not
proof of attribution after every hostengine reconnect; preserve that check in
future exporter changes.

## Roll back this monitoring addition

Delete only this bundle with `kubectl delete -k deploy/platform/monitoring/hardware`.
Restore the pre-change ServiceMonitor endpoint configuration: `gpu-metrics`,
`/metrics`, `interval: 15s`, without the added relabelings or explicit timeout.
Do not delete the working ServiceMonitor. No model rollback is needed because
this change does not modify inference resources.
