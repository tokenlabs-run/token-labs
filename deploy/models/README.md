# Active model workloads

Only actively deployable model workloads belong here. Each model/runtime has an
independent directory and controller-runnable entrypoint where appropriate.

- `nemotron-3.5-lightning-30b-a3b-nvfp4/`: aggregate and 1P/1D manifests,
  separated into `llm-d/` and `dynamo/`.
- `qwen3-30b-a3b-instruct-2507-fp8/`: stable control manifests, separated into
  `llm-d/` and `dynamo/`.
- `qwen3.6-35b-a3b-nvfp4-fast/`: TOK-25 DGX Spark vLLM green candidate with
  immutable Unsloth weights and blue/green Services.
- `BENCHMARKING.md`: controller-side deployment and comparison procedure.

Each `llm-d/` and `dynamo/` directory carries its own README with prerequisites,
deploy commands, verification steps and runtime-specific caveats.

Standalone experiments and retired workloads belong under `../archive/models/`.
