# Controlled vLLM batching results

Increasing max_num_seqs from 1 to 4 changed confirmed output throughput from 71.184 to 79.986 tokens/second, a 12.4% increase. All six selected confirmations passed; each configuration completed 3,000 requests.

The experimental P99 limit was frozen at 2.260152 seconds, 1.2 times the 1,000-request light-load baseline P99 of 1.883460 seconds. It is not a customer-derived SLO.

Each request had 512 verified input and exactly 128 generated tokens. A custom aiohttp client generated open-loop arrivals independently of request completion. It had no client concurrency cap. Warmup preceded measurements. Prefix caching and speculative decoding were off; context 4,096, batched-token budget 2,048 and KV memory budget 2 GiB were fixed. The standalone single-worker path bypassed framework routing. The model revision, precision, image digest, vLLM version and hardware are disclosed in summary.json. These findings apply to this synthetic workload and test configuration.

The first candidate confirmation at 0.690356 RPS reached 88.335 tokens/second but failed with P99 2.288324 seconds. It remains in the aggregate exports and plot. The final candidate confirmations used 0.625 RPS without changing the limit. Caps 2 and 8 have short exploratory results only and were not confirmed. Four and eight were essentially tied in exploration; this study does not establish an optimal cap.

Single-sequence waiting requests and TTFT increased at failing loads, showing admission queueing. Kernel timings and memory-bandwidth profiling were unavailable; neither physical bottleneck is established. Missing telemetry fields remain unavailable rather than zero.

Every run is in comparison.csv and summary.json, including latency failures and five safety cancellations during a backlog stop. No selected confirmation had errors or timeouts. Output throughput includes drain. End-to-end latency includes dispatch delay; percentiles were recomputed from individual client records. Client-observed ITL uses token arrival gaps; coalesced tokens share an event timestamp, and a separate P99 of per-request mean ITL is disclosed.

The original configuration and routing were restored, and model generation and service health were verified. An initial readiness probe returned HTTP 404 and passed on a subsequent read-only retry; the rerun orchestrator now waits for generation readiness.

Public artifacts contain sanitized aggregate results, methodology and the plot. Full raw client records, telemetry, workload, configurations and rerunnable scripts remain in the local experiment directory.
