#!/usr/bin/env python3
"""Check model identity, native Rust EPP configuration, and route references."""
from pathlib import Path
import yaml
import json

HERE = Path(__file__).resolve().parent


def read(name):
    return yaml.safe_load((HERE / name).read_text())


def main():
    for short in ('qwen', 'muse'):
        old = read(f'inputs/{short}-graph.yaml')
        new = read(f'{short}-graph.yaml')
        assert new['metadata']['name'] == old['metadata']['name'] + '-151-epp'
        epp, worker = new['spec']['components']
        assert epp['type'] == 'epp' and 'eppConfig' not in epp
        assert worker['type'] == 'decode'
        assert worker['frontendSidecar'] == 'sidecar-frontend'
        picker = epp['podTemplate']['spec']['containers'][0]
        assert ':1.5.1@sha256:' in picker['image']
        assert not picker.get('command') and not picker.get('args')
        old_worker = old['spec']['components'][1]['podTemplate']['spec']['containers'][0]
        main_container, sidecar = worker['podTemplate']['spec']['containers']
        assert ':1.5.1@sha256:' in main_container['image']
        assert main_container['args'][:len(old_worker['args'])] == old_worker['args']
        assert '--enable-prefix-caching' in main_container['args']
        block = main_container['args'][main_container['args'].index('--block-size') + 1]
        assert next(e['value'] for e in picker['env'] if e['name'] == 'DYN_KV_CACHE_BLOCK_SIZE') == str(json.loads((HERE / 'effective-kv-block-sizes.json').read_text())[short])
        assert 'dynamo-frontend-nightly@sha256:' in sidecar['image']
        assert sidecar['args'][sidecar['args'].index('--router-mode') + 1] == 'direct'
        route = read(f'{short}-canary-route.yaml')
        assert route['spec']['rules'][0]['backendRefs'][0]['name'] == new['metadata']['name'] + '-pool'
        print(f'{short}: model/revision/runtime flags preserved; Rust EPP and nightly direct sidecar verified')
    for route in yaml.safe_load_all((HERE / 'public-routes.yaml').read_text()):
        refs = [r for rule in route['spec']['rules'] for r in rule['backendRefs'] if r.get('kind') == 'InferencePool']
        assert len(refs) == (2 if route['kind'] == 'AIGatewayRoute' else 0)
    envoy = read('envoy-gateway-values.yaml')['config']['envoyGateway']
    assert {'group': 'inference.networking.k8s.io', 'version': 'v1', 'kind': 'InferencePool'} in envoy['extensionManager']['backendResources']
    assert envoy['extensionManager']['service']['fqdn']['hostname'] == 'ai-gateway-controller.envoy-ai-gateway-system.svc.cluster.local'
    print('public/native routes and preserved AI gateway extension verified')


if __name__ == '__main__':
    main()
