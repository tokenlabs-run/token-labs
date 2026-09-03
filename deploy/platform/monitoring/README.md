# Token Labs production monitoring

This package provisions Prometheus scrape targets, SLO/OpenRouter alerts,
Grafana dashboards, Slack/PagerDuty routing, and the incident harness. It does
not mutate or restart the active production model.

## Activate

1. Build and publish `synthetic-monitor/Dockerfile`, then pin its image digest
   in `openrouter-synthetic-monitor.yaml`.
2. Create a dedicated low-quota monitoring API key. Copy
   `openrouter-synthetic-monitor-secret.example.yaml`, replace both values, and
   apply the populated Secret out-of-band. Never commit it.
3. Create a Slack incoming webhook in the **Token Labs.run** workspace for the
   desired alert channel and a PagerDuty Events API v2 integration. Put both
   values in a copy of `incident-harness/secret-template.yaml` and apply it.
4. Apply `kubectl apply -k deploy/platform/monitoring`, then confirm both Token
   Labs dashboards appear in Grafana.
5. Test notifications with a temporary test rule. Never stop the active model
   to test monitoring; the production zero-downtime invariant still applies.

Critical public-path alerts fire after 1–2 minutes and route to PagerDuty. All
alerts go through the incident harness to Slack. OpenRouter counts 401/402/404,
5xx, mid-stream failures, and error finish reasons against uptime; it excludes
400/403/413/429. This package tracks 429 separately as capacity pressure and
also watches TTFT and streaming token throughput.
