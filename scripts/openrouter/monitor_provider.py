#!/usr/bin/env python3
"""Record authenticated synthetic streams across a provider selector cutover."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import time

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--duration', type=float, default=1800)
    parser.add_argument('--interval', type=float, default=10)
    parser.add_argument('--api-key-env', default='TOKENLABS_BENCH_API_KEY')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.duration <= 0 or args.interval < 0:
        parser.error('duration must be positive and interval non-negative')
    key = os.environ.get(args.api_key_env)
    if not key:
        parser.error('API credential environment variable is missing')
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer '+key
    args.out.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    records = []
    while time.monotonic()-started < args.duration:
        tick = time.monotonic()
        record = {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'model': args.model, 'done': False, 'ttft_seconds': None}
        try:
            with session.post(args.url.rstrip('/')+'/v1/chat/completions', json={
                    'model': args.model, 'messages': [{'role': 'user',
                        'content': 'Explain one useful Python debugging technique briefly.'}],
                    'max_tokens': 1024, 'temperature': 0, 'stream': True,
                    'stream_options': {'include_usage': True}}, stream=True, timeout=180) as response:
                record['status'] = response.status_code
                record['headers_seconds'] = time.monotonic()-tick
                response.raise_for_status()
                record['request_id'] = response.headers.get('x-request-id')
                for line in response.iter_lines(chunk_size=1):
                    if not line.startswith(b'data: '):
                        continue
                    data = line[6:].strip()
                    if data == b'[DONE]':
                        record['done'] = True
                        break
                    event = json.loads(data)
                    record['response_id'] = event.get('id', record.get('response_id'))
                    if event.get('usage'):
                        record['usage'] = event['usage']
                    for choice in event.get('choices', []):
                        if choice.get('finish_reason'):
                            record['finish_reason'] = choice['finish_reason']
                        delta = choice.get('delta', {})
                        if record['ttft_seconds'] is None and any(
                                delta.get(k) for k in ('content', 'reasoning', 'reasoning_content')):
                            record['ttft_seconds'] = time.monotonic()-tick
                usage = record.get('usage', {})
                if (not record['done'] or record['ttft_seconds'] is None
                        or not record.get('finish_reason')
                        or usage.get('total_tokens') != usage.get('prompt_tokens', 0)+usage.get('completion_tokens', 0)):
                    raise ValueError('Incomplete stream or missing usage')
        except (requests.RequestException, ValueError) as error:
            record['error_type'] = type(error).__name__
        record['seconds'] = time.monotonic()-tick
        records.append(record)
        with args.out.with_suffix('.jsonl').open('a') as progress:
            progress.write(json.dumps(record)+'\n')
        if record.get('error_type'):
            break
        remaining = args.duration-(time.monotonic()-started)
        if remaining > 0:
            time.sleep(min(args.interval, remaining))
    report = {'passed': bool(records) and all(not r.get('error_type') for r in records),
              'model': args.model, 'duration_seconds': time.monotonic()-started,
              'requests': len(records), 'failures': [r for r in records if r.get('error_type')]}
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
