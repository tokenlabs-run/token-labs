#!/usr/bin/env python3
"""Guard a gateway-only selector switch; retain the old aggregator for rollback."""
import argparse
import json
from pathlib import Path
import subprocess
import urllib.request

from prepare_responses_gateway import KUBECTL, NAME, read


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    for name in ('conformance.json', 'chat-regression.json', 'admission.json'):
        assert json.loads((args.evidence / name).read_text())['passed'], name
    events = [json.loads(line) for line in (args.evidence / 'codex-tool-smoke.jsonl').read_text().splitlines()]
    assert any(event.get('type') == 'turn.completed' for event in events), 'Codex turn did not complete'
    before = json.loads((args.evidence / 'active-service-before.json').read_text())
    stable = read('service', 'model-aggregator')
    assert stable['spec']['selector'] == before['spec']['selector'], 'Active selector changed'
    old = read('deployment', stable['spec']['selector']['app'])
    candidate = read('deployment', NAME)
    for deployment in (old, candidate):
        assert deployment['status'].get('availableReplicas') == 1, 'Aggregator unavailable'
    code_volume = next(v for v in candidate['spec']['template']['spec']['volumes'] if v['name'] == 'code')
    source = Path(__file__).resolve().parents[2] / 'deploy/platform/model-aggregator/aggregator.py'
    assert read('configmap', code_volume['configMap']['name'])['data']['aggregator.py'] == source.read_text()
    for name in (NAME, stable['metadata']['name']):
        slices = json.loads(subprocess.check_output(KUBECTL + [
            'get', 'endpointslices', '-l', 'kubernetes.io/service-name=' + name, '-o', 'json']))
        ready = [e for s in slices['items'] for e in s.get('endpoints', []) if e.get('conditions', {}).get('ready')]
        assert len(ready) == 1, 'Require exactly one ready endpoint for ' + name
        (args.evidence / (name + '-endpoints-before.json')).write_text(json.dumps(slices, indent=2) + '\n')
    # Verify both catalogs immediately before cutover. The model Services never change.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    inventories = []
    for name in ('model-aggregator', NAME):
        service = read('service', name)
        with opener.open('http://' + service['spec']['clusterIP'] + ':8000/v1/models', timeout=15) as r:
            inventories.append({m['id'] for m in json.load(r)['data']})
    assert inventories[0] == inventories[1] == {
        'nvidia/Qwen3.6-35B-A3B-NVFP4', 'nvidia/Qwen3.8-27B-NVFP4'}
    patch = json.loads((args.evidence / 'selector-patch.json').read_text())
    assert patch == [
        {'op': 'test', 'path': '/spec/selector', 'value': before['spec']['selector']},
        {'op': 'replace', 'path': '/spec/selector', 'value': {'app': NAME}}]
    command = KUBECTL + ['patch', 'service', 'model-aggregator', '--type=json', '-p', json.dumps(patch)]
    subprocess.run(command + ['--dry-run=server'], check=True)
    if args.apply:
        subprocess.run(command, check=True)
    print('Applied' if args.apply else 'Dry run passed; production selector unchanged')


if __name__ == '__main__':
    main()
