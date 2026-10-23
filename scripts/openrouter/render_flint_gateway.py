#!/usr/bin/env python3
"""Render a separate Flint gateway candidate using the live gateway's settings."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = 'kubernetes-admin@kubernetes'
NAMESPACE = 'token-labs'
CANDIDATE = 'model-aggregator-flint-green'


def get(kind, name=None):
    command = ['kubectl', '--context='+CONTEXT, '-n', NAMESPACE, 'get', kind]
    if name:
        command.append(name)
    return json.loads(subprocess.check_output(command + ['-o', 'json']))


def render():
    service = get('service', 'model-aggregator')
    deployments = get('deployments')['items']
    active = next(d for d in deployments if all(
        d['spec']['template']['metadata']['labels'].get(k) == v
        for k, v in service['spec']['selector'].items()))
    if active['metadata']['name'] == CANDIDATE:
        raise RuntimeError('The Flint gateway is already active; use a new candidate name for another rollout')
    deployment = {'apiVersion': 'apps/v1', 'kind': 'Deployment',
                  'metadata': {'name': CANDIDATE, 'namespace': NAMESPACE},
                  'spec': copy.deepcopy(active['spec'])}
    deployment['spec']['replicas'] = 1
    deployment['spec']['selector'] = {'matchLabels': {'app': CANDIDATE}}
    template = deployment['spec']['template']
    template['metadata'] = {'labels': {'app': CANDIDATE}}
    # The CPU-only candidate must not bypass node-pressure taints.
    nodes = get('nodes')['items']
    healthy = [n['metadata']['name'] for n in nodes
               if any(c['type'] == 'Ready' and c['status'] == 'True'
                      for c in n['status']['conditions'])
               and not any(c['type'] in ('DiskPressure', 'MemoryPressure', 'PIDPressure')
                           and c['status'] == 'True' for c in n['status']['conditions'])]
    node = next((name for name in ('controller', 'spark-01', 'spark-02')
                 if name in healthy), None)
    if node is None:
        raise RuntimeError('No healthy node has been identified for the gateway candidate')
    template['spec']['nodeSelector'] = {'kubernetes.io/hostname': node}
    container = template['spec']['containers'][0]
    container['args'] = [
        'pip install fastapi==0.158.1 uvicorn==0.54.0 httpx==0.28.1 --quiet\n'
        'exec uvicorn aggregator:app --host 0.0.0.0 --port 8000 --app-dir /app\n']
    selector = ','.join(f'{k}={v}' for k, v in service['spec']['selector'].items())
    pods = json.loads(subprocess.check_output([
        'kubectl', '--context='+CONTEXT, '-n', NAMESPACE, 'get', 'pods',
        '-l', selector, '-o', 'json']))['items']
    container['image'] = pods[0]['status']['containerStatuses'][0]['imageID'].removeprefix('docker-pullable://')
    backends = []
    for s in get('services')['items']:
        labels = s['metadata'].get('labels', {})
        selected = s['spec'].get('selector', {})
        if (labels.get('token-labs/model') == 'true'
            or selected.get('nvidia.com/dynamo-component-type') == 'frontend'
            or (selected.get('llm-d.ai/inference-serving') == 'true'
                and selected.get('llm-d.ai/role') == 'decode')):
            backends.append(s['metadata']['name'])
    env = {e['name']: e for e in container['env']}
    env['MODEL_BACKEND_SERVICES'] = {'name': 'MODEL_BACKEND_SERVICES',
        'value': ','.join(sorted(set(backends + ['flint-nvfp4'])))}
    env['MODEL_CONCURRENCY_LIMITS'] = {'name': 'MODEL_CONCURRENCY_LIMITS',
        'value': json.dumps({'RecursiveSI/flint': 1})}
    container['env'] = list(env.values())
    configmaps = []
    for key, path, volume_name in [
        ('aggregator.py', ROOT/'deploy/platform/model-aggregator/aggregator.py', 'code'),
        ('models.json', ROOT/'deploy/platform/model-aggregator/models.json', 'openrouter-model-document'),
    ]:
        content = path.read_text()
        name = 'flint-provider-' + ('code-' if key.endswith('.py') else 'catalog-') + hashlib.sha256(content.encode()).hexdigest()[:10]
        configmaps.append({'apiVersion': 'v1', 'kind': 'ConfigMap',
            'metadata': {'name': name, 'namespace': NAMESPACE},
            'immutable': True, 'data': {key: content}})
        volume = next(v for v in template['spec']['volumes'] if v['name'] == volume_name)
        volume['configMap']['name'] = name
    diagnostic = {'apiVersion': 'v1', 'kind': 'Service',
        'metadata': {'name': CANDIDATE, 'namespace': NAMESPACE},
        'spec': {'selector': {'app': CANDIDATE},
                 'ports': [{'name': 'http', 'port': 8000, 'targetPort': 8000}]}}
    model = {'apiVersion': 'v1', 'kind': 'Service',
        'metadata': {'name': 'flint-nvfp4', 'namespace': NAMESPACE},
        'spec': {'selector': {'token-labs/model-id': 'flint-nvfp4', 'token-labs/slot': 'green'},
                 'ports': [{'name': 'http', 'port': 8000, 'targetPort': 'http'}]}}
    return {'apiVersion': 'v1', 'kind': 'List',
            'items': [*configmaps, deployment, diagnostic, model]}, service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    manifest, previous = render()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'gateway-candidate.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (args.out/'gateway-service-before.json').write_text(json.dumps(previous, indent=2)+'\n')
    print(args.out/'gateway-candidate.json')


if __name__ == '__main__':
    main()
