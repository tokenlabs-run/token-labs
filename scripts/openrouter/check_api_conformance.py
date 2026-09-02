#!/usr/bin/env python3
"""Check an OpenAI-compatible Tokenlabs endpoint for OpenRouter readiness.

The bearer token is read from an environment variable and is never persisted.
The JSON report contains pass/fail evidence and sanitized response summaries,
not prompts, generated content, credentials, or full response bodies.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time
from typing import Any, Callable

import requests


class CheckFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int,
    expected: tuple[int, ...] = (200,),
    **kwargs: Any,
) -> tuple[requests.Response, Any]:
    started = time.perf_counter()
    response = session.request(method, url, timeout=timeout, **kwargs)
    elapsed_ms = (time.perf_counter() - started) * 1000
    require(
        response.status_code in expected,
        f"{method} {url}: HTTP {response.status_code}, expected {expected}",
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise CheckFailure(f"{method} {url}: response is not JSON") from exc
    return response, {"body": body, "elapsed_ms": elapsed_ms}


def validate_usage(usage: Any) -> dict[str, int]:
    require(isinstance(usage, dict), "missing usage object")
    result = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        require(isinstance(value, int) and value >= 0, f"invalid usage.{key}")
        result[key] = value
    require(
        result["total_tokens"]
        == result["prompt_tokens"] + result["completion_tokens"],
        "usage.total_tokens is inconsistent",
    )
    return result


def validate_chat_response(body: Any, model: str) -> dict[str, Any]:
    require(isinstance(body, dict), "chat response is not an object")
    require(isinstance(body.get("id"), str) and body["id"], "missing response id")
    require(body.get("object") == "chat.completion", "incorrect response object")
    require(isinstance(body.get("created"), int), "missing integer created timestamp")
    require(isinstance(body.get("model"), str), "missing response model")
    choices = body.get("choices")
    require(isinstance(choices, list) and len(choices) == 1, "expected one choice")
    choice = choices[0]
    require(isinstance(choice, dict), "choice is not an object")
    require(choice.get("index") == 0, "choice index must be zero")
    require(
        choice.get("finish_reason") in {"stop", "length", "tool_calls"},
        "invalid or missing finish_reason",
    )
    message = choice.get("message")
    require(isinstance(message, dict), "missing assistant message")
    require(message.get("role") == "assistant", "incorrect response role")
    usage = validate_usage(body.get("usage"))
    return {
        "returned_model": body["model"],
        "requested_model": model,
        "finish_reason": choice["finish_reason"],
        "usage": usage,
    }


def check_models(ctx: dict[str, Any]) -> dict[str, Any]:
    _, result = request_json(
        ctx["session"], "GET", f"{ctx['url']}/v1/models", timeout=ctx["timeout"]
    )
    body = result["body"]
    require(isinstance(body, dict) and isinstance(body.get("data"), list), "bad model list")
    ids = [item.get("id") for item in body["data"] if isinstance(item, dict)]
    require(ctx["model"] in ids, f"model not present in /v1/models: {ctx['model']}")
    return {"elapsed_ms": result["elapsed_ms"], "model_count": len(ids)}


def check_provider_catalog(ctx: dict[str, Any]) -> dict[str, Any]:
    _, result = request_json(
        ctx["session"], "GET", ctx["provider_models_url"], timeout=ctx["timeout"]
    )
    body = result["body"]
    require(isinstance(body, dict) and isinstance(body.get("data"), list),
            "provider catalog must contain a data array")
    matches = [item for item in body["data"]
               if isinstance(item, dict) and item.get("id") == ctx["model"]]
    require(len(matches) == 1, "provider catalog must contain the exact model once")
    document = matches[0]
    require(document.get("schema_version") == "2.4", "provider schema must be 2.4")
    require(document.get("is_ready") is True, "provider model is not ready")
    require(isinstance(document.get("name"), str) and document["name"], "missing name")
    require(isinstance(document.get("created"), int), "missing created timestamp")
    require(isinstance(document.get("hugging_face_id"), str), "missing Hugging Face ID")
    require(document.get("openrouter", {}).get("slug") == ctx["model"],
            "OpenRouter slug differs from model ID")
    inputs = document.get("input_modalities")
    outputs = document.get("output_modalities")
    require(isinstance(inputs, list) and inputs, "missing input modalities")
    require(isinstance(outputs, list) and outputs, "missing output modalities")
    text_inputs = [item for item in inputs if item.get("type") == "text"]
    text_outputs = [item for item in outputs if item.get("type") == "text"]
    require(len(text_inputs) == 1 and len(text_outputs) == 1,
            "expected exactly one text input and output modality")
    for label, modality in (("input", text_inputs[0]), ("output", text_outputs[0])):
        require(isinstance(modality.get("pricing"), list) and modality["pricing"],
                f"missing {label} pricing")
        require(isinstance(modality.get("capacity"), list) and modality["capacity"],
                f"missing {label} capacity")
    require(text_outputs[0].get("streaming") is True, "text streaming not declared")
    root_capacity = document.get("capacity")
    require(isinstance(root_capacity, list), "missing request capacity")
    require(any(item.get("type") == "concurrency" for item in root_capacity),
            "missing concurrency capacity")
    require(any(item.get("type") == "request" for item in root_capacity),
            "missing request-per-minute capacity")
    require(isinstance(document.get("datacenters"), list) and document["datacenters"],
            "missing datacenter declaration")
    require(isinstance(document.get("deployment_region"), str)
            and document["deployment_region"], "missing deployment region")
    require(isinstance(document.get("compliance"), dict), "missing compliance declaration")
    return {
        "elapsed_ms": result["elapsed_ms"],
        "schema_version": document["schema_version"],
        "is_ready": document["is_ready"],
        "input_modalities": [item.get("type") for item in inputs],
        "output_modalities": [item.get("type") for item in outputs],
    }


def check_auth_required(ctx: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(f"{ctx['url']}/v1/models", timeout=ctx["timeout"])
    require(response.status_code in (401, 403), f"unauthenticated request returned {response.status_code}")
    return {"status_code": response.status_code}


def check_nonstream(ctx: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": ctx["model"],
        "messages": [{"role": "user", "content": "Reply with the word ready."}],
        "temperature": 0,
        "max_tokens": 16,
        "stream": False,
    }
    _, result = request_json(
        ctx["session"],
        "POST",
        f"{ctx['url']}/v1/chat/completions",
        timeout=ctx["timeout"],
        json=payload,
    )
    summary = validate_chat_response(result["body"], ctx["model"])
    summary["elapsed_ms"] = result["elapsed_ms"]
    return summary


def check_stream(ctx: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": ctx["model"],
        "messages": [{"role": "user", "content": "Reply with the word ready."}],
        "temperature": 0,
        "max_tokens": 16,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    started = time.perf_counter()
    response = ctx["session"].post(
        f"{ctx['url']}/v1/chat/completions",
        json=payload,
        timeout=ctx["timeout"],
        stream=True,
    )
    require(response.status_code == 200, f"stream returned HTTP {response.status_code}")
    require("text/event-stream" in response.headers.get("content-type", ""), "not SSE")
    chunks = 0
    done = False
    usage = None
    first_data_ms = None
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line or raw_line.startswith(":"):
            continue
        require(raw_line.startswith("data:"), "non-SSE line in stream")
        if first_data_ms is None:
            first_data_ms = (time.perf_counter() - started) * 1000
        data = raw_line[5:].strip()
        if data == "[DONE]":
            done = True
            break
        try:
            event = json.loads(data)
        except ValueError as exc:
            raise CheckFailure("stream event is not JSON") from exc
        require(not event.get("error"), "stream contained an error object")
        if event.get("usage") is not None:
            usage = validate_usage(event["usage"])
        choices = event.get("choices")
        require(isinstance(choices, list), "stream event missing choices")
        chunks += 1
    require(done, "stream ended without [DONE]")
    require(chunks > 0, "stream emitted no JSON chunks")
    require(usage is not None, "stream omitted requested usage accounting")
    return {
        "first_data_ms": first_data_ms,
        "elapsed_ms": (time.perf_counter() - started) * 1000,
        "json_chunks": chunks,
        "usage": usage,
    }


def check_unknown_model(ctx: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": "tokenlabs/definitely-not-a-model",
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 1,
    }
    response = ctx["session"].post(
        f"{ctx['url']}/v1/chat/completions",
        json=payload,
        timeout=ctx["timeout"],
    )
    require(response.status_code in (400, 404), f"unknown model returned {response.status_code}")
    return {"status_code": response.status_code}


def check_invalid_request(ctx: dict[str, Any]) -> dict[str, Any]:
    payload = {"model": ctx["model"], "messages": "not-an-array"}
    response = ctx["session"].post(
        f"{ctx['url']}/v1/chat/completions",
        json=payload,
        timeout=ctx["timeout"],
    )
    require(response.status_code in (400, 422), f"invalid request returned {response.status_code}")
    return {"status_code": response.status_code}


def check_tools(ctx: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": ctx["model"],
        "messages": [{"role": "user", "content": "Call lookup_city for Paris."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup_city",
                    "description": "Look up a city",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": "lookup_city"}},
        "temperature": 0,
        "max_tokens": 128,
    }
    _, result = request_json(
        ctx["session"],
        "POST",
        f"{ctx['url']}/v1/chat/completions",
        timeout=ctx["timeout"],
        json=payload,
    )
    body = result["body"]
    summary = validate_chat_response(body, ctx["model"])
    calls = body["choices"][0]["message"].get("tool_calls")
    require(isinstance(calls, list) and len(calls) == 1, "expected one tool call")
    function = calls[0].get("function") if isinstance(calls[0], dict) else None
    require(isinstance(function, dict), "tool call missing function")
    require(function.get("name") == "lookup_city", "incorrect tool name")
    try:
        arguments = json.loads(function.get("arguments", ""))
    except ValueError as exc:
        raise CheckFailure("tool arguments are not valid JSON") from exc
    require(arguments == {"city": "Paris"}, f"incorrect tool arguments: {arguments}")
    summary["elapsed_ms"] = result["elapsed_ms"]
    return summary


def check_structured_output(ctx: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": ctx["model"],
        "messages": [{"role": "user", "content": "Return readiness as ready."}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "readiness",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"readiness": {"type": "string"}},
                    "required": ["readiness"],
                    "additionalProperties": False,
                },
            },
        },
        "temperature": 0,
        "max_tokens": 64,
    }
    _, result = request_json(
        ctx["session"],
        "POST",
        f"{ctx['url']}/v1/chat/completions",
        timeout=ctx["timeout"],
        json=payload,
    )
    body = result["body"]
    summary = validate_chat_response(body, ctx["model"])
    content = body["choices"][0]["message"].get("content")
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise CheckFailure("structured output is not valid JSON") from exc
    require(
        isinstance(parsed, dict) and isinstance(parsed.get("readiness"), str),
        "structured output does not match schema",
    )
    summary["elapsed_ms"] = result["elapsed_ms"]
    return summary


CHECKS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "provider-catalog": check_provider_catalog,
    "models": check_models,
    "auth-required": check_auth_required,
    "nonstream": check_nonstream,
    "stream": check_stream,
    "unknown-model": check_unknown_model,
    "invalid-request": check_invalid_request,
    "tools": check_tools,
    "structured-output": check_structured_output,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--provider-models-url")
    parser.add_argument("--api-key-env", default="TOKENLABS_BENCH_API_KEY")
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--tools", action="store_true")
    parser.add_argument("--structured-outputs", action="store_true")
    args = parser.parse_args()
    if args.timeout < 1 or args.repetitions < 1:
        parser.error("timeout and repetitions must be positive")
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        parser.error(f"environment variable {args.api_key_env!r} is not set")

    session = requests.Session()
    session.headers.update(
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    )
    ctx = {
        "session": session,
        "url": args.url.rstrip("/"),
        "model": args.model,
        "timeout": args.timeout,
        "provider_models_url": args.provider_models_url,
    }
    selected = [
        "models",
        "auth-required",
        "nonstream",
        "stream",
        "unknown-model",
        "invalid-request",
    ]
    if args.provider_models_url:
        selected.insert(0, "provider-catalog")
    if args.tools:
        selected.append("tools")
    if args.structured_outputs:
        selected.append("structured-output")

    report: dict[str, Any] = {
        "schema_version": 1,
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": ctx["url"],
        "model": args.model,
        "repetitions": args.repetitions,
        "checks": [],
    }
    failures = 0
    for repetition in range(1, args.repetitions + 1):
        for name in selected:
            started = time.perf_counter()
            try:
                evidence = CHECKS[name](ctx)
                result = {"name": name, "repetition": repetition, "passed": True, "evidence": evidence}
            except Exception as exc:  # each failure must be reported before exit
                failures += 1
                result = {
                    "name": name,
                    "repetition": repetition,
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            result["check_elapsed_ms"] = (time.perf_counter() - started) * 1000
            report["checks"].append(result)
            print(f"{'PASS' if result['passed'] else 'FAIL'} {name} repetition={repetition}")
    report["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    report["passed"] = failures == 0
    report["failure_count"] = failures
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {args.output}; passed={report['passed']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
