# Old graph frontend switch assessment

No traffic was switched and no workload template or replica count was changed. The stable frontend Service remains on release-151. The requested old graph frontend passed nine API probes but failed all six namespace-tool probes with HTTP400, reporting ambiguous tool names after namespace flattening. The current frontend passed all fifteen identical probes. The rollback therefore fails the API compatibility gate in deploy/models/MODEL_ROLLOUT_RUNBOOK.md.

Do not delete qwen36-nvfp4-dynamo-agg-151-epp: its Epp and VllmWorker components both request one replica, and the VllmWorker is the active GPU process. A direct graph frontend does not need an EPP for inference scheduling, but generic public chat/completion routes currently reference the EPP InferencePool. Retiring EPP requires separately changing the component and routing after validation while preserving the active worker.

Snapshots and per-probe responses are retained beside this report.
