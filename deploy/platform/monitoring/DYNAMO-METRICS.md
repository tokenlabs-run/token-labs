# Dynamo monitoring

`podmonitor-dynamo.yaml` selects metrics-enabled Dynamo frontend and worker pods
in `token-labs`. Its `release: kube-prometheus-stack` label is required by the
Prometheus instance. Named ports select frontend HTTP metrics on 8000 and worker
system metrics on 9090. The comparison monitor excludes Dynamo to avoid duplicate
scrapes. Do not restore the retired hardcoded worker-IP scrape jobs.

The Inference Metrics dashboard reports KV transfer **prompt tokens**, using
`vllm:prompt_tokens_by_source_total{source="external_kv_transfer"}`. This is not a
count of transfer operations or bytes. The total resets when the worker restarts;
the rate panel uses the dashboard rate interval. Ordinary prefill should report
local-compute tokens and decode should report externally transferred tokens.

Latency quantiles and request error ratios can be undefined while idle. Scrape
availability proves only that metrics endpoints respond, not model readiness or
public API availability. The 30-day scrape budget uses available history; a newly
scraped workload does not yet have 30 days of evidence. Unsupported DCGM metrics
are explained in text panels instead of shown as zero.

Validate a rollout with Prometheus `up{job="monitoring/token-labs-dynamo"}`,
check the transfer counter before and after a successful inference request, and
verify that serving pod UIDs, restart counts, and frontend service selectors stay
unchanged. Apply monitoring resources without restarting inference workers.

## Validation — 2026-09-29

- Server-side dry-run and Kustomize rendering passed.
- Frontend, prefill, and decode scrape targets all reported `up=1`.
- All 44 queries across the inference, GPU, and SLO dashboards returned finite
  samples after a test request (28 + 7 + 9); no query errors or empty results.
- Completion `cmpl-19538936-79ca-48cc-92ed-0c148655d77e` returned HTTP 200
  with 23 prompt tokens and 32 completion tokens. Decode externally transferred
  prompt tokens increased from 484 to 507; the five-minute rate was positive.
- Serving pod UIDs, restart counts, readiness, and the frontend Service selector
  were unchanged. No inference rollout was performed.
