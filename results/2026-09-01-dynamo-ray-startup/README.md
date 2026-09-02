# Ray worker startup validation

Source: spark-01:/home/nvidia/src/github.com/elizabetht/dynamo-ray-worker-startup, branch codex/ray-worker-startup.

- Complete internal/dynamo Go package tests passed, including race detection.
- Behavioral regressions fail on origin/main and pass with the fix.
- Three real Ray 2.55.1 workers started before the head; all logged waiting.
- After starting the head, all four Ray nodes joined with zero pod restarts.
- A task pinned to each Ray node completed successfully across spark-01 and spark-02.
- Validation used isolated CPU-only pods and the exact generated worker command. No model inference or operator rollout was performed.
- Python image pinned by digest in manifests; an initial run with differing cached Python patch versions was discarded.

Reproduction: apply workers.json, confirm all three workers log waiting, apply head.json, then run validate_ray.py inside the head pod. Delete the validation namespace afterward.

PR: https://github.com/elizabetht/dynamo/pull/5
Commit: a742dbe4c

Fork CI limitations: title-labeling action reports Resource not accessible by integration; CI approval workflow has no GH_TOKEN. These are workflow permissions/credentials failures, not local test failures.
Copyright CI also cannot pull the fork helm-tester:0.1.1 image (manifest unknown). Other checks were still running when the PR was delivered.
