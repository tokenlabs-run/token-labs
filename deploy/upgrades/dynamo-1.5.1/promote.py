#!/usr/bin/env python3
"""Promote one tested EPP graph while preserving the other model's routes."""
import argparse
import json
from pathlib import Path
import subprocess
import yaml

HERE = Path(__file__).resolve().parent


def kubectl(*args):
    return subprocess.check_output(['kubectl', *args, '-n', 'token-labs'])


def get(kind, name):
    return json.loads(kubectl('get', kind, name, '-o', 'json'))


def patch(kind, name, operations):
    print(kubectl('patch', kind, name, '--type=json', '-p', json.dumps(operations)).decode().strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=['qwen', 'muse'], required=True)
    parser.add_argument('--stage', action='store_true')
    parser.add_argument('--evidence-dir', type=Path, required=True)
    args = parser.parse_args()
    short = args.model
    for suffix, count in [('direct', 15), ('epp-chat', 3)]:
        results = [json.loads(line) for line in (args.evidence_dir / f'{short}-{suffix}.jsonl').read_text().splitlines()]
        assert len(results) == count and all(result['passed'] for result in results), f'{suffix} checks must pass before promotion'
    if not args.stage:
        results = [json.loads(line) for line in (args.evidence_dir / f'{short}-staged-public.jsonl').read_text().splitlines()]
        assert len(results) == 3 and all(result['passed'] for result in results), 'Staged public EPP checks must pass before final promotion'
    graph = yaml.safe_load((HERE / f'{short}-graph.yaml').read_text())
    live = get('dgd', graph['metadata']['name'])
    assert any(c['type'] == 'Ready' and c['status'] == 'True' for c in live['status']['conditions']), 'Graph must be ready before promotion'
    api = yaml.safe_load((HERE / f'{short}-api-frontend.yaml').read_text())
    deploy = get('deployment', api['metadata']['name'])
    assert deploy['status'].get('readyReplicas') == 1
    service = yaml.safe_load((HERE / f'{short}-stable-service.yaml').read_text())
    current = get('service', service['metadata']['name'])
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    (args.evidence_dir / f'{short}-service-before-promotion.json').write_text(json.dumps(current, indent=2))
    if current['spec']['selector'] != service['spec']['selector']:
        patch('service', service['metadata']['name'], [{'op': 'test', 'path': '/spec/selector', 'value': current['spec']['selector']}, {'op': 'replace', 'path': '/spec/selector', 'value': service['spec']['selector']}])
    model = next(e['value'] for e in graph['spec']['components'][0]['podTemplate']['spec']['containers'][0]['env'] if e['name'] == 'DYN_MODEL_NAME')
    for desired in yaml.safe_load_all((HERE / 'public-routes.yaml').read_text()):
        kind = desired['kind'].lower()
        name = desired['metadata']['name']
        current = get(kind, name)
        (args.evidence_dir / f'{short}-{kind}-before-promotion.json').write_text(json.dumps(current, indent=2))
        rules = current['spec']['rules']
        new_rules = json.loads(json.dumps(rules))
        def matches(rule):
            if kind == 'aigatewayroute':
                return any(h.get('value') == model for m in rule.get('matches', []) for h in m.get('headers', []))
            return any(m.get('path', {}).get('value') == f'/models/{short}/v1' for m in rule.get('matches', []))
        replacements = [rule for rule in desired['spec']['rules'] if matches(rule)]
        if args.stage:
            for rule in replacements:
                if any(ref.get('kind') == 'InferencePool' for ref in rule['backendRefs']):
                    for match in rule['matches']:
                        match['headers'].append({'type': 'Exact', 'name': 'x-dynamo-epp-promotion', 'value': short + '-151'})
        assert replacements
        for replacement in replacements:
            is_pool = any(ref.get('kind') == 'InferencePool' for ref in replacement['backendRefs'])
            indices = [i for i, rule in enumerate(new_rules) if matches(rule) and any(ref.get('kind') == 'InferencePool' for ref in rule['backendRefs']) == is_pool]
            assert len(indices) <= 1
            if indices:
                new_rules[indices[0]] = replacement
            else:
                new_rules.append(replacement)
        if new_rules != rules:
            patch(kind, name, [{'op': 'test', 'path': '/spec/rules', 'value': rules}, {'op': 'replace', 'path': '/spec/rules', 'value': new_rules}])


if __name__ == '__main__':
    main()
