#!/usr/bin/env python3
"""Compare n=1, n=2, n=1 with bounded requests and preserve raw evidence."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--url', default='http://127.0.0.1:18098')
p.add_argument('--model', default='Qwen/Qwen3-30B-A3B-Instruct-2507-FP8')
p.add_argument('--timeout', type=int, default=30)
p.add_argument('--output', type=Path, default=Path('results') / ('dynamo-14098-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
results = []
for label, n in [('baseline', 1), ('parallel', 2), ('recovery', 1)]:
    request = {'model': a.model, 'messages': [{'role': 'user', 'content': 'What is 17 * 23?'}], 'n': n, 'temperature': 0.1, 'max_tokens': 64, 'stream': False}
    request_path = a.output / f'{label}.request.json'
    request_path.write_text(json.dumps(request, indent=2) + '\n')
    response_path = a.output / f'{label}.response.json'
    start = time.monotonic()
    r = subprocess.run(['curl', '--silent', '--show-error', '--max-time', str(a.timeout), '--connect-timeout', '5', '--header', 'Content-Type: application/json', '--data-binary', '@' + str(request_path), '--output', str(response_path), '--dump-header', str(a.output / f'{label}.headers.txt'), '--write-out', '%{http_code}', a.url.rstrip('/') + '/v1/chat/completions'], capture_output=True, text=True)
    body = response_path.read_bytes() if response_path.exists() else b''
    result = {'label': label, 'n': n, 'curl_exit': r.returncode, 'http_status': r.stdout, 'elapsed_seconds': round(time.monotonic() - start, 3), 'response_bytes': len(body), 'stderr': r.stderr}
    try:
        choices = json.loads(body).get('choices', [])
        result['choice_indices'] = [c['index'] for c in choices]
        result['finish_reasons'] = [c.get('finish_reason') for c in choices]
    except (ValueError, KeyError, AttributeError):
        pass
    results.append(result)
    print(json.dumps(result), flush=True)
    (a.output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
