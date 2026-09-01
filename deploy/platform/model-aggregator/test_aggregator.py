import json
from pathlib import Path
import tempfile
import unittest
import httpx
import aggregator as a


def service(name, selector, labels=None):
    return {'metadata': {'name': name, 'namespace': 'token-labs', 'labels': labels or {}},
            'spec': {'selector': selector, 'ports': [{'name': 'http', 'port': 8000}]}}


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_changes_failures_and_credentials(self):
        services = [service('one', {'llm-d.ai/inference-serving': 'true', 'llm-d.ai/role': 'decode'}),
                    service('two', {'nvidia.com/dynamo-component-type': 'frontend'}),
                    service('worker', {'nvidia.com/dynamo-component-type': 'worker'})]
        responses = {'one': {'data': [{'id': 'actual-model'}, {'id': None}]},
                     'two': {'data': [{'id': 'actual-model'}, {'id': 'second-model'}]}}
        api_failed = False
        def kube(request):
            self.assertEqual(request.headers['authorization'], 'Bearer test-token')
            return httpx.Response(503 if api_failed else 200, json={'items': services})
        def backend(request):
            self.assertNotIn('authorization', request.headers)
            name = request.url.host.split('.')[0]
            self.assertNotEqual(name, 'worker')
            if name not in responses:
                raise httpx.ConnectError('unavailable')
            return httpx.Response(200, json=responses[name])
        with tempfile.TemporaryDirectory() as directory:
            old_path = a.SA_PATH
            a.SA_PATH = Path(directory)
            (a.SA_PATH / 'token').write_text('test-token')
            a._namespace = 'token-labs'
            async with httpx.AsyncClient(transport=httpx.MockTransport(kube), base_url='https://kube') as k, \
                    httpx.AsyncClient(transport=httpx.MockTransport(backend)) as b:
                a._kube_client, a._http_client = k, b
                await a.refresh_cache()
                self.assertEqual([m['id'] for m in a._cache], ['actual-model', 'second-model'])
                del responses['two']
                await a.refresh_cache()
                self.assertEqual([m['id'] for m in a._cache], ['actual-model'])
                services.clear()
                await a.refresh_cache()
                self.assertEqual(json.loads((await a.list_models()).body)['data'], [])
                services.append(service('new', {'app': 'vllm'}, {'token-labs/model': 'true'}))
                responses['new'] = {'data': [{'id': 'new-model'}]}
                await a.refresh_cache()
                self.assertEqual(a._cache[0]['id'], 'new-model')
                api_failed = True
                await a.refresh_cache()
                self.assertEqual((await a.list_models()).status_code, 503)
                self.assertEqual(a._cache, [])
            a.SA_PATH = old_path

    def test_service_selection(self):
        self.assertIsNone(a.service_url(service('prefill', {'llm-d.ai/inference-serving': 'true', 'llm-d.ai/role': 'prefill'})))
        self.assertIsNone(a.service_url(service('unrelated', {'app': 'web'})))
        candidate = service('external', {'app': 'vllm'}, {'token-labs/model': 'true'})
        candidate['spec']['type'] = 'ExternalName'
        self.assertIsNone(a.service_url(candidate))


if __name__ == '__main__':
    unittest.main()
