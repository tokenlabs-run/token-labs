# Heterogeneous H200 to MI300X prefill/decode

This harness evaluates semantic KV compatibility for
`Qwen/Qwen3-30B-A3B-Instruct-2507-FP8` across different GPU vendors:

```text
client -> vLLM Mooncake proxy
       -> H200 vLLM kv_producer (prefill)
       -> Mooncake 0.3.13 TCP
       -> MI300X vLLM kv_consumer (decode)
```

The evaluated deployment uses vLLM 0.26.0 on both nodes. The H200 is a
DigitalOcean GPU Droplet and the MI300X is an AMD Developer Cloud instance.
The nodes therefore communicate over public TCP, not a shared VPC or RDMA
fabric. Mooncake stages TCP transfers through host memory. This is a
compatibility and cross-cloud performance evaluation, not a recommended
production network topology.

The original recorded run deliberately excluded Dynamo for a plain-vLLM
isolation test. The follow-up validation below closes the Dynamo integration
gate while preserving the original result as a separate baseline.

## Dynamo validation

The follow-up Dynamo deployment uses the same model and Mooncake data path:

```text
client -> H200 Dynamo frontend (loopback HTTP)
       -> H200 Dynamo + vLLM prefill worker
       -> Mooncake 0.3.13 TCP
       -> MI300X Dynamo + vLLM decode worker
```

Both GPU workers run `ai-dynamo==1.4.2` and vLLM 0.26.0. Keep the CUDA and
ROCm images on their respective Mooncake 0.3.13 build lineages; mixing the
stock 0.3.10 wheel or the older ROCm build produces incompatible segment
descriptors. `MC_FORCE_TCP=1` must be confirmed in both startup logs.

Dynamo uses etcd discovery. The supplied etcd launcher binds only to H200
loopback. In the cross-cloud deployment, the MI300X reaches it through a
client-managed SSH forward rather than a public unauthenticated etcd port.
The Dynamo frontend also binds only to H200 loopback; run the benchmark on
that host or reach it through SSH.

vLLM resolves the Mooncake bootstrap host to `127.0.0.1` when Dynamo uses
external load balancing. That is incorrect for cross-node P/D. The overlay
applies `dynamo_mooncake_bootstrap_host.patch`, which preserves upstream
behavior unless `DYN_MOONCAKE_BOOTSTRAP_HOST` is set. The H200 prefill launch
script sets it to the prefill node's routable address.

Launch the components after building the CUDA and ROCm overlays from their
Mooncake 0.3.13 base images:

```bash
# H200
./launch_dynamo_etcd.sh
PUBLIC_IP=<h200-address> ./launch_dynamo_frontend.sh
PUBLIC_IP=<h200-address> ./launch_dynamo_prefill.sh

# MI300X, after forwarding its 127.0.0.1:2379 to H200 etcd
PUBLIC_IP=<mi300x-address> ./launch_dynamo_decode.sh
```

Run the same matrix with the Dynamo frontend and its metrics endpoint:

```bash
BASE_URL=http://127.0.0.1:8000 \
DECODE_METRICS_URL=http://127.0.0.1:8000/metrics \
RESULT_DIR=/root/dynamo-hetero-matrix \
  ./run_matrix.sh
```

Capture the H200 prefill log from the benchmark interval, then validate result
geometry and Mooncake byte accounting:

```bash
./analyze_dynamo_matrix.py /root/dynamo-exact-matrix prefill-benchmark.log \
  /root/dynamo-wire-byte-verification > matrix-summary.csv
```

For this fixed matrix, 381 requests contain 2,210,816 input tokens. At 98,304
KV bytes per token, the required transferred payload is 217,332,056,064 bytes
(`202.40625 GiB`). Mooncake's periodic metrics are sampled rather than
cumulative, so the validator combines exact request token counts with 1k and
8k wire-byte probes and requires zero failed transfers.

## Server configuration

On the H200, set its reachable address and launch the prefill server:

```bash
PUBLIC_IP=<h200-address> ./launch_mooncake_prefill.sh
```

On the MI300X, use the ROCm image and launch the decode server:

```bash
PUBLIC_IP=<mi300x-address> ./launch_mooncake_decode.sh
```

On the H200, launch the request-routing proxy:

```bash
PREFILL_IP=<h200-address> DECODE_IP=<mi300x-address> \
  ./launch_mooncake_proxy.sh
```

Both vLLM workers use block size 16, prefix caching disabled, four Mooncake
workers, eight TCP lanes, enlarged queue/admission limits, and a 300-second
transfer timeout. These settings are material: 8k/8k c=8 overflowed Mooncake's
descriptor capacity with 16 workers, while 8k/8k c=32 exceeded the default
30-second transfer timeout with four workers.

## Benchmark and validation

Run all 21 requested points through the proxy:

```bash
RESULT_DIR=/root/hetero-matrix \
DECODE_METRICS_URL=http://<mi300x-address>:8020/metrics \
  ./run_matrix.sh
```

The sweep covers 1k/8k, 8k/8k, and 8k/1k ISL/OSL at concurrency 1, 2, 4, 8,
16, 32, and 64. Each point uses exact random lengths, greedy generation,
`--ignore-eos`, and one prompt per concurrent request.

Validate the complete result set and write the summary:

```bash
./analyze_matrix.py /root/hetero-matrix > matrix-summary.csv
```

The validator rejects missing points, request failures, short inputs or
outputs, local prefix-cache hits, and missing external-KV tokens. For this
model, the KV geometry is 98,304 bytes per token, so the validated physical
payload is `external_kv_tokens * 98,304`. Mooncake logs independently report
96 MiB per 1,024-token request and 768 MiB per 8,192-token request.

For monolithic comparisons, launch plain vLLM without a KV connector on each
GPU and run `run_baseline_matrix.sh` against each endpoint. Then compare all
three result sets:

```bash
./compare_results.py hetero h200-baseline mi300x-baseline > comparison.csv
```

## Provisioning caveat and cleanup

`provision.sh` and `destroy.sh` apply only when both entitled GPU sizes are
available in one DigitalOcean team. They were not used for the recorded
cross-cloud run. The DigitalOcean H200 must be deleted through the
DigitalOcean API after artifacts are copied. The AMD Developer Cloud MI300X
must be stopped separately in its portal; `destroy.sh` cannot remove it.
