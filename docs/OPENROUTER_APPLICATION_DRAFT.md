# OpenRouter provider application draft

Status: **not ready to submit**. This document is a fill-ready application and
launch-readiness checklist. Bracketed values require an authorized owner; they
must not be guessed. Submission is an external action and is not authorized by
this document.

## Application fields

| Form field | Draft value | Status / evidence |
|---|---|---|
| Company Name | `[LEGAL COMPANY NAME]` | Required. Confirm the registered entity; do not substitute the brand name without approval. |
| Website | `https://www.tokenlabs.run` | Ready. |
| Your Email | `[NAME@TOKENLABS.RUN]` | Required. The snapshot asks for a company email and says it will be invited to Slack Connect. |
| Display Name | `Token Labs` | Proposed; owner approval required. |
| Desired Slug | `token-labs` | Proposed; lowercase/hyphen-valid and subject to OpenRouter availability. |
| Distinguishing Features | Select `High Throughput` only after the final public-path gate passes. Consider `Unique Infrastructure` only if OpenRouter agrees that dedicated DGX Spark capacity qualifies. | The rendered choices are Low Latency, High Throughput, Unique Models, Low Pricing, Unique Infrastructure, Decentralized, and Strategic Partnership. Do not select unproven claims. |
| Extra Details | See “Application narrative” below. | Draft. |
| URL to Models | `https://api.tokenlabs.run/openrouter/models` | Implemented in Git; verify it is deployed and returns HTTP 200 with the validated schema-2.4 document before submission. Do **not** enter `/v1/models`: it is OpenAI-format. |
| Privacy Policy URL | `https://www.tokenlabs.run/privacy.html` | Draft is published in the repository; verify the public URL and obtain owner/legal approval before submission. |
| Terms of Service URL | `https://www.tokenlabs.run/terms.html` | Draft is published in the repository; verify the public URL and obtain owner/legal approval before submission. |
| Data Policy | `Token Labs does not use prompts or completions for training. Inference content is processed transiently and is not intentionally retained after request completion. Operational metadata—model, token counts, timing, status, and security signals—may be retained up to 30 days, with limited extensions for security, billing disputes, or legal obligations. Details: https://www.tokenlabs.run/data-policy.html` | Draft published; owner must approve and confirm the stated controls before submission. |
| Supported Output Modalities | Select `Text` only. | The rendered choices also include Image, Audio, Video, Embeddings, Rerank, and TTS; the selected model does not provide them. |
| Inference Location | `[COUNTRY/REGION WHERE THE DGX SPARK RUNS]` | Required; infrastructure owner must confirm. |
| HQ Location | `[COMPANY HQ COUNTRY/REGION]` | Required; company owner must confirm. |
| API Base URL | `https://api.tokenlabs.run/openrouter/v1` | Implemented provider-specific path with bounded admission; verify production authentication, streaming, and overload behavior. |
| Icon URI | `[PUBLIC SQUARE LOGO URL]` | Optional; recommended. |
| Status Page URL | `[PUBLIC STATUS PAGE URL]` | Optional; recommended. Grafana is not a substitute unless intentionally made public and customer-safe. |
| SOC 2 compliant | `No` | Conservative default until documentary evidence exists. |
| HIPAA compliant | `No` | Conservative default; the model document must not advertise HIPAA. |
| ISO 27001 compliant | `No` | Conservative default until documentary evidence exists. |

The identity fields and the later required fields/choices were verified from the
supplied rendered form snapshots. Two earlier supplied files were 6-by-2-pixel
placeholders and contained no readable form fields. Recheck the live form
immediately before submission.

## Application narrative

Token Labs proposes to provide `qwen/qwen3-30b-a3b-instruct-2507` from dedicated
NVIDIA DGX Spark capacity. The served checkpoint is
`Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`, licensed under Apache-2.0. The initial
deployment uses one aggregated vLLM worker behind an authenticated Envoy gateway.
Admission is deliberately bounded: traffic above the validated concurrency is
rejected promptly with HTTP 429 instead of being held in a long provider queue.
We will publish only capacity, pricing, context length, features, and readiness
that have passed reproducible public-endpoint tests. The launch candidate is
tested across interactive, tool-use, balanced, long-prefill, long-decode, and
long-mixed workloads, including streaming correctness and failure behavior.

## Conditions that must be closed before submission

- Produce a schema-2.4 provider model document at the proposed Models API URL.
  It must include real pricing, modality-specific capacity, context length,
  architecture, quantization, supported parameters, inference location, and a
  truthful `is_ready` value.
- Keep the normal OpenAI-compatible `GET /v1/models` endpoint as well. It must
  list the exact canonical served name
  `qwen/qwen3-30b-a3b-instruct-2507` while the backend is healthy.
- Demonstrate from the public URL that the implemented concurrency admission
  guard returns an early 429 above the benchmarked limit. Existing RPM/token
  quota 429s are separate and do not prove load-aware admission.
- Validate non-streaming and SSE streaming, terminal `[DONE]`, usage reporting,
  error status codes, tools, and structured output from the public URL.
- Complete the public-path concurrency matrix and choose the largest concurrency
  that passes latency, correctness, memory, and stability gates. Do not advertise
  unmeasured capacity.
- Arrange OpenRouter auto top-up or invoicing and approve input/output pricing.
- Publish the privacy policy and approved data policy; confirm HQ and inference
  locations and a company-domain contact email.
- Run at least 100 production-like requests before treating measured uptime as
  representative; target at least 95% OpenRouter-defined uptime and materially
  higher internal launch SLOs.

## Current technical audit

| Requirement | Current state | Required action |
|---|---|---|
| OpenAI `GET /v1/models` | Implemented dynamically, but currently returns an empty list while serving stacks are scaled down. | Restore only when the infrastructure owner intends it; serve the canonical model name and retest. |
| OpenRouter provider models document | Route and fail-closed loader are implemented; readiness is reduced to false unless the exact backend is live. | Mount the owner-approved, schema-validated document and verify the public response. |
| Early 429 | Provider-specific concurrency admission is implemented in addition to Kuadrant RPM/token quotas. | Set its limit from the completed public benchmark and prove response timing under overload. |
| No long provider queue | Admission is bounded before forwarding; accepted requests may still queue inside vLLM up to its configured sequence capacity. | Align the admission limit with vLLM `max-num-seqs` and verify queue time at saturation. |
| Streaming/API correctness | Test tooling exists. | Run it against the final public deployment and retain the sanitized report. |
| Pricing/capacity truthfulness | Generator fails closed when values are absent. | Owner approves pricing; benchmark supplies capacity. Validate against the official schema. |
| Model redistribution/hosting rights | Apache-2.0 selected checkpoint. | Retain license notice/attribution and recheck the exact immutable artifact revision before launch. |
| Provider billing | Not evidenced in repository. | Arrange auto top-up or invoicing with OpenRouter. |

## Submission rule

Submit only after every required field above is non-bracketed and every technical
condition has evidence. The form should not be submitted automatically: an
authorized company representative must approve the legal, privacy, commercial,
location, and contact information.
