# Missing DCGM profiling metrics: investigation

Investigated October 1, 2026, approximately 2:30–2:45 p.m. America/Chicago.

The missing metrics originate in DCGM, before the exporter or Prometheus.
Both GB10 nodes reproduce a PerfWorks driver-initialization failure with
DCGM 4.6.0 and NVIDIA driver 580.95.05. NVIDIA's forum responses identify
DGX Spark/GB10 as an unsupported DCGM platform. There is no verified
collector configuration change that enables profiling on this deployment.

## Evidence by layer

| Layer | Observed result |
|---|---|
| Prometheus | Both DCGM targets have `up=1`; existing GPU utilization samples are present. No `DCGM_FI_PROF_*` series exist. |
| Scrape configuration | Correct ServiceMonitor target and port; no metric relabeling that discards profiling fields. |
| Raw exporter endpoints | Eleven samples per node; zero profiling samples. |
| Collector CSV | All eight requested profiling fields are already present. |
| Exporter logs | Profiling fields skipped because the DCGM module is unavailable. |
| Active DCGM hostengine | Profiling module 8 reports `Failed to load` on both nodes; `profile --list -i 0` fails. |
| Installation | `libdcgmmoduleprofiling.so.4.6.0` and `libnvperf_dcgm_host.so` exist on both nodes; linked dependencies resolve. |
| Permissions | Hostengine runs as root, privileged, with administrative capabilities. Driver restricts profiling to administrators, which this process satisfies. |
| Version pairing | Hostengine is DCGM 4.6.0; exporter tag is 4.6.0-4.8.3-distroless. The DCGM client/server versions match. |
| Isolated initialization | `NVPW_InitializeTarget()` succeeds, then `NVPW_DCGM_LoadDriver returned 1`; profiling construction fails on both nodes. |
| Dynamic loader | The first-node trace loads both the CUDA driver library and PerfWorks library, with no missing-library or undefined-symbol error in the captured trace. |

The host kernel driver and loaded CUDA/NVML libraries report 580.95.05.
The container includes CUDA 13.2 and compatibility libraries, but the observed
hostengine maps use the host 580.95.05 CUDA/NVML libraries. This is not proof
that the entire profiling software stack is compatible with GB10.

## Reproduction method and safety

The production hostengine disables logging. To capture initialization errors,
short-lived hostengines were started inside the existing DCGM containers with
unique temporary Unix sockets and PID files, a 20-second timeout, and DEBUG
logging. Unneeded modules were denylisted only in those temporary processes.
Only `dcgmi profile --list -i 0` was requested; no profiling watches, stress
workloads, diagnostics, driver detach, GPU resets or SKU-check overrides were
requested. Two further first-node probes tested internal logging and dynamic
library resolution. Internal NVLOG did not reveal a more specific error.

All temporary hostengine processes exited. Subsequent process listings showed
only the original PID 1 hostengine on each node. The active hostengines and
exporters were not restarted. Both exporter endpoints remained responsive;
Prometheus still scraped them successfully. Token Labs Service specifications,
including production selectors, matched the pre-investigation snapshot.

## Interpretation and limits

The proven immediate cause is PerfWorks failing its driver initialization,
which prevents DCGM profiling from becoming available. The returned value `1`
does not establish a specific proprietary driver failure reason. The probes
alone cannot distinguish all possible driver/version/platform incompatibilities.

NVIDIA's forum response to the same Spark failure states that DCGM is not
officially supported on DGX Spark, with a December 2025 follow-up saying no
support was planned. A separate March 2026 GB10 thread reiterates that status:

- [Spark profiling-module failure](https://forums.developer.nvidia.com/t/spark-failed-to-retrieve-sm-activity-and-the-profiler-module-failed-to-load/351926)
- [GB10 DCGM support response](https://forums.developer.nvidia.com/t/dcgm-exporter-missing-process-level-attribution-for-gpu-time-slicing-on-blackwell-gb10/363037)
- [Exporter release/version pairing](https://docs.nvidia.com/datacenter/dcgm/latest/release-notes/dcgm-exporter.html)

This evidence supports treating profiling as unavailable on the tested stack,
not as a Prometheus scrape bug or a missing CSV entry. Basic metrics observed
working on GB10 do not imply official support for every DCGM feature. These
historical support statements are not proof that future releases cannot add it.

## Recommended next step

Keep the verified basic GPU/host metrics. Do not restart production, upgrade
host drivers, bypass SKU checks, or change Prometheus to chase these fields.
If profiling is essential, use a separately qualified supported GPU lab or ask
NVIDIA to confirm a supported GB10 driver/DCGM combination using these logs.
No claim is made that an OpenTelemetry Collector or a CSV change can restore
these unavailable hardware measurements. No external support request was sent.
