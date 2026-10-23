# Unnumbered aggregator migration

The stable model-aggregator Service selects app=model-aggregator-candidate.
Deployment and diagnostic Service are named model-aggregator-candidate.
The repository deployment.yaml uses these names and selectors. The candidate
was rendered with Kustomize; its code and provider catalog data were verified
identical to candidate 3 before staging.

Candidate health, catalog, provider authentication, completion, and streaming
passed. Public catalog, authenticated completion, and streaming returned HTTP 200
after the selector-only switch. Public catalog and completion passed again after
candidate 2 retirement. GPU workloads were not changed.

Candidate 2 had no established inbound connections on port 8000 and no completion
requests logged during the preceding 30 minutes. Its Deployment and diagnostic
Service were deleted at the user's request; its pod is confirmed gone.

Candidate 3 deletion was initially rejected by automatic approval review because
it was within the rollback window. The user subsequently explicitly approved
waiving that window and scaling candidate 3 to zero. The scale-down succeeded
after confirming the stable Service selected only the healthy unnumbered candidate
and candidate 3 had no established inbound connections. Candidate 3 is now 0/0;
its Deployment and diagnostic Service remain available for manual restoration.
Public catalog and authenticated completion checks returned HTTP 200 after scaling.

Kustomize rendering and git diff --check passed. This migration is not committed.
