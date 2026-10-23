import copy
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetirementSafety(unittest.TestCase):
    def test_removes_only_epp_rules_and_keeps_unrelated_routes_in_order(self):
        tool = load('disable_qwen_epp')
        def rule(name):
            return {'backendRefs': [{'name': name}], 'matches': [{'headers': [{'name': 'model', 'value': name}]}]}
        route = {'metadata': {'name': 'models', 'resourceVersion': '7'}, 'spec': {'rules': [
            rule('flint-admission-gateway'), rule(tool.POOL), rule('qwen3-6-35b-a3b-nvfp4'),
            rule(tool.POOL), rule('muse-glimmer-30b')]}}
        canary = {'metadata': {'name': 'canary', 'resourceVersion': '8'}, 'spec': {'rules': [rule(tool.POOL)]}}
        original = copy.deepcopy(route)
        operations = tool.plan(route, canary)
        self.assertEqual([kind for kind, _, _ in operations], ['aigatewayroute', 'httproute'])
        remaining = copy.deepcopy(route['spec']['rules'])
        for operation in operations[0][2]:
            if operation['op'] == 'remove':
                remaining.pop(int(operation['path'].rsplit('/', 1)[1]))
        self.assertEqual(remaining, [original['spec']['rules'][i] for i in [0, 2, 4]])
        self.assertEqual(route, original)
        self.assertEqual(operations[1][2][-1]['value'], [{'name': tool.STABLE, 'port': 8000, 'weight': 1}])

    def test_health_candidate_does_not_modify_serving_graph_or_other_worker_settings(self):
        tool = load('prepare_qwen_health_candidate')
        worker = {'name': 'VllmWorker', 'type': 'decode', 'replicas': 1,
                  'podTemplate': {'spec': {'nodeSelector': {'kubernetes.io/hostname': 'spark-02'},
                      'containers': [{'name': 'main', 'image': 'pinned-worker', 'args': ['--max-num-seqs', '4'],
                          'env': [{'name': 'OTHER', 'value': 'preserve'},
                                  {'name': 'DYN_HEALTH_CHECK_ENABLED', 'value': 'true'}]}]}}}
        active = {'apiVersion': 'nvidia.com/v1beta1', 'spec': {'backendFramework': 'vllm',
                   'components': [{'name': 'Epp', 'type': 'epp'}, worker]}}
        old = {'spec': {'components': [{'name': 'Frontend', 'type': 'frontend', 'replicas': 1}]}}
        untouched = copy.deepcopy(active)
        candidate = tool.build(active, old, 'independent-gpu')
        self.assertEqual(active, untouched)
        self.assertEqual(candidate['metadata']['namespace'], 'qwen36-health-validation')
        self.assertEqual([c['name'] for c in candidate['spec']['components']], ['Frontend', 'VllmWorker'])
        changed = candidate['spec']['components'][1]
        expected = copy.deepcopy(worker)
        expected['podTemplate']['spec']['nodeSelector']['kubernetes.io/hostname'] = 'independent-gpu'
        expected['podTemplate']['spec']['containers'][0]['env'][1]['value'] = 'false'
        self.assertEqual(changed, expected)


if __name__ == '__main__':
    unittest.main()
