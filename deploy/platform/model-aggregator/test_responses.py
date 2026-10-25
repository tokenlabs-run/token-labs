"""Responses proxy contract, stream lifecycle, and shared admission regressions."""
import asyncio
import json
import unittest
from unittest.mock import patch

import httpx
import aggregator as a

MODEL = 'nvidia/Qwen3.8-27B-NVFP4'
PAYLOAD = {
    'model': MODEL, 'input': [
        {'type': 'function_call', 'call_id': 'call_1', 'name': 'lookup', 'arguments': '{}'},
        {'type': 'function_call_output', 'call_id': 'call_1', 'output': '42'},
    ],
    'tools': [{'type': 'namespace', 'name': 'functions', 'tools': [
        {'type': 'function', 'name': 'lookup', 'parameters': {'type': 'object'}}]}],
    'tool_choice': 'auto', 'store': False, 'reasoning': {'effort': 'medium'},
}


def request(payload):
    async def receive():
        return {'type': 'http.request', 'body': json.dumps(payload).encode(), 'more_body': False}
    return a.Request({'type': 'http', 'method': 'POST', 'path': '/v1/responses',
                      'headers': [(b'authorization', b'Bearer customer-key')]}, receive)


class ResponsesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = patch.multiple(a, _model_backends={MODEL: 'http://backend'},
                                    _inflight=0, _model_inflight={},
                                    MODEL_CONCURRENCY_LIMITS={MODEL: 1})
        self.state.start()
        self.addCleanup(self.state.stop)

    async def test_registered_route_preserves_payload_and_native_result(self):
        result = {'id': 'resp_1', 'status': 'completed', 'output': [], 'usage': {'total_tokens': 7}}

        def backend(req):
            self.assertEqual(str(req.url), 'http://backend/v1/responses')
            self.assertEqual(json.loads(req.content), PAYLOAD)
            self.assertNotIn('authorization', req.headers)
            return httpx.Response(200, json=result)

        async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as upstream, \
                httpx.AsyncClient(transport=httpx.ASGITransport(app=a.app), base_url='http://test') as client:
            with patch.object(a, '_http_client', upstream):
                response = await client.post('/v1/responses', json=PAYLOAD)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        self.assertEqual(a._inflight, 0)

    async def test_native_stream_bytes_and_capacity_released_on_disconnect(self):
        chunks = [b'event: response.output_item.added\ndata: {"type":"response.output_item.added"}\n\n',
                  b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n']

        class Stream(httpx.AsyncByteStream):
            closed = False
            async def __aiter__(self):
                for chunk in chunks:
                    yield chunk
            async def aclose(self):
                self.closed = True

        for disconnect in (False, True):
            stream = Stream()
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda req: httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                              stream=stream))) as upstream:
                with patch.object(a, '_http_client', upstream):
                    response = await a.direct_responses(request({**PAYLOAD, 'stream': True}))
                    self.assertFalse(await a.admit(MODEL))
                    self.assertEqual(response.headers['content-type'], 'text/event-stream; charset=utf-8')
                    if disconnect:
                        self.assertEqual(await anext(response.body_iterator), chunks[0])
                        await response.body_iterator.aclose()
                    else:
                        self.assertEqual([c async for c in response.body_iterator], chunks)
            self.assertTrue(stream.closed)
            self.assertEqual(a._inflight, 0)
            self.assertEqual(a._model_inflight, {})

    async def test_upstream_error_status_and_body_are_preserved(self):
        error = {'error': {'message': 'Unsupported tool', 'type': 'invalid_request_error'}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda req: httpx.Response(400, json=error))) as upstream:
            with patch.object(a, '_http_client', upstream):
                response = await a.direct_responses(request(PAYLOAD))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body), error)
        self.assertEqual(a._inflight, 0)

    async def test_bad_model_unknown_model_and_overload_do_not_reach_backend(self):
        for model in (None, [], {}):
            response = await a.direct_responses(request({'model': model}))
            self.assertEqual(response.status_code, 400)
        self.assertEqual((await a.direct_responses(request({'model': 'missing'}))).status_code, 404)
        self.assertTrue(await a.admit(MODEL))
        try:
            response = await a.direct_responses(request(PAYLOAD))
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers['retry-after'], '1')
        finally:
            await a.release(MODEL)

    async def test_chat_and_responses_share_the_same_model_limit(self):
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"type":"response.created"}\n\n'

        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda req: httpx.Response(200, stream=Stream()))) as upstream:
            with patch.object(a, '_http_client', upstream):
                response = await a.direct_responses(request({**PAYLOAD, 'stream': True}))
                await anext(response.body_iterator)
                chat = await a.direct_chat_completions(request({'model': MODEL, 'messages': []}))
                self.assertEqual(chat.status_code, 429)
                await response.body_iterator.aclose()
                self.assertEqual(a._model_inflight, {})

    async def test_connection_failure_and_cancellation_release_capacity(self):
        for failure in (httpx.ConnectError('offline'), asyncio.CancelledError()):
            async def backend(req):
                raise failure
            async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as upstream:
                with patch.object(a, '_http_client', upstream):
                    if isinstance(failure, asyncio.CancelledError):
                        with self.assertRaises(asyncio.CancelledError):
                            await a.direct_responses(request(PAYLOAD))
                    else:
                        self.assertEqual((await a.direct_responses(request(PAYLOAD))).status_code, 502)
            self.assertEqual(a._inflight, 0)
            self.assertEqual(a._model_inflight, {})


if __name__ == '__main__':
    unittest.main()
