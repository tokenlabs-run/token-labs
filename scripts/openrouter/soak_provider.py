#!/usr/bin/env python3
"""Exercise an authenticated provider serially and save usage/error/latency evidence."""
import argparse
import json
import os
from pathlib import Path
import statistics
import time

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--duration', type=float, default=1800)
    parser.add_argument('--max-tokens', type=int, default=1024)
    parser.add_argument('--api-key-env', default='TOKENLABS_BENCH_API_KEY')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.max_tokens < 1:
        parser.error('max-tokens must be positive')
    if args.duration <= 0:
        parser.error('duration must be positive')
    key = os.environ.get(args.api_key_env)
    if not key:
        parser.error('API credential environment variable is missing')
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer ' + key
    started = time.monotonic()
    latencies, errors = [], []
    output_tokens = 0
    while time.monotonic() - started < args.duration:
        payload = {'model': args.model, 'messages': [{'role': 'user', 'content':
            ('Explain one useful Python debugging technique briefly.' if len(latencies) % 2
             else 'What is 17 times 23? Answer briefly.')}],
            'max_tokens': args.max_tokens, 'temperature': 1.0}
        tick = time.monotonic()
        try:
            response = session.post(args.url.rstrip('/') + '/v1/chat/completions',
                                    json=payload, timeout=120)
            response.raise_for_status()
            body = response.json()
            choice = body['choices'][0]
            message = choice['message']
            text = message.get('content') or message.get('reasoning') or message.get('reasoning_content')
            if not text or choice.get('finish_reason') not in ('stop', 'length'):
                raise ValueError('completion is missing content or has an invalid finish reason')
            usage = body['usage']
            if usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']:
                raise ValueError('inconsistent usage accounting')
            output_tokens += usage['completion_tokens']
            latencies.append(time.monotonic() - tick)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.with_suffix('.jsonl').open('a') as progress:
                progress.write(json.dumps({'request': len(latencies), 'seconds': latencies[-1], 'completion_tokens': usage['completion_tokens'], 'finish_reason': choice['finish_reason']})+'\n')
        except (requests.RequestException, ValueError, KeyError, IndexError) as error:
            errors.append({'elapsed_seconds': round(time.monotonic()-started, 2),
                           'error': str(error)})
            break
    ordered = sorted(latencies)
    report = {'model': args.model, 'url': args.url, 'duration_seconds': time.monotonic()-started,
              'requested_duration_seconds': args.duration, 'concurrency': 1,
              'requests': len(latencies), 'errors': errors,
              'completion_tokens': output_tokens,
              'p50_seconds': statistics.median(latencies) if latencies else None,
              'p95_seconds': ordered[min(len(ordered)-1, int(len(ordered)*0.95))] if ordered else None,
              'passed': not errors and bool(latencies) and time.monotonic()-started >= args.duration}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
