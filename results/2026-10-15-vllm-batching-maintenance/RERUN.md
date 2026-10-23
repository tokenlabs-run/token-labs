# Reproduce the controlled batching experiment

The completed authoritative result is `attempt-06`. It retains the calibration, four-setting exploration and rejected higher-rate confirmation from `attempt-05`. Earlier attempts retain setup failures and restoration checks. The current run uses a custom open-loop aiohttp client, not AIPerf exports. AIPerf itself supports request-rate load; the repository's existing matrix wrapper drives concurrency sweeps. This experiment's client records scheduled arrival, dispatch lag, every streamed token event, response usage and every failure.

Run from the controller with Python 3.12, aiohttp 3.13.5, NumPy 1.26.4 and Matplotlib 3.6.3. The pinned model snapshot must already be cached on spark-02. The runner temporarily stops the Qwen worker; use it only with explicit downtime authorization. Muse, Service selectors and drivers are left unchanged.

Prepare a fresh result directory, capture the current original DGD and copy the saved workload (replace the example directory before running):

```sh
mkdir -p results/new-batching-run
kubectl --context kubernetes-admin@kubernetes -n token-labs get dynamographdeployment qwen36-nvfp4-dynamo-agg-151-epp -o json > results/new-batching-run/original-dgd.json
cp results/2026-10-15-vllm-batching-maintenance/workload.jsonl results/new-batching-run/workload.jsonl
python3 scripts/benchmarks/check_batching_open_loop.py
python3 -u scripts/benchmarks/run_batching_experiment.py --out results/new-batching-run --authorized-downtime > results/new-batching-run/experiment.log 2>&1
python3 scripts/benchmarks/report_batching_experiment.py --root results/new-batching-run
```

To regenerate the workload, run `generate_batching_workload.py` in an environment with the exact cached tokenizer and Transformers. Pass `--tokenizer` the local snapshot directory ending in `1355db6a052410cfd62085d94b58866fd0f2c3c5`, `--seed 20261015`, and `--count 30000`; save stdout as workload.jsonl. The expected SHA256 is `04d1926cd4cead96317d1f623b7a6f5b9277bc680a02e1ac4476dde836e95a92`. Generation aborts unless every unique prompt round-trips to exactly 512 tokens. Do not run tokenizer generation on the serving GPU during measurements.

The runner freezes its own warmed 1,000-request calibration threshold before any tuning. A new experiment has a new calibration; the existing attempt-05 limit must never be changed. Raw request and telemetry files, configuration manifests, startup logs, blocked records and failures must remain available. An interrupted point is not a passing point.

SIGTERM and Python exceptions enter the restoration block; SIGKILL or controller loss cannot run cleanup. If interrupted, inspect restoration.json and cluster state before restarting anything. Recovery restores the saved original DGD replica count after removing the isolated test worker; never apply the test manifest to the production worker.

The short-run best candidate in attempt-05 failed its first 1,000-request confirmation at 0.690356 RPS: P99 2.288324 seconds exceeded the unchanged 2.260152-second limit. A graceful SIGTERM after the completed run restored Qwen and verified health. The lower-rate continuation is recorded in attempt-06, with hard-linked copies of the earlier immutable raw records and byte-identical calibration. Its selected confirmation sequence retains the passing first baseline, then runs candidate, candidate, baseline, baseline, candidate. The failed higher-rate point remains in the final table and plot.

After a source attempt has completed restoration, reproduce the continuation in a fresh directory:

```sh
python3 -u scripts/benchmarks/resume_batching_confirmation.py --source results/2026-10-15-vllm-batching-maintenance/attempt-05 --out results/new-lower-rate-confirmation --candidate-rate 0.625 --authorized-downtime
python3 scripts/benchmarks/report_batching_experiment.py --root results/new-lower-rate-confirmation
```

The continuation requires the original worker restored and the experiment namespace absent. It reuses the original frozen threshold; it does not recalibrate after observing a failure. It resumes the dataset cursor so no prompts are reused, and selects confirmation run names explicitly in conclusion.json.

Publication uses `publish_batching_results.py --root <completed-result-directory> --site <isolated-checkout>/docs` after regenerating the report. The builder checks completion, confirmation sample counts, frozen calibration, workload SHA256 and restoration before writing the existing website page. The site is GitHub Pages from main/docs at https://www.tokenlabs.run/benchmark-results.html. Publication is isolated from unrelated local production commits.

The final restoration worker became ready before frontend model discovery completed: its first generation probe returned HTTP 404, and later read-only inventory/generation probes succeeded without additional service changes. The exported orchestrator now retries generation readiness for up to 120 seconds. The exact original measured orchestrator is preserved in scripts/recorded, and script-provenance.json records both SHA256 values. Measurement controls and the client were unchanged.

Public publication is limited to sanitized aggregate metrics, methodology and plots. Automatic review rejected public export of raw telemetry, internal configuration and workload artifacts. The complete reproduction-evidence.tar.gz remains in the local attempt-06 directory; the publisher defaults to keeping that bundle local.
