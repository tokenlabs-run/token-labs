# Mooncake advertised-host validation, 2026-09-24

Result: blocked before the cross-node request path. Both Qwen3.6 cases failed during Mooncake GDN_ATTN cache initialization. See pr-comment.md for the ready-to-post evidence comment and summary.json for machine-readable outcomes.

The production DGD was deleted at the operator's explicit request. It had no ready frontend endpoints before deletion. Its original manifests and service selectors are in production-dgd.json, rollback.json, and services-before.json. The controller had DiskPressure; an exact rollback may remain scheduling-blocked there. No gateway or aggregator changes were made.

The isolated test DGD is retained with all components at zero replicas. No successful inference deployment was promoted. The CPU probe was removed. Apply unset.yaml or pod-ip.yaml only when intentionally repeating the test with available GPU capacity. protocol-configmap.json contains the exact source overlay required by either case.

render.py records how the test manifests were derived from the requested Qwen3.6 manifest. monitor.py captured logs; request.py is the HTTP probe. real-helper-tests.log used the current branch test file with its module loaded from /tmp into the runtime probe, so it tested the real installed vLLM helper without modifying the image. The failed model-parallel expectations are retained, not hidden or skipped.
