#!/usr/bin/env python3
"""Record DGX readiness, restarts, node pressure, and runtime metrics during load."""
import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request

p = argparse.ArgumentParser()
p.add_argument('--seconds', type=int, default=1800)
p.add_argument('--interval', type=int, default=45)
p.add_argument('--output', required=True, type=Path)
a = p.parse_args()
if a.seconds <= 0 or not 1 <= a.interval <= 45:
    p.error('Require positive seconds and an interval from 1 to 45 seconds')
metrics = {'qwen': 'http://10.104.158.112:9090/metrics', 'flint': 'http://10.97.29.248:8000/metrics'}
selectors = ['nvidia.com/dynamo-component=VllmWorker', 'app=flint-nvfp4-vllm-green', 'token-labs/model-id=qwen36-nvfp4-frontend,token-labs/slot=blue']
k = ['kubectl', '--context=kubernetes-admin@kubernetes']
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
a.output.parent.mkdir(parents=True, exist_ok=True)
start = time.monotonic()
while True:
    row = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'elapsed_s': round(time.monotonic()-start, 1), 'pods': [], 'nodes': {}, 'metrics': {}, 'errors': []}
    try:
        for selector in selectors:
            pods = json.loads(subprocess.check_output(k+['-n', 'token-labs', 'get', 'pods', '-l', selector, '-o', 'json'], timeout=15))['items']
            active = [pod for pod in pods if pod['status']['phase'] not in ('Succeeded', 'Failed') and not pod['metadata'].get('deletionTimestamp')]
            if len(active) != 1:
                row['errors'].append(f'{selector}: expected one active pod, got {len(active)}')
            for pod in active:
                states = pod['status'].get('containerStatuses', [])
                item = {'name': pod['metadata']['name'], 'containers': [{'name': s['name'], 'ready': s['ready'], 'restarts': s['restartCount'], 'image_id': s.get('imageID')} for s in states]}
                row['pods'].append(item)
                if len(states) != len(pod['spec']['containers']) or not all(s['ready'] and s['restartCount'] == 0 for s in states):
                    row['errors'].append(f'{item["name"]}: not ready or restarted')
        nodes = json.loads(subprocess.check_output(k+['get', 'nodes', 'spark-01', 'spark-02', '-o', 'json'], timeout=15))['items']
        for node in nodes:
            conditions = {c['type']: c['status'] for c in node['status']['conditions']}
            row['nodes'][node['metadata']['name']] = conditions
            if conditions.get('Ready') != 'True' or any(conditions.get(c) != 'False' for c in ('MemoryPressure', 'DiskPressure', 'PIDPressure')):
                row['errors'].append(f'{node["metadata"]["name"]}: unhealthy node conditions')
        for model, url in metrics.items():
            with http.open(url, timeout=10) as response:
                body = response.read().decode()
            values = {}
            for line in body.splitlines():
                if line.startswith('#') or not line.strip():
                    continue
                match = re.match(r'([^ {]+)(?:\{.*\})?\s+([^ ]+)', line)
                if match and match[1] in ('vllm:num_requests_running', 'vllm:num_requests_waiting', 'vllm:kv_cache_usage_perc', 'dynamo_component_gpu_cache_usage_percent'):
                    values[match[1]] = max(values.get(match[1], 0), float(match[2]))
            row['metrics'][model] = values
            if not values:
                row['errors'].append(f'{model}: missing engine metrics')
            if values.get('vllm:kv_cache_usage_perc', 0) >= .9:
                row['errors'].append(f'{model}: KV cache at or above 90%')
    except Exception as exc:
        row['errors'].append(str(exc))
    with a.output.open('a') as f:
        f.write(json.dumps(row)+'\n')
    print(json.dumps({'elapsed_s': row['elapsed_s'], 'metrics': row['metrics'], 'errors': row['errors']}), flush=True)
    remaining = a.seconds-(time.monotonic()-start)
    if remaining <= 0:
        break
    time.sleep(min(a.interval, remaining))
