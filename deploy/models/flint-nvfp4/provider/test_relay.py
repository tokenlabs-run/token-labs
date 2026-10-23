import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

with patch.dict(os.environ, {'FLINT_PROVIDER_BASE': 'https://provider.test/openrouter/v1',
                             'FLINT_PROVIDER_KEY': 'provider-test-key'}):
    spec = importlib.util.spec_from_file_location('flint_relay', Path(__file__).with_name('relay.py'))
    relay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(relay)


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwarding_uses_provider_key_and_preserves_usage(self):
        def upstream(request):
            self.assertEqual(request.headers['authorization'], 'Bearer provider-test-key')
            self.assertEqual(json.loads(request.content)['model'], 'RecursiveSI/flint')
            return httpx.Response(200, json={'choices': [], 'usage': {'total_tokens': 3}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as backend:
            relay.app.state.client = backend
            async with httpx.AsyncClient(transport=httpx.ASGITransport(relay.app), base_url='http://relay') as client:
                response = await client.post('/v1/chat/completions',
                    headers={'authorization': 'Bearer portal-user-key'},
                    json={'model': 'RecursiveSI/flint', 'messages': []})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['usage']['total_tokens'], 3)

    async def test_readiness_requires_exact_flint_identity(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'data': [{'id': 'qwen'}]}))) as backend:
            relay.app.state.client = backend
            async with httpx.AsyncClient(transport=httpx.ASGITransport(relay.app), base_url='http://relay') as client:
                self.assertEqual((await client.get('/healthz')).status_code, 503)

    async def test_overload_propagates_retry_after(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, json={'error': 'busy'}, headers={'Retry-After': '1'}))) as backend:
            relay.app.state.client = backend
            async with httpx.AsyncClient(transport=httpx.ASGITransport(relay.app), base_url='http://relay') as client:
                response = await client.post('/v1/chat/completions', json={'model': 'RecursiveSI/flint'})
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.headers['retry-after'], '1')

    async def test_unknown_model_never_reaches_provider(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(relay.app), base_url='http://relay') as client:
            self.assertEqual((await client.post('/v1/chat/completions', json={'model': 'qwen'})).status_code, 404)

    async def test_stream_preserves_events_usage_and_closes_upstream(self):
        events = b'data: {"choices":[],"usage":{"total_tokens":3}}\n\ndata: [DONE]\n\n'

        class Stream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                yield events[:20]
                yield events[20:]

            async def aclose(self):
                self.closed = True

        stream = Stream()
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=stream,
                headers={'Content-Type': 'text/event-stream'}))) as backend:
            relay.app.state.client = backend
            async with httpx.AsyncClient(transport=httpx.ASGITransport(relay.app), base_url='http://relay') as client:
                response = await client.post('/v1/chat/completions',
                    json={'model': 'RecursiveSI/flint', 'stream': True})
                self.assertEqual(response.content, events)
                self.assertTrue(stream.closed)


if __name__ == '__main__':
    unittest.main()
