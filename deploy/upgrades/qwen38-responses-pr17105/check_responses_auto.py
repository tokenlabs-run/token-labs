#!/usr/bin/env python3
"""Check the no-tools automatic-choice regression through a real Responses API."""

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def check(origin, key, model, stream, omit_tools, choice):
    payload = {
        "model": model,
        "input": 'Return only the JSON object {"ok": true}.',
        "text": {"format": {"type": "json_object"}},
        "chat_template_kwargs": {"enable_thinking": False},
        "max_output_tokens": 128,
        "stream": stream,
    }
    if choice != "omit":
        payload["tool_choice"] = choice
    if not omit_tools:
        payload["tools"] = []
    row = {"stream": stream, "omit_tools": omit_tools, "tool_choice": choice, "passed": False}
    request = Request(
        origin.rstrip("/") + "/v1/responses",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "User-Agent": "tokenlabs-pr17105-validation/1.0",
        },
    )
    try:
        with urlopen(request, timeout=180) as response:
            row["http_status"] = response.status
            if stream:
                completed = False
                text = []
                for line in response:
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == b"[DONE]":
                        continue
                    event = json.loads(data)
                    if event.get("type") in ("error", "response.failed") or event.get("error"):
                        raise ValueError(json.dumps(event)[:500])
                    if event.get("type") == "response.output_text.delta":
                        text.append(event.get("delta", ""))
                    if event.get("type") == "response.completed":
                        completed = event["response"].get("status") == "completed"
                result = "".join(text)
            else:
                data = json.load(response)
                completed = data.get("status") == "completed" and not data.get("error")
                result = "".join(
                    part.get("text", "")
                    for item in data.get("output", [])
                    if item.get("type") == "message"
                    for part in item.get("content", [])
                    if part.get("type") == "output_text"
                )
            row["completed"] = completed
            row["valid_json"] = json.loads(result) == {"ok": True}
            row["passed"] = row["http_status"] == 200 and completed and row["valid_json"]
    except HTTPError as error:
        row.update(http_status=error.code, error=error.read(1000).decode(errors="replace"))
    except (OSError, ValueError) as error:
        row["error"] = str(error)[:1000]
    if "error" in row:
        row["error"] = row["error"].replace(key, "[REDACTED]")
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-file", required=True, type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--choice", choices=("auto", "none", "omit"), default="auto")
    args = parser.parse_args()
    endpoint = json.loads(args.endpoint_file.read_text())
    key = args.key_file.read_text().strip()
    if not endpoint["origin"].startswith("https://") or not key:
        parser.error("Require an HTTPS endpoint and a nonempty credential file")
    rows = [
        check(endpoint["origin"], key, endpoint["served_model"], stream, omit_tools, args.choice)
        for stream in (False, True)
        for omit_tools in (True, False)
    ]
    report = {"endpoint_id": endpoint["id"], "checks": rows, "passed": all(r["passed"] for r in rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
