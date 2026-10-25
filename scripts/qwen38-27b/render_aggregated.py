#!/usr/bin/env python3
"""Render an operator-managed graph from the validated Qwen3.8 serving settings."""
import copy
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
source = json.loads((ROOT / 'deploy/models/qwen3.8-27b-nvfp4/dynamo/candidate.json').read_text())
pod = next(x for x in source['items'] if x['kind'] == 'Deployment')['spec']['template']['spec']
name = 'qwen38-nvfp4-dynamo-agg'

def container(name_in):
    c = copy.deepcopy(next(c for c in pod['containers'] if c['name'] == name_in))
    c['name'] = 'main'
    if name_in == 'frontend':
        # Empty args trigger the operator's default module arguments.
        c['command'] = ['python3']
        c['args'] = ['-m', 'dynamo.frontend'] + c['args']
    # The operator supplies the graph namespace, Kubernetes discovery, and RBAC.
    for flag in ['--namespace', '--discovery-backend']:
        i = c['args'].index(flag)
        del c['args'][i:i + 2]
    c['env'] = [e for e in c['env'] if e['name'] != 'DYN_FILE_KV']
    c['volumeMounts'] = [m for m in c['volumeMounts'] if m['name'] != 'discovery']
    return c

worker = copy.deepcopy(pod)
worker.pop('automountServiceAccountToken', None)
worker['containers'] = [container('worker')]
worker['volumes'] = [v for v in worker['volumes'] if v['name'] != 'discovery']
frontend = {
    'nodeSelector': copy.deepcopy(pod['nodeSelector']),
    'securityContext': copy.deepcopy(pod['securityContext']),
    'tolerations': copy.deepcopy(pod['tolerations']),
    'containers': [container('frontend')],
    'volumes': [copy.deepcopy(v) for v in pod['volumes'] if v['name'] == 'model-cache'],
}
graph = {
    'apiVersion': 'nvidia.com/v1beta1',
    'kind': 'DynamoGraphDeployment',
    'metadata': {
        'name': name, 'namespace': 'token-labs',
        'labels': {'app.kubernetes.io/name': name, 'app.kubernetes.io/part-of': 'dynamo'},
    },
    'spec': {
        'backendFramework': 'vllm',
        'components': [
            {'name': 'Frontend', 'type': 'frontend', 'replicas': 1,
             'runtimeVersionOverride': '1.6.0', 'podTemplate': {'spec': frontend}},
            {'name': 'VllmWorker', 'type': 'worker', 'replicas': 1,
             'runtimeVersionOverride': '1.6.0', 'sharedMemorySize': '16Gi',
             'podTemplate': {'spec': worker}},
        ],
    },
}
print('# Operator-managed alternative to candidate.json; both require the same Spark-01 GPU.')
print('# Public Service selectors are intentionally managed separately from this graph.')
print(yaml.safe_dump(graph, sort_keys=False), end='')
