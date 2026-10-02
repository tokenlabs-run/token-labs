#!/usr/bin/env python3
"""Test the actual hardware PrometheusRule with a local promtool (PyYAML required)."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import yaml

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--promtool', default='promtool')
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
hardware = root / 'deploy/platform/monitoring/hardware'
rules = yaml.safe_load((hardware / 'gpu-health-alerts.yaml').read_text())
with tempfile.TemporaryDirectory(prefix='token-labs-hardware-') as directory:
    dest = Path(directory)
    (dest / 'rules.yaml').write_text(yaml.safe_dump(rules['spec']))
    shutil.copyfile(hardware / 'rules.test.yaml', dest / 'rules.test.yaml')
    subprocess.run([args.promtool, 'check', 'rules', str(dest / 'rules.yaml')], check=True)
    subprocess.run([args.promtool, 'test', 'rules', str(dest / 'rules.test.yaml')], check=True)
for bundle in ['deploy/platform/monitoring', 'deploy/platform/observability']:
    subprocess.run(['kubectl', 'kustomize', str(root / bundle)], check=True, stdout=subprocess.DEVNULL)
print('PASS: alert behavior and both parent Kustomize bundles')
