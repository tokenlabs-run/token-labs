#!/usr/bin/env python3
"""Switch the stable Qwen3.8 Service after checking operator migration evidence."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import requests

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--evidence', type=Path, required=True)
p.add_argument('--apply', action='store_true')
a = p.parse_args()
k = ['kubectl', '--context=kubernetes-admin@kubernetes', '-n', 'token-labs']
def get(*args):
    return json.loads(subprocess.check_output(k + ['get', *args, '-o', 'json']))

assert json.loads((a.evidence / 'conformance.json').read_text())['passed']
benchmark = json.loads((a.evidence / 'benchmark-c4.json').read_text())
assert benchmark['summary']['passed'] and benchmark['summary']['errors'] == 0
assert benchmark['concurrency'] == 4 and benchmark['summary']['requests'] >= 12
graph = get('dynamographdeployment', 'qwen38-nvfp4-dynamo-agg')
assert graph['status']['observedGeneration'] == graph['metadata']['generation']
assert any(c['type'] == 'Ready' and c['status'] == 'True' for c in graph['status']['conditions'])
service = get('svc', 'qwen38-nvfp4-dynamo-agg')
slices = get('endpointslices', '-l', 'kubernetes.io/service-name=qwen38-nvfp4-dynamo-agg')
ready = [e for item in slices['items'] for e in item['endpoints'] if e['conditions'].get('ready')]
assert len(ready) == 1, ready
s = requests.Session()
s.trust_env = False
url = 'http://' + service['spec']['clusterIP'] + ':8000'
r = s.get(url + '/v1/models', timeout=10)
r.raise_for_status()
assert {m['id'] for m in r.json()['data']} == {'nvidia/Qwen3.8-27B-NVFP4'}
old = {'token-labs/model-id': 'qwen38-nvfp4', 'token-labs/slot': 'blue'}
new = {'nvidia.com/dynamo-graph-deployment-name': 'qwen38-nvfp4-dynamo-agg', 'nvidia.com/dynamo-component-type': 'frontend'}
stable = get('svc', 'qwen38-nvfp4')
current = stable['spec']['selector']
assert current in (old, new), current
patch = [
    {'op': 'test', 'path': '/metadata/resourceVersion', 'value': stable['metadata']['resourceVersion']},
    {'op': 'test', 'path': '/spec/selector', 'value': current},
    {'op': 'replace', 'path': '/spec/selector', 'value': new},
]
cmd = k + ['patch', 'svc', 'qwen38-nvfp4', '--type=json', '-p', json.dumps(patch), '-o', 'json']
if not a.apply:
    cmd += ['--dry-run=server']
result = json.loads(subprocess.check_output(cmd))
record = {'applied': a.apply, 'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'before': current, 'after': result['spec']['selector'], 'ready_endpoints': ready}
(a.evidence / ('cutover.json' if a.apply else 'cutover-dry-run.json')).write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
