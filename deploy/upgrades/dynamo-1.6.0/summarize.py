#!/usr/bin/env python3
"""Summarize completed rollout evidence without treating blocked checks as passing."""
import argparse
import datetime
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--evidence', type=Path, required=True)
a = p.parse_args()

def read(name):
    return json.loads((a.evidence/name).read_text())

def lines(name):
    return [json.loads(line) for line in (a.evidence/name).read_text().splitlines()]

report = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'models': {}, 'limitations': ['No separate model-quality benchmark was run.', 'Flint capacity TTFT counts reasoning tokens; its old content-only baseline has different channel semantics.', 'Baselines ran for two minutes; new runs lasted 30 minutes. Qwen used a direct sidecar baseline and a stable frontend for the new run. These are not controlled runtime benchmarks.']}
for model in ('qwen', 'flint'):
    api = read(model+'-160-api.json')
    protocols = lines(model+'-160-protocols.jsonl')
    gateway = read(model+'-160-internal-gateway.json')
    overload = read(model+'-160-overload.json')
    load = read(model+'-160-load.json')
    baseline = read(model+'-baseline-load.json')
    public_file = a.evidence/(model+'-160-public-gateway.json')
    public = json.loads(public_file.read_text()) if public_file.exists() else None
    assert load['passed'] and load['requested_seconds'] >= 1800, model+' load incomplete or failed'
    item = {'api_checks': len(api['checks']), 'api_passed': api['passed'], 'protocol_checks': len(protocols), 'protocols_passed': all(row['passed'] for row in protocols), 'internal_gateway_checks': len(gateway['checks']), 'internal_gateway_passed': gateway['passed'], 'overload_passed': overload['passed'], 'load': load, 'baseline': baseline, 'public_gateway_passed': public['passed'] if public else None}
    item['p95_ttft_ratio_to_baseline'] = load['p95_ttft_s']/baseline['p95_ttft_s']
    item['p95_duration_ratio_to_baseline'] = load['p95_duration_s']/baseline['p95_duration_s']
    assert all(item[key] for key in ('api_passed', 'protocols_passed', 'internal_gateway_passed', 'overload_passed')), model+' validation failed'
    report['models'][model] = item
observations = lines('observation.jsonl')
if (a.evidence/'observation-tail.jsonl').exists():
    observations += lines('observation-tail.jsonl')
report['observations'] = {'samples': len(observations), 'errors': [row for row in observations if row['errors']], 'first_utc': observations[0]['utc'], 'last_utc': observations[-1]['utc'], 'max_kv_cache_fraction': {model: max(row['metrics'].get(model, {}).get('vllm:kv_cache_usage_perc', 0) for row in observations) for model in ('qwen', 'flint')}}
assert not report['observations']['errors'], 'Observation errors require review'
report['service_selectors_preserved'] = read('deployed-state.json')['service_selectors_preserved']
assert report['service_selectors_preserved']
report['running_versions'] = read('running-runtime-versions.json')
report['public_unauthenticated'] = read('public-unauthenticated.json')
report['public_authenticated_status'] = 'passed' if all(item['public_gateway_passed'] for item in report['models'].values()) else 'not complete; see public approval status or individual reports'
(a.evidence/'validation-summary.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps({'models': {model: {'requests': item['load']['requests'], 'errors': item['load']['errors'], 'p95_ttft_s': item['load']['p95_ttft_s'], 'p95_duration_s': item['load']['p95_duration_s']} for model,item in report['models'].items()}, 'observations': report['observations']['samples'], 'public_authenticated_status': report['public_authenticated_status']}, indent=2))
