#!/usr/bin/env python3
"""Render an isolated aggregator candidate from the active deployment, without applying it."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess

KUBECTL = ['kubectl', '--context=kubernetes-admin@kubernetes', '-n', 'token-labs']
NAME = 'model-aggregator-responses-green'


def read(kind, name):
    return json.loads(subprocess.check_output(KUBECTL + ['get', kind] + ([name] if name else []) + ['-o', 'json']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    stable = read('service', 'model-aggregator')
    active = stable['spec']['selector'].get('app')
    if not active or active == NAME:
        parser.error('Require a different active aggregator with an app selector')
    # Refuse to render over any candidate that already receives production traffic.
    services = read('services', '')['items']
    for service in services:
        if service['metadata']['name'] != NAME and service['spec'].get('selector', {}).get('app') == NAME:
            parser.error('Candidate is already selected by ' + service['metadata']['name'])
    deployment = read('deployment', active)
    spec = copy.deepcopy(deployment['spec'])
    labels = {'app': NAME}
    spec['selector'] = {'matchLabels': labels}
    spec['template']['metadata'] = {'labels': labels}
    source = Path(__file__).resolve().parents[2] / 'deploy/platform/model-aggregator/aggregator.py'
    code = source.read_text()
    config_name = 'aggregator-responses-' + hashlib.sha256(code.encode()).hexdigest()[:12]
    for volume in spec['template']['spec']['volumes']:
        if volume['name'] == 'code':
            volume['configMap']['name'] = config_name
    def meta(name):
        return {'namespace': 'token-labs', 'name': name}
    items = [
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta(config_name),
         'immutable': True, 'data': {'aggregator.py': code}},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': meta(NAME), 'spec': spec},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': meta(NAME),
         'spec': {'selector': labels, 'ports': [{'name': 'http', 'port': 8000, 'targetPort': 'http'}]}},
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'active-service-before.json').write_text(json.dumps(stable, indent=2) + '\n')
    (args.output / 'candidate.json').write_text(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}, indent=2) + '\n')
    patch = [{'op': 'test', 'path': '/spec/selector', 'value': stable['spec']['selector']},
             {'op': 'replace', 'path': '/spec/selector', 'value': labels}]
    (args.output / 'selector-patch.json').write_text(json.dumps(patch, indent=2) + '\n')
    print('Rendered candidate:', NAME, 'code:', config_name, 'active:', active)


if __name__ == '__main__':
    main()
