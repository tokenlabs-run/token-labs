#!/usr/bin/env python3
"""Save a live experiment's deployment, pod image IDs, and logs."""
import argparse
import json
from pathlib import Path
import subprocess
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('deployment')
p.add_argument('output', type=Path)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
k = ['kubectl', '--context', 'kubernetes-admin@kubernetes', '-n', 'token-labs']
(a.output / 'deployment.json').write_bytes(subprocess.check_output(k + ['get', 'dgd', a.deployment, '-o', 'json']))
pods = subprocess.check_output(k + ['get', 'pods', '-l', 'app.kubernetes.io/part-of=' + a.deployment, '-o', 'json'])
(a.output / 'pods.json').write_bytes(pods)
for pod in json.loads(pods)['items']:
    name = pod['metadata']['name']
    role = pod['metadata']['labels']['nvidia.com/dynamo-component'].lower()
    (a.output / (role + '.log')).write_bytes(subprocess.check_output(k + ['logs', name]))
