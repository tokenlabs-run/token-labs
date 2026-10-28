#!/usr/bin/env python3
"""Check mixed chat/Responses load and cross-protocol early rejection on a candidate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request

MODEL = 'nvidia/Qwen3.8-27B-NVFP4'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    release = threading.Event()
    opened = [threading.Event() for _ in range(4)]

    def request(path, body):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(urllib.request.Request(args.url.rstrip('/') + path,
                           data=json.dumps({'model': MODEL, **body}).encode(),
                           headers={'Content-Type': 'application/json'}), timeout=90)

    def occupy(index):
        prompt = 'List the integers from 1 through 1000 in order, one per line. Do not skip any.'
        is_chat = index % 2 == 0
        path = '/v1/chat/completions' if is_chat else '/v1/responses'
        body = ({'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 256} if is_chat
                else {'input': prompt, 'max_output_tokens': 256, 'store': False})
        with request(path, {**body, 'stream': True}) as response:
            opened[index].set()
            assert release.wait(20), 'Test coordinator did not release stream'
            raw = response.read().decode()
            events = [json.loads(line[5:].strip()) for line in raw.splitlines()
                      if line.startswith('data:') and line[5:].strip() not in ('', '[DONE]')]
            assert not any(e.get('error') or e.get('type') in ('error', 'response.failed') for e in events)
            assert '[DONE]' in raw if is_chat else any(e.get('type') in (
                'response.completed', 'response.incomplete') for e in events)
        return {'path': path, 'passed': True}

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(occupy, i) for i in range(4)]
        try:
            assert all(event.wait(20) for event in opened), 'Streams failed to start'
            try:
                with request('/v1/responses', {'input': 'Reply OK.', 'max_output_tokens': 8}):
                    raise AssertionError('Fifth request bypassed model admission limit')
            except urllib.error.HTTPError as e:
                assert e.code == 429 and e.headers['Retry-After'] == '1', e.code
        finally:
            release.set()
        checks = [f.result() for f in futures]
    with request('/v1/responses', {'input': 'Reply with exactly OK.', 'max_output_tokens': 32}) as r:
        assert json.load(r)['status'] == 'completed', 'Capacity did not recover'
    report = {'passed': True, 'url': args.url, 'early_429': True, 'capacity_recovered': True, 'streams': checks}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
