#!/usr/bin/env python3
"""Verify one full-context request and rejection beyond the configured limit.

Uses synthetic token IDs to test allocation and API limits, not answer quality.
Run against an isolated diagnostic endpoint; this can occupy a GPU for minutes.
"""
import argparse
import json
import time
import urllib.error
import urllib.request

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--base-url', required=True)
p.add_argument('--model', required=True)
p.add_argument('--limit', type=int, required=True)
a = p.parse_args()
models = json.load(urllib.request.urlopen(a.base_url.rstrip('/')+'/v1/models'))
model = next(m for m in models['data'] if m['id'] == a.model)
assert model['max_model_len'] == a.limit, model
for count, expected in [(a.limit - 1, 200), (a.limit + 1, 400)]:
    payload = {'model': a.model, 'prompt': [42] * count, 'max_tokens': 1, 'temperature': 0}
    req = urllib.request.Request(a.base_url.rstrip('/')+'/v1/completions', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            code, body = r.status, json.load(r)
    except urllib.error.HTTPError as e:
        code, body = e.code, json.load(e)
    print(json.dumps({'model': a.model, 'input_tokens': count, 'expected_status': expected, 'status': code, 'elapsed_seconds': round(time.monotonic()-start, 2), 'response':body}), flush=True)
    assert code == expected, body
    if code == 200:
        assert body['usage']['prompt_tokens'] == count, body
        assert body['usage']['completion_tokens'] == 1, body
