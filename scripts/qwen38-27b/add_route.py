#!/usr/bin/env python3
"""Append Qwen3.8 to the existing DGX AI route without regenerating other rules."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
KUBE = ['kubectl', '--context=kubernetes-admin@kubernetes', '-n', 'token-labs']
MODEL = 'nvidia/Qwen3.8-27B-NVFP4'
BACKEND = 'qwen38-admission-gateway'


def read(kind, name):
    return json.loads(subprocess.check_output(KUBE + ['get', kind, name, '-o', 'json']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    route = read('aigatewayroute', 'token-labs-models')
    rule = {'matches': [{'headers': [{'type': 'Exact', 'name': 'x-ai-eg-model', 'value': MODEL}]}],
            'backendRefs': [{'name': BACKEND}],
            'timeouts': {'request': '600s', 'backendRequest': '600s'}}
    existing = [r for r in route['spec']['rules'] if any(
        h.get('name') == 'x-ai-eg-model' and h.get('value') == MODEL
        for match in r.get('matches', []) for h in match.get('headers', []))]
    if existing:
        if len(existing) != 1 or [b['name'] for b in existing[0]['backendRefs']] != [BACKEND]:
            raise RuntimeError('An existing Qwen3.8 route uses another backend; refusing to replace it')
        print('Qwen3.8 route already exists')
        return
    patch = [{'op': 'test', 'path': '/metadata/resourceVersion',
              'value': route['metadata']['resourceVersion']},
             {'op': 'add', 'path': '/spec/rules/-', 'value': rule}]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'dgx-route-before.json').write_text(json.dumps(route, indent=2)+'\n')
    (args.out/'dgx-route-patch.json').write_text(json.dumps(patch, indent=2)+'\n')
    if not args.apply:
        print(args.out/'dgx-route-patch.json')
        return
    service = read('service', 'model-aggregator')
    if service['spec']['selector'] != {'app': 'model-aggregator-qwen38-blue'}:
        raise RuntimeError('Promote the validated Qwen3.8 gateway before adding its public model route')
    slices = json.loads(subprocess.check_output(KUBE + ['get', 'endpointslices',
        '-l', 'kubernetes.io/service-name=model-aggregator', '-o', 'json']))
    endpoints = [e for s in slices['items'] for e in s.get('endpoints', [])
                 if e.get('conditions', {}).get('ready') is True]
    if not endpoints or any(not e.get('targetRef', {}).get('name', '').startswith(
            'model-aggregator-qwen38-blue-') for e in endpoints):
        raise RuntimeError('Stable gateway endpoints do not exclusively select the ready candidate')
    (args.out/'dgx-route-endpoints.json').write_text(json.dumps(slices, indent=2)+'\n')
    manifest = str(ROOT/'deploy/models/qwen3.8-27b-nvfp4/dynamo/direct-backend.yaml')
    subprocess.run(KUBE + ['apply', '--dry-run=server', '-f', manifest], check=True)
    subprocess.run(KUBE + ['apply', '-f', manifest], check=True)
    command = KUBE + ['patch', 'aigatewayroute', 'token-labs-models', '--type=json', '-p', json.dumps(patch)]
    subprocess.run(command + ['--dry-run=server'], check=True)
    subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
