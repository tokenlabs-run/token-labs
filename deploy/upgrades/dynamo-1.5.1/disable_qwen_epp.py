#!/usr/bin/env python3
"""Retire Qwen EPP traffic while preserving the immutable graph and GPU worker."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error

CONTEXT = 'kubernetes-admin@kubernetes'
NAMESPACE = 'token-labs'
GRAPH = 'qwen36-nvfp4-dynamo-agg-151-epp'
POOL = GRAPH + '-pool'
STABLE = 'qwen36-nvfp4-frontend'
WORKER = GRAPH + '-0-vllmworker-68p9j'
MODEL = 'nvidia/Qwen3.6-35B-A3B-NVFP4'


def kubectl(*args):
    return json.loads(subprocess.check_output(['kubectl', '--context=' + CONTEXT,
        '--request-timeout=30s', '-n', NAMESPACE, *args, '-o', 'json'], text=True))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def identity(pod):
    return {'uid': pod['metadata']['uid'], 'spec_sha256': digest(pod['spec']),
            'containers': {c['name']: {'id': c['containerID'], 'restarts': c['restartCount'],
                                      'ready': c['ready']}
                           for c in pod['status']['containerStatuses']}}


def probe(path='/models/qwen/v1/chat/completions'):
    body = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'Reply with READY only.'}],
            'max_tokens': 16, 'temperature': 0, 'stream': False,
            'chat_template_kwargs': {'enable_thinking': False}}
    request = urllib.request.Request('https://api.tokenlabs.run' + path,
        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
        assert response.status == 200 and result['model'] == MODEL
        assert result['choices'][0]['message']['content'].strip() == 'READY'
        return {'http_status': response.status, 'model': result['model'], 'reply': 'READY'}


def observe_generic():
    try:
        return probe('/v1/chat/completions')
    except urllib.error.HTTPError as error:
        return {'http_status': error.code, 'body': error.read().decode()[:500]}


def plan(route, canary):
    route_patch = [{'op': 'test', 'path': '/metadata/resourceVersion',
                    'value': route['metadata']['resourceVersion']}]
    targets = [i for i, rule in enumerate(route['spec']['rules'])
               if any(ref.get('name') == POOL for ref in rule.get('backendRefs', []))]
    assert all(len(route['spec']['rules'][i]['backendRefs']) == 1 for i in targets)
    for i in reversed(targets):
        route_patch.append({'op': 'remove', 'path': '/spec/rules/' + str(i)})
    fallback = [r for r in route['spec']['rules'] if any(
        ref.get('name') == 'qwen3-6-35b-a3b-nvfp4' for ref in r.get('backendRefs', []))]
    assert len(fallback) == 1, 'Direct frontend fallback is missing'
    canary_patch = [{'op': 'test', 'path': '/metadata/resourceVersion',
                     'value': canary['metadata']['resourceVersion']}]
    for i, rule in enumerate(canary['spec']['rules']):
        if any(ref.get('name') == POOL for ref in rule.get('backendRefs', [])):
            canary_patch.append({'op': 'replace', 'path': f'/spec/rules/{i}/backendRefs',
                                  'value': [{'name': STABLE, 'port': 8000, 'weight': 1}]})
    return [('aigatewayroute', route, route_patch), ('httproute', canary, canary_patch)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--routes-only', action='store_true',
        help='Keep the immutable DGD and worker; retire only traffic references to EPP')
    args = parser.parse_args()
    if not args.routes_only:
        parser.error('Use --routes-only: the installed operator forbids removing or scaling EPP in place')
    args.evidence.mkdir(parents=True, exist_ok=False)
    def save(name, value):
        (args.evidence / name).write_text(json.dumps(value, indent=2) + '\n')
    stable = kubectl('get', 'service', STABLE)
    slices = kubectl('get', 'endpointslices', '-l', 'kubernetes.io/service-name=' + STABLE)
    assert any(e.get('conditions', {}).get('ready') for s in slices['items']
               for e in (s.get('endpoints') or [])), 'Stable frontend has no ready endpoints'
    worker_before = identity(kubectl('get', 'pod', WORKER))
    assert all(c['ready'] for c in worker_before['containers'].values())
    snapshots = [kubectl('get', 'aigatewayroute', 'token-labs-models'),
                 kubectl('get', 'httproute', 'dynamo-151-qwen-canary'),
                 kubectl('get', 'dynamographdeployment', GRAPH)]
    save('stable-service-before.json', stable)
    save('stable-endpoints-before.json', slices)
    save('worker-before.json', worker_before)
    save('direct-probe-before.json', probe())
    generic_before = observe_generic()
    save('generic-probe-before.json', generic_before)
    save('immutable-dgd-before.json', snapshots[2])
    plans = plan(*snapshots[:2])
    save('retained-epp.json', {'reason': 'DGD topology is immutable; EPP requires exactly one replica',
                             'graph': GRAPH, 'worker_migration_required': True})
    for kind, original, patch in plans:
        name = original['metadata']['name']
        save(kind + '-before.json', original)
        save(kind + '-patch.json', patch)
        kubectl('patch', kind, name, '--type=json', '-p', json.dumps(patch), '--dry-run=server')
        if args.apply and len(patch) > 1:
            kubectl('patch', kind, name, '--type=json', '-p', json.dumps(patch))
            save(kind + '-after.json', kubectl('get', kind, name))
            current = identity(kubectl('get', 'pod', WORKER))
            assert current == worker_before, 'Worker identity, readiness or restart state changed'
    if args.apply:
        for _ in range(20):
            compiled = kubectl('get', 'httproute', 'token-labs-models')
            if POOL not in json.dumps(compiled['spec']):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Compiled route still references the retired EPP path')
        generic_after = observe_generic()
        save('generic-probe-after.json', generic_after)
        if generic_before['http_status'] == 200:
            assert generic_after['http_status'] == 200, 'Generic route regressed'
        save('direct-probe-after.json', probe())
    save('result.json', {'applied': args.apply, 'worker_unchanged': True,
        'routes_only': args.routes_only, 'epp_component_removed': False,
        'stable_selector_unchanged': kubectl('get', 'service', STABLE)['spec']['selector'] == stable['spec']['selector'],
        'finished_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()})
    print(json.dumps({'applied': args.apply, 'evidence': str(args.evidence), 'worker_unchanged': True}))


if __name__ == '__main__':
    main()
