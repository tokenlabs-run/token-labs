#!/usr/bin/env python3
"""Add Qwen's stable Service to the serving aggregator's discovery targets.

Applying restarts the aggregator Deployment. Use only with explicit user approval
for an in-place change. Model workers and public Service selectors stay unchanged.
"""
import argparse
import json
from pathlib import Path
import subprocess

K = ['kubectl', '--context=kubernetes-admin@kubernetes', '-n', 'token-labs']


def get(kind, name=None):
    return json.loads(subprocess.check_output(K + ['get', kind] + ([name] if name else []) + ['-o', 'json']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--apply-approved-in-place', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    service = get('service', 'model-aggregator')
    active = [d for d in get('deployments')['items'] if all(
        d['spec']['template']['metadata']['labels'].get(k) == v
        for k, v in service['spec']['selector'].items())]
    if len(active) != 1:
        raise RuntimeError('Expected one serving aggregator Deployment')
    deployment = active[0]
    target = get('service', 'qwen36-nvfp4-frontend')
    endpoints = json.loads(subprocess.check_output(K + ['get', 'endpointslices', '-l',
        'kubernetes.io/service-name=qwen36-nvfp4-frontend', '-o', 'json']))
    if not any(e.get('conditions', {}).get('ready') for s in endpoints['items'] for e in (s.get('endpoints') or [])):
        raise RuntimeError('Qwen stable Service has no ready endpoints')
    containers = deployment['spec']['template']['spec']['containers']
    ci = next(i for i, c in enumerate(containers) if c['name'] == 'aggregator')
    ei = next(i for i, e in enumerate(containers[ci]['env']) if e['name'] == 'MODEL_BACKEND_SERVICES')
    original = containers[ci]['env'][ei]['value']
    backends = set(original.split(','))
    backends.add(target['metadata']['name'])
    value = ','.join(sorted(backends))
    for name, obj in [('service-before', service), ('active-deployment-before', deployment),
                      ('qwen-stable-before', target), ('pods-before', get('pods'))]:
        (args.output / (name + '.json')).write_text(json.dumps(obj, indent=2) + '\n')
    if original == value:
        print('Stable Qwen discovery target is already present')
        return
    patch = [{'op': 'test', 'path': '/metadata/resourceVersion', 'value': deployment['metadata']['resourceVersion']},
             {'op': 'test', 'path': f'/spec/template/spec/containers/{ci}/env/{ei}/value', 'value': original},
             {'op': 'replace', 'path': f'/spec/template/spec/containers/{ci}/env/{ei}/value', 'value': value}]
    file = args.output / 'deployment-patch.json'
    file.write_text(json.dumps(patch, indent=2) + '\n')
    command = K + ['patch', 'deployment', deployment['metadata']['name'], '--type=json', '--patch-file', str(file)]
    subprocess.run(command + ['--dry-run=server', '-o', 'name'], check=True)
    if args.apply_approved_in_place:
        subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
