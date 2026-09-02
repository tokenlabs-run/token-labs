---
name: model-serving-benchmarks
description: Design, run, validate, and publish repeatable model-serving performance matrices with NVIDIA AIPerf for a specified model, endpoint topology, and hardware. Use for ISL/OSL and concurrency sweeps or throughput Pareto curves; distinguish single-worker baselines from distributed-framework experiments.
---

# Model serving benchmarks

Use the repository scripts in `scripts/benchmarks/` to make experiment inputs,
commands, validation, and outputs reproducible.

Before running load, identify the claim the topology can support. Record whether
requests actually traverse each framework scheduler, how many workers are
available to it, whether prefill and decode are disaggregated, and where each
worker is placed. Label a one-worker path as a single-worker baseline. Do not
attribute differences to distributed scheduling when a scheduler is bypassed or
has only one worker.

Copy `scripts/benchmarks/example-config.json` into the result directory and fill
in the served model names, URLs, tokenizer, hardware, topology, workloads, and
concurrencies. Use a new output directory when any controlled input changes.
Keep the saved `benchmark-config.json` with the raw artifacts.

Run each backend separately when this avoids client interference:

```bash
python3 scripts/benchmarks/run_aiperf_matrix.py \
  --config results/<experiment>/config.json \
  --out results/<experiment>/raw \
  --backend <backend-name>
```

The runner resumes only exports that pass exact request-count and server-reported
ISL/OSL checks. It records the exact command for every point. A partial or failed
run must remain distinguishable from a valid canonical export; preserve failure
artifacts with a descriptive suffix before rerunning.

Validate and aggregate only from raw exports:

```bash
python3 scripts/benchmarks/aggregate_aiperf_matrix.py \
  --config results/<experiment>/config.json \
  --root results/<experiment>/raw \
  --output results/<experiment>/pareto.json
```

Use `--allow-partial` only for progress inspection. Publish a Pareto curve only
when `complete` is true, the expected and measured point counts match, every
point has zero request errors, and the deployment provenance supports the stated
comparison. Pareto axes are aggregate output tokens/s and output tokens/s/user,
calculated independently for each ISL/OSL workload.

Read [references/experiment-design.md](references/experiment-design.md) when
choosing topology, controls, sample sizes, or publication language.
