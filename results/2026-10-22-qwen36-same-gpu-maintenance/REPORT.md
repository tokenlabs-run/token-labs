# Qwen3.6 same-GPU maintenance

The user explicitly approved using the same GPU and service disruption. EPP was removed permanently. The existing EPP-free graph `qwen36-nvfp4-dynamo-agg` now reports Ready=True. Its worker runs on spark-02 with both containers ready and zero restarts. The public stable Service continues selecting the old blue Dynamo frontend. Flint was not changed.

The main worker explicitly sets `DYN_HEALTH_CHECK_ENABLED=false`, disabling the generation-payload canary that previously caused false liveness failures under queue load. The engine monitor remains enabled. The pinned worker image, model revision, parser flags, context length, sequence limit and all worker arguments match the previous serving worker.

Final public chat, streaming and forced tool-call checks passed. Eight simultaneous requests each completed 512 output tokens. 21 health observations returned HTTP200 for both /live and /health; observed peak running=4, waiting=4. This is a bounded validation, not a repeat of the full AgentX run, a capacity benchmark, or an injected engine-failure test.

There were two model reloads. The initial worker passed the small checks, but restoring the embedded frontend caused Grove to recreate the worker despite its unchanged template. A stale in-progress PodCliqueSet was recreated to converge to the desired graph. The pinned old frontend image then failed on Spark ARM with exec-format error, so that duplicate frontend remains scaled to zero. The existing old blue frontend remains on the x86 controller. An initial explanation that frontend zero replicas would permanently keep the DGD not ready proved incorrect; the final graph converged to Ready=True. No further worker template changes were made.

Known existing limitations remain: the old frontend's namespace-tool compatibility cases failed in prior assessment, controller disk pressure causes Pod churn, and generic `/v1/chat/completions` returned HTTP200. Model-specific `/models/qwen/v1/chat/completions` passed all final checks.

Reproducible graph: `deploy/upgrades/dynamo-1.5.1/inputs/qwen-epp-free-graph.yaml`, rendered by `generate.py`. The generator no longer creates the Qwen EPP graph. The diagnostic Service selects the blue frontend. Rollback manifests and instructions are retained here. No credentials were copied into these files.
