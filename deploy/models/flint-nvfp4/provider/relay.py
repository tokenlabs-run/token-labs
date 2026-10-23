"""Bridge portal-authenticated Flint requests to the DGX provider endpoint."""
import os
import json
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODEL = "RecursiveSI/flint"
ORIGIN = os.environ["FLINT_PROVIDER_BASE"].rstrip("/")
AUTH = {"Authorization": "Bearer " + os.environ["FLINT_PROVIDER_KEY"]}


@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(600, connect=10),
        follow_redirects=False,
    ) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz")
async def health(request: Request):
    try:
        response = await request.app.state.client.get(
            ORIGIN + "/models", headers=AUTH, timeout=10)
        healthy = response.status_code == 200 and any(
            item.get("id") == MODEL for item in response.json().get("data", []))
    except (httpx.HTTPError, ValueError, TypeError):
        healthy = False
    return JSONResponse({"ready": healthy}, status_code=200 if healthy else 503)


@app.get("/livez")
async def live():
    return {"alive": True}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    if not isinstance(payload, dict) or payload.get("model") != MODEL:
        return JSONResponse({"error": "Unknown model"}, status_code=404)
    upstream = None
    stream_owned = False
    try:
        upstream = await request.app.state.client.send(
            request.app.state.client.build_request(
                "POST", ORIGIN + "/chat/completions", json=payload,
                headers={**AUTH, "x-request-id": request.headers.get("x-request-id", "")}),
            stream=True)
        headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        if "retry-after" in upstream.headers:
            headers["Retry-After"] = upstream.headers["retry-after"]
        if payload.get("stream"):
            async def stream():
                try:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
                finally:
                    await upstream.aclose()
            stream_owned = True
            return StreamingResponse(stream(), status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type", "text/event-stream"),
                headers=headers)
        return JSONResponse(json.loads(await upstream.aread()),
            status_code=upstream.status_code, headers=headers)
    except (httpx.HTTPError, ValueError):
        return JSONResponse({"error": "Flint upstream unavailable"}, status_code=502)
    finally:
        if upstream is not None and not stream_owned:
            await upstream.aclose()
