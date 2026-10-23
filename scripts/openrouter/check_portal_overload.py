#!/usr/bin/env python3
"""Check public Flint backpressure with a disposable key kept inside AWS."""
import argparse
import json
from pathlib import Path
import subprocess


def check():
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    import uuid
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    from portal.app import Settings
    from portal.store import Store, tenants

    settings = Settings.from_env()
    store = Store(settings.database_url)
    tenant = str(uuid.uuid4())
    with store.engine.begin() as connection:
        connection.execute(tenants.insert().values(id=tenant,
            name='Operator Flint overload validation', enabled=True))
    key = None
    try:
        key = store.create_key(tenant, 'Disposable overload probe', True, 1)
        barrier = threading.Barrier(8)
        body = json.dumps({'model': 'RecursiveSI/flint', 'messages': [
            {'role': 'user', 'content': 'Count upward indefinitely.'}],
            'max_tokens': 8192, 'temperature': 0, 'stream': True}).encode()

        def one_request(index):
            barrier.wait()
            started = time.monotonic()
            request = Request(settings.inference_url.rstrip('/')+'/chat/completions',
                data=body, headers={'Authorization': 'Bearer '+key['key'],
                                    'Content-Type': 'application/json'})
            try:
                with urlopen(request, timeout=60) as response:
                    record = {'status': response.status,
                              'headers_ms': (time.monotonic()-started)*1000}
                    time.sleep(5)
                    return record
            except HTTPError as error:
                record = {'status': error.code,
                          'headers_ms': (time.monotonic()-started)*1000,
                          'retry_after': error.headers.get('Retry-After')}
                error.close()
                return record
            except Exception as error:
                return {'status': 0, 'error_type': type(error).__name__}

        with ThreadPoolExecutor(max_workers=8) as executor:
            records = list(executor.map(one_request, range(8)))
        accepted = [r for r in records if r['status'] == 200]
        rejected = [r for r in records if r['status'] == 429]
        passed = (len(accepted) == 1 and len(rejected) == 7
                  and all(r.get('retry_after') for r in rejected)
                  and all(r['headers_ms'] < 1000 for r in rejected))
        return {'passed': passed, 'model': 'RecursiveSI/flint',
                'url': settings.inference_url, 'accepted': len(accepted),
                'rejected': len(rejected), 'requests': records}
    finally:
        if key:
            store.transition_key(tenant, key['id'], 'revoke')
        with store.engine.begin() as connection:
            connection.execute(tenants.update().where(tenants.c.id == tenant).values(enabled=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--inside-portal', action='store_true')
    args = parser.parse_args()
    if args.inside_portal:
        print(json.dumps(check()))
    else:
        if args.output is None:
            parser.error('--output is required')
        command = ['kubectl', '--context=inference-prod-us-east-1', '-n', 'inference',
            'exec', 'deployment/inference-portal-flint-green', '-c', 'portal', '--',
            'python', '-c', Path(__file__).read_text(), '--inside-portal']
        report = json.loads(subprocess.check_output(command, text=True, timeout=180))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report['passed'] else 1)
