# Resume this stopped EKS model

The benchmark shutdown intentionally suspends Flux Kustomization qwen38-27b and sets both DynamoGraphDeployment components to zero replicas. It deletes only the experiment GPU NodeClaim. The model API remains unavailable until the model is resumed. The portal and CPU nodes remain running. No automatic request-triggered wake-up is configured.

Before resuming, review the current Git revision and ensure the intended pinned model configuration remains the one Flux will apply. The shutdown tool saves the original graph, Service selector, NodeClaim, and Flux state in shutdown-before.json.

If Git still specifies one replica for each component, resume reconciliation:

```bash
flux resume kustomization qwen38-27b --context=inference-prod-us-east-1
flux reconcile kustomization qwen38-27b --context=inference-prod-us-east-1
```

The pending GPU workload should cause Karpenter to provision another g6.12xlarge. Confirm the current NodePool limits and AWS capacity before resuming. The old node-local model cache disappears when its EC2 instance terminates, so the next start must download weights again. Wait for model loading, readiness, and a direct chat smoke test before treating the public model endpoint as available.

Envoy's 6000 total tokens/minute quota was bypassed by the direct benchmark and was never disabled. There is no quota restoration step.
