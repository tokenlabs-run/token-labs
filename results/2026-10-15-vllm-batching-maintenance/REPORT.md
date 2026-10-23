# Controlled vLLM batching experiment

The completed study is in [attempt-06/REPORT.md](attempt-06/REPORT.md). Its raw records also include the earlier calibration, four-setting search, passing first baseline and failed higher-rate candidate from attempt-05.

Increasing max_num_seqs from 1 to 4 increased confirmed output throughput from 71.184 to 79.986 tokens/second, or 12.4%. Three 1,000-request confirmations per configuration all passed the unchanged experimental P99 limit of 2.260152 seconds, with no errors or timeouts and no sustained backlog growth. Baseline P99 ranged from 1.8757 to 1.9333 seconds; candidate P99 ranged from 2.1028 to 2.1437 seconds. This is a tested sustainable lower bound for the fixed 512-input/128-output synthetic workload and 4,096-token test context.

The higher-rate candidate reached 88.335 tokens/second but failed P99 at 2.288324 seconds; its 1,000 requests remain in the data. All failures, including five safety cancellations in an exploratory backlog stop and earlier setup failures, are retained. Caps 2 and 8 have exploratory results only.

The original Qwen specification and Service selectors match their saved originals. Qwen and Muse generation and gateway inventory returned HTTP 200, all nodes are Ready, and the test namespace was removed. An unauthenticated public inventory probe returned HTTP 401. The first Qwen readiness probe returned HTTP 404 before a subsequent read-only retry passed; the event and the bounded readiness-retry fix are documented in the full report.

- [Full local report](attempt-06/REPORT.md)
- [All run metrics](attempt-06/comparison.csv)
- [Raw requests, telemetry, saved workload and rerunnable scripts](attempt-06/reproduction-evidence.tar.gz)
- [Saved 30,000-prompt workload](workload.jsonl)
- [Throughput versus P99 plot](attempt-06/throughput-versus-p99.png)
- [Independent restoration health checks](attempt-06/post-restoration-health.json)
- [Rerun instructions](RERUN.md)

Published and live-verified results: https://www.tokenlabs.run/benchmark-results.html#vllm-batching-2026-10-15 . The public export contains sanitized aggregate metrics, methodology and plots. Automatic approval review rejected exporting the raw bundle containing internal telemetry, deployment configuration and workload artifacts; it remains available locally above. Publication was isolated from five unrelated unpublished local commits.
