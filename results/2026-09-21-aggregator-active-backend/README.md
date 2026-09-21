# Aggregator active backend selection

Source of warnings: model-aggregator-candidate-2 background discovery every 28 seconds.
Six discovered Services had no ready endpoints. Both GPUs remain allocated to the
healthy Qwen3 Dynamo disaggregated backend.

Added MODEL_BACKEND_SERVICES allowlist, configured to
qwen3-30b-control-dynamo-disagg-frontend. Empty/unset preserves automatic discovery.

Validation: all 14 unit tests passed. Candidate health, live catalog, provider
catalog, completion, streaming with DONE, rejection of unauthenticated provider
requests, and authenticated provider catalog passed. After the selector-only
cutover, public catalog, authenticated provider completion, and authenticated
streaming all returned HTTP 200. Candidate logs show no unavailable-endpoint or
service-discovery errors across multiple refresh intervals.

Stable model-aggregator Service now selects app=model-aggregator-candidate-3.
Previous candidate-2 remains ready and directly probeable for rollback. Its old
background discovery continues to emit warnings during retention. No inference
workload or model Service selector was modified.

Rollback, after verifying candidate-2 ready endpoints:

```sh
kubectl -n token-labs patch service model-aggregator --type=json -p='[{"op":"test","path":"/spec/selector/app","value":"model-aggregator-candidate-3"},{"op":"replace","path":"/spec/selector/app","value":"model-aggregator-candidate-2"}]'
```

The candidate manifest preserves the live provider catalog ConfigMap and credential
references. It does not deploy unrelated local working-tree changes. Retain the old
aggregator for the rollback window; its retirement is a separate operation.
