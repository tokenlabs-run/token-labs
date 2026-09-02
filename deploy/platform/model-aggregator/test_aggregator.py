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

    def test_provider_document_is_fail_closed_and_live_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            old_path = a.PROVIDER_DOCUMENT_PATH
            a.PROVIDER_DOCUMENT_PATH = Path(directory) / 'models.json'
            self.assertIsNone(a.provider_document())
            a.PROVIDER_DOCUMENT_PATH.write_text(json.dumps({'data': [{
                'schema_version': '2.4', 'id': 'model', 'is_ready': True
            }]}))
            a._model_backends = {}
            self.assertFalse(a.provider_document()['data'][0]['is_ready'])
            a._model_backends = {'model': 'http://backend'}
            self.assertTrue(a.provider_document()['data'][0]['is_ready'])
            a.PROVIDER_DOCUMENT_PATH = old_path

    async def test_admission_rejects_without_queueing(self):
        old_limit = a.OPENROUTER_CONCURRENCY
        a.OPENROUTER_CONCURRENCY = 1
        a._inflight = 0
        self.assertTrue(await a.admit())
        self.assertFalse(await a.admit())
        self.assertEqual(a._inflight, 1)
        await a.release()
        self.assertEqual(a._inflight, 0)
        a.OPENROUTER_CONCURRENCY = old_limit

    def test_provider_bearer_authentication(self):
        old_key = a.OPENROUTER_API_KEY
        a.OPENROUTER_API_KEY = 'test-secret'
        self.assertTrue(a.provider_authorized('Bearer test-secret'))
        self.assertTrue(a.provider_authorized('bearer test-secret'))
        self.assertFalse(a.provider_authorized('Bearer wrong'))
        self.assertFalse(a.provider_authorized('Basic test-secret'))
        self.assertFalse(a.provider_authorized(None))
        a.OPENROUTER_API_KEY = old_key


if __name__ == '__main__':
    unittest.main()
