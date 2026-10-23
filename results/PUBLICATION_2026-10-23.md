# Reports published on 2026-10-23

This collection contains compact reports and measurements selected from pending local work.
Raw logs, per-request records, workload datasets, tokenizer files, and cluster snapshots remain local.
Some reports reference those local artifacts; the references do not mean the raw files were published.

The publication manifest records report hashes and the artifacts excluded from this pass.
Existing tracked evidence from earlier commits remains unchanged.

Regenerate into a separate clean checkout with:

```bash
python3 scripts/common/prepare_results_publication.py \
  --source /path/to/source-checkout \
  --destination /path/to/publication-checkout --apply
```

| Collection | Compact reports |
| --- | ---: |
| 2026-09-21-aggregator-unnumbered | 1 |
| 2026-09-24-mooncake-14487 | 3 |
| 2026-09-24-mooncake-14487-v150 | 4 |
| 2026-10-01-hardware-observability | 5 |
| 2026-10-01-muse-gateway-proposal | 1 |
| 2026-10-07-dynamo-1.5.1 | 1 |
| 2026-10-15-vllm-batching | 2 |
| 2026-10-15-vllm-batching-maintenance | 99 |
| 2026-10-17-qwen38-27b-fp8-eks | 55 |
| 2026-10-22-flint-provider | 6 |
| 2026-10-22-qwen36-frontend-rollback | 1 |
| 2026-10-22-qwen36-pod-cleanup | 1 |
| 2026-10-22-qwen36-same-gpu-maintenance | 2 |
