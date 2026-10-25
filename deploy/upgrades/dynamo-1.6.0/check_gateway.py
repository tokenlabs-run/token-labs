#!/usr/bin/env python3
"""Run gateway conformance with a referenced Kubernetes credential kept in memory."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--url', required=True, help='Base URL ending in /v1')
p.add_argument('--model', required=True)
p.add_argument('--output', required=True)
p.add_argument('--overload-limit', type=int)
a = p.parse_args()
if not a.url.rstrip('/').endswith('/v1'):
    p.error('URL must end in /v1')
api_root = a.url.rstrip('/')[:-3]
root = Path(__file__).resolve().parents[3]
secret = json.loads(subprocess.check_output(['kubectl', '--context=kubernetes-admin@kubernetes', '-n', 'token-labs', 'get', 'secret', 'openrouter-provider-auth', '-o', 'json'], timeout=15))
env = dict(os.environ, TOKENLABS_BENCH_API_KEY=base64.b64decode(secret['data']['api-key']).decode())
if a.overload_limit is None:
    cmd = [sys.executable, str(root/'scripts/openrouter/check_api_conformance.py'), '--url', api_root, '--model', a.model, '--output', a.output, '--repetitions', '3', '--tools', '--structured-outputs']
else:
    if a.overload_limit < 1:
        p.error('overload limit must be positive')
    cmd = [sys.executable, str(root/'scripts/openrouter/check_early_429.py'), '--url', a.url.rstrip('/')+'/chat/completions', '--model', a.model, '--output', a.output, '--expected-max-admitted', str(a.overload_limit), '--requests', str(a.overload_limit+8)]
raise SystemExit(subprocess.run(cmd, env=env).returncode)
