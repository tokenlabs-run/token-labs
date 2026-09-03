# Token Labs operating rules

## Production inference: zero-downtime invariant

Production availability takes precedence over deployment convenience.

- Never apply a pod-template change to the Deployment currently selected by a
  production Service.
- Never restart, scale down, delete, or repurpose the active production model
  until a separate candidate is ready, warmed, tested, and directly probeable.
- Every production model change must use distinct blue and green Deployments
  on separate available capacity, plus diagnostic Services for both slots.
- Keep the stable public Service on the existing slot while the candidate
  loads and passes readiness, API conformance, quality, overload, capacity,
  and latency gates.
- Cut over atomically by changing only the stable Service's slot selector.
- Keep the previous slot ready and directly probeable through the observation
  and rollback window. Do not terminate it to accelerate connection draining.
- Before any mutation, record the active Service selector and prove the
  replacement has ready endpoints. After cutover, verify the public API before
  touching the old slot.
- If independent spare capacity is unavailable, stop. Do not perform an
  in-place rollout and do not accept downtime implicitly. Escalate the capacity
  blocker to the user.
- A manifest using `strategy: Recreate` is never a production rollout plan for
  the active slot.

Follow `deploy/models/MODEL_ROLLOUT_RUNBOOK.md` for every production model
promotion and rollback.
