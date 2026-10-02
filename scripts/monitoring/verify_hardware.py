#!/usr/bin/env python3
"""Read-only verification of the Token Labs hardware telemetry path.

Requires kubectl access, PyYAML, and local port forwards to Prometheus/Grafana.
Grafana credentials are read into memory from its existing Kubernetes Secret;
credentials, tenant data, prompts and logs are never written to the evidence.
"""
import argparse
import base64
import datetime
import json
import re
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request


def kube(*args):
    return json.loads(subprocess.check_output(['kubectl', *args, '-o', 'json']))


def get(base, path, headers=None):
    with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers or {}), timeout=20) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prometheus', default='http://127.0.0.1:19090')
    parser.add_argument('--grafana', default='http://127.0.0.1:13000')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = {'captured_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    targets = get(args.prometheus, '/api/v1/targets')['data']['activeTargets']
    gpu = [t for t in targets if t['labels'].get('job') == 'nvidia-dcgm-exporter']
    assert len(gpu) == 2 and {t['labels'].get('node') for t in gpu} == {'spark-01', 'spark-02'}, gpu
    assert all(t['health'] == 'up' for t in gpu), gpu
    result['dcgm_targets'] = [{'labels': t['labels'], 'health': t['health'], 'lastScrape': t['lastScrape']} for t in gpu]
    result['raw_gpu_samples'] = {}
    for pod in kube('get', 'pods', '-n', 'gpu-operator', '-l', 'app=nvidia-dcgm-exporter')['items']:
        name, node = pod['metadata']['name'], pod['spec']['nodeName']
        raw = subprocess.check_output(['kubectl', 'get', '--raw', f'/api/v1/namespaces/gpu-operator/pods/{name}:9400/proxy/metrics'], text=True)
        gpu_samples = [line for line in raw.splitlines() if line.startswith('DCGM_FI_')]
        assert gpu_samples, (node, 'no GPU samples')
        # Exporter releases have used both Hostname and hostname.
        for sample in gpu_samples:
            hostname = re.search(r'(?:Hostname|hostname)="([^"]+)"', sample)
            assert hostname and hostname.group(1) == node, (node, sample)
        (args.output / f'{node}.metrics').write_text(raw)
        result['raw_gpu_samples'][node] = {s.split('{', 1)[0]: s.rsplit(' ', 1)[1] for s in raw.splitlines() if s and not s.startswith('#')}
    groups = get(args.prometheus, '/api/v1/rules')['data']['groups']
    groups = [g for g in groups if g['name'].startswith('token-labs.hardware.')]
    assert len(groups) == 2, groups
    assert all(r['health'] == 'ok' for g in groups for r in g['rules']), groups
    result['rules'] = [{'group': g['name'], 'rules': [{'name': r['name'], 'health': r['health'], 'state': r.get('state')} for r in g['rules']]} for g in groups]
    secret = kube('get', 'secret', 'grafana-admin-secret', '-n', 'monitoring')['data']
    credentials = base64.b64decode(secret['admin-user']) + b':' + base64.b64decode(secret['admin-password'])
    headers = {'Authorization': 'Basic ' + base64.b64encode(credentials).decode()}
    dashboard = get(args.grafana, '/api/dashboards/uid/token-labs-hardware', headers)
    assert dashboard['meta']['provisioned'], dashboard['meta']
    result['dashboard'] = {'uid': dashboard['dashboard']['uid'], 'provisioned': True, 'url': dashboard['meta']['url']}
    result['panel_queries'] = []
    for panel in dashboard['dashboard']['panels']:
        for target in panel.get('targets', []):
            query = target['expr']
            response = get(args.grafana, '/api/datasources/proxy/uid/prometheus/api/v1/query?' + urllib.parse.urlencode({'query': query}), headers)
            assert response['status'] == 'success', response
            samples = response['data']['result']
            # An inactive alert legitimately has no series. Hardware panels must
            # return both expected nodes; zero-filling is only for scrape status.
            if not query.startswith('ALERTS'):
                assert {s['metric'].get('node') for s in samples} == {'spark-01', 'spark-02'}, (query, samples)
            result['panel_queries'].append({'title': panel['title'], 'query': query, 'samples': samples})
    (args.output / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f"PASS: two exporters, {sum(len(g['rules']) for g in groups)} rules, provisioned dashboard and {len(result['panel_queries'])} Grafana datasource queries")


if __name__ == '__main__':
    main()
