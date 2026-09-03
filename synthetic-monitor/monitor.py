"""Public-path OpenAI streaming probe with OpenRouter-aligned metrics."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import time
import httpx
from prometheus_client import Counter, Gauge, start_http_server

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
BASE_URL = os.environ.get("TOKEN_LABS_BASE_URL", "https://api.tokenlabs.run").rstrip("/")
API_KEY = os.environ["TOKEN_LABS_API_KEY"]
MODEL = os.environ["TOKEN_LABS_MODEL"]
INTERVAL = float(os.environ.get("PROBE_INTERVAL_SECONDS", "30"))
TIMEOUT = float(os.environ.get("PROBE_TIMEOUT_SECONDS", "25"))
MAX_TOKENS = int(os.environ.get("PROBE_MAX_TOKENS", "16"))

SUCCESS = Gauge("token_labs_openrouter_probe_success", "Last public-path completion succeeded", ["model"])
TTFT = Gauge("token_labs_openrouter_probe_ttft_seconds", "Time to first content token", ["model"])
LATENCY = Gauge("token_labs_openrouter_probe_latency_seconds", "End-to-end completion latency", ["model"])
THROUGHPUT = Gauge("token_labs_openrouter_probe_output_tokens_per_second", "Output tokens per generation second", ["model"])
LAST_SUCCESS = Gauge("token_labs_openrouter_probe_last_success_timestamp_seconds", "Unix time of last success", ["model"])
REQUESTS = Counter("token_labs_openrouter_probe_requests_total", "Synthetic requests by uptime outcome", ["model", "outcome", "status_code"])


def parse_sse_data(line: str) -> dict | None:
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    return None if not data or data == "[DONE]" else json.loads(data)


async def probe(client: httpx.AsyncClient) -> None:
    started, first_token_at = time.monotonic(), None
    output_chunks, output_tokens, finish_reason = 0, None, None
    status_code, outcome = "network_error", "error"
    try:
        async with client.stream(
            "POST", f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"model": MODEL, "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                  "max_tokens": MAX_TOKENS, "temperature": 0, "stream": True,
                  "stream_options": {"include_usage": True}}, timeout=TIMEOUT,
        ) as response:
            status_code = str(response.status_code)
            response.raise_for_status()
            async for line in response.aiter_lines():
                event = parse_sse_data(line)
                if not event:
                    continue
                choice = (event.get("choices") or [{}])[0]
                if event.get("usage"):
                    output_tokens = event["usage"].get("completion_tokens")
                if (choice.get("delta") or {}).get("content"):
                    first_token_at = first_token_at or time.monotonic()
                    output_chunks += 1
                finish_reason = choice.get("finish_reason") or finish_reason
            if first_token_at is None or finish_reason == "error":
                raise ValueError("invalid completion stream")
            ended = time.monotonic()
            TTFT.labels(MODEL).set(first_token_at - started)
            LATENCY.labels(MODEL).set(ended - started)
            THROUGHPUT.labels(MODEL).set((output_tokens or output_chunks) / max(ended - first_token_at, 0.001))
            LAST_SUCCESS.labels(MODEL).set(time.time())
            SUCCESS.labels(MODEL).set(1)
            outcome = "success"
    except Exception as exc:
        log.warning("probe failed: %s", exc)
        SUCCESS.labels(MODEL).set(0)
    finally:
        REQUESTS.labels(MODEL, outcome, status_code).inc()


async def main() -> None:
    start_http_server(9101)
    async with httpx.AsyncClient(http2=True) as client:
        while True:
            await probe(client)
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
