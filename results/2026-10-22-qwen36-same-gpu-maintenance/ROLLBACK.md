# Same-GPU rollback

The user approved service disruption for this maintenance. Rollback also requires a model reload on the same GPU.

1. Scale only `VllmWorker` in `qwen36-nvfp4-dynamo-agg` to zero. Wait for its Pod to terminate and release spark-02's GPU.
2. Restore `qwen36-nvfp4-dynamo-agg-151-epp-rollback.yaml`. Its pinned original worker has one replica and the original inference canary behavior. This recreates EPP if it has been deleted.
3. Wait for the original worker to be ready and verify public chat, stream and tools through the blue frontend. The public Service selector has not changed during maintenance.
4. Restore the original old-graph configuration from `qwen36-nvfp4-dynamo-agg-rollback.yaml` only after checking that its VllmWorker replicas remain zero. Its original Frontend replica runs on the controller and may encounter the pre-existing disk-pressure problem.

Do not scale both workers to one on the same GPU. Do not touch Flint on spark-01. The old frontend's namespace-tool regression and generic public chat HTTP500 existed before maintenance and are not repaired by this rollback.
