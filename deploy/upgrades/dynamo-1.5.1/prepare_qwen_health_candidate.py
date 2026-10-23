#!/usr/bin/env python3
"""Prepare an isolated, EPP-free graph. Never modifies the serving graph."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import yaml


def build(active, old, spare_node):
    worker = deepcopy(next(c for c in active['spec']['components'] if c['name'] == 'VllmWorker'))
    frontend = deepcopy(next(c for c in old['spec']['components'] if c['name'] == 'Frontend'))
    # Verified from ai-dynamo-runtime metadata in the pinned old frontend image.
    frontend['runtimeVersionOverride'] = '1.6.0'
    main = next(c for c in worker['podTemplate']['spec']['containers'] if c['name'] == 'main')
    env = main.setdefault('env', [])
    env[:] = [e for e in env if e['name'] != 'DYN_HEALTH_CHECK_ENABLED']
    env.append({'name': 'DYN_HEALTH_CHECK_ENABLED', 'value': 'false'})
    worker['podTemplate']['spec']['nodeSelector']['kubernetes.io/hostname'] = spare_node
    # A separate Kubernetes namespace prevents production discovery from seeing
    # a same-model candidate before deliberate routing cutover.
    return {'apiVersion': active['apiVersion'], 'kind': 'DynamoGraphDeployment',
            'metadata': {'name': 'qwen36-nvfp4-health-candidate', 'namespace': 'qwen36-health-validation',
                         'annotations': {'token-labs/status': 'prepared-only-requires-independent-gpu'}},
            'spec': {'backendFramework': active['spec']['backendFramework'],
                     'components': [frontend, worker]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--active-snapshot', required=True, type=Path)
    parser.add_argument('--old-snapshot', required=True, type=Path)
    parser.add_argument('--spare-node', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.spare_node in ['spark-01', 'spark-02']:
        parser.error('Both production Spark nodes are occupied; provide separate capacity')
    candidate = build(json.loads(args.active_snapshot.read_text()),
                      json.loads(args.old_snapshot.read_text()), args.spare_node)
    args.output.write_text('# Prepared only. No production cutover or apply has been performed.\n' +
                           yaml.safe_dump(candidate, sort_keys=False))
    print(args.output)


if __name__ == '__main__':
    main()
