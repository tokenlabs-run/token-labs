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

    def test_provider_document_is_static_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            old_path = a.PROVIDER_DOCUMENT_PATH
            a.PROVIDER_DOCUMENT_PATH = Path(directory) / 'models.json'
            self.assertIsNone(a.provider_document())
            a.PROVIDER_DOCUMENT_PATH.write_text(json.dumps({'data': [{
                'schema_version': '2.4', 'id': 'model', 'is_ready': True
            }]}))
            a._model_backends = {}
            self.assertTrue(a.provider_document()['data'][0]['is_ready'])
            self.assertEqual(a.provider_document()['data'][0]['id'], 'model')
            a.PROVIDER_DOCUMENT_PATH = old_path

    async def test_openrouter_model_list_returns_provider_document(self):
        with tempfile.TemporaryDirectory() as directory:
            old_path = a.PROVIDER_DOCUMENT_PATH
            a.PROVIDER_DOCUMENT_PATH = Path(directory) / 'models.json'
            a.PROVIDER_DOCUMENT_PATH.write_text(json.dumps({'data': [{
                'schema_version': '2.4', 'id': 'model', 'is_ready': True
            }]}))
            a._model_backends = {'model': 'http://backend'}
            response = await a.list_openrouter_models()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            body = json.loads(response.body)
            self.assertEqual(body['data'][0]['id'], 'model')
            self.assertTrue(body['data'][0]['is_ready'])
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

    async def test_direct_chat_uses_advertised_model_backend(self):
        old_client = a._http_client
        old_backends = a._model_backends
        old_inflight = a._inflight
        body = json.dumps({
            'model': 'advertised-model',
            'messages': [{'role': 'user', 'content': 'ping'}],
            'max_tokens': 1,
        }).encode()

        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}

        def backend(request):
            self.assertEqual(str(request.url),
                             'http://backend/v1/chat/completions')
            self.assertNotIn('authorization', request.headers)
            return httpx.Response(200, json={
                'id': 'completion',
                'choices': [{'message': {'role': 'assistant',
                                         'content': 'ok'}}],
            })

        request = a.Request({
            'type': 'http',
            'method': 'POST',
            'path': '/v1/chat/completions',
            'headers': [(b'authorization', b'Bearer customer-key'),
                        (b'content-type', b'application/json')],
        }, receive)
        try:
            a._model_backends = {'advertised-model': 'http://backend'}
            a._inflight = 0
            async with httpx.AsyncClient(
                    transport=httpx.MockTransport(backend)) as client:
                a._http_client = client
                response = await a.direct_chat_completions(request)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.body)['id'], 'completion')
            self.assertEqual(a._inflight, 0)
        finally:
            a._http_client = old_client
            a._model_backends = old_backends
            a._inflight = old_inflight

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
