import json
import pathlib
import sys
import unittest


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import check_api_conformance as conformance  # noqa: E402


def valid_body(**overrides):
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "qwen/qwen3-30b-a3b-instruct-2507",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "ready"},
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
    }
    body.update(overrides)
    return body


class FakeResponse:
    def __init__(self, *, status=200, body=None, lines=(), content_type="application/json"):
        self.status_code = status
        self._body = body
        self._lines = list(lines)
        self.headers = {"content-type": content_type}

    def json(self):
        return self._body

    def iter_lines(self, decode_unicode=False):
        del decode_unicode
        yield from self._lines


class FakeSession:
    def __init__(self, response):
        self.response = response

    def post(self, *args, **kwargs):
        del args, kwargs
        return self.response

    def request(self, *args, **kwargs):
        del args, kwargs
        return self.response


class ConformanceValidationTests(unittest.TestCase):
    def test_provider_catalog_requires_ready_complete_model(self):
        model = "qwen/qwen3-30b-a3b-instruct-2507"
        document = {
            "schema_version": "2.4", "id": model, "name": "Qwen", "created": 1,
            "hugging_face_id": "Qwen/Qwen3-30B-A3B-Instruct-2507",
            "is_ready": True, "openrouter": {"slug": model},
            "input_modalities": [{"type": "text", "pricing": [{}], "capacity": [{}]}],
            "output_modalities": [{"type": "text", "streaming": True,
                                   "pricing": [{}], "capacity": [{}]}],
            "capacity": [{"type": "request"}, {"type": "concurrency"}],
            "datacenters": [{"country_code": "US"}], "deployment_region": "US",
            "compliance": {"zdr": False, "hipaa": False},
        }
        result = conformance.check_provider_catalog({
            "session": FakeSession(FakeResponse(body={"data": [document]})),
            "provider_models_url": "https://example.test/models",
            "model": model, "timeout": 1,
        })
        self.assertTrue(result["is_ready"])

    def test_provider_catalog_rejects_not_ready(self):
        model = "qwen/qwen3-30b-a3b-instruct-2507"
        response = FakeResponse(body={"data": [{
            "schema_version": "2.4", "id": model, "is_ready": False
        }]})
        with self.assertRaisesRegex(conformance.CheckFailure, "not ready"):
            conformance.check_provider_catalog({
                "session": FakeSession(response),
                "provider_models_url": "https://example.test/models",
                "model": model, "timeout": 1,
            })

    def test_valid_usage(self):
        self.assertEqual(
            conformance.validate_usage(
                {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
            ),
            {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        )

    def test_inconsistent_usage_fails(self):
        with self.assertRaisesRegex(conformance.CheckFailure, "inconsistent"):
            conformance.validate_usage(
                {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 6}
            )

    def test_error_finish_reason_fails(self):
        body = valid_body()
        body["choices"][0]["finish_reason"] = "error"
        with self.assertRaisesRegex(conformance.CheckFailure, "finish_reason"):
            conformance.validate_chat_response(body, body["model"])

    def test_valid_stream_with_usage_and_done(self):
        event = {
            "choices": [{"index": 0, "delta": {"content": "ready"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        }
        response = FakeResponse(
            lines=(f"data: {json.dumps(event)}", "data: [DONE]"),
            content_type="text/event-stream; charset=utf-8",
        )
        result = conformance.check_stream(
            {
                "session": FakeSession(response),
                "url": "https://example.test",
                "model": "qwen/qwen3-30b-a3b-instruct-2507",
                "timeout": 1,
            }
        )
        self.assertEqual(result["json_chunks"], 1)
        self.assertEqual(result["usage"]["total_tokens"], 5)

    def test_truncated_stream_fails(self):
        event = {"choices": [{"index": 0, "delta": {"content": "partial"}}]}
        response = FakeResponse(
            lines=(f"data: {json.dumps(event)}",),
            content_type="text/event-stream",
        )
        with self.assertRaisesRegex(conformance.CheckFailure, r"\[DONE\]"):
            conformance.check_stream(
                {
                    "session": FakeSession(response),
                    "url": "https://example.test",
                    "model": "qwen/qwen3-30b-a3b-instruct-2507",
                    "timeout": 1,
                }
            )

    def test_stream_error_object_fails(self):
        response = FakeResponse(
            lines=(
                'data: {"error":{"message":"worker lost"},"choices":[]}',
                "data: [DONE]",
            ),
            content_type="text/event-stream",
        )
        with self.assertRaisesRegex(conformance.CheckFailure, "error object"):
            conformance.check_stream(
                {
                    "session": FakeSession(response),
                    "url": "https://example.test",
                    "model": "qwen/qwen3-30b-a3b-instruct-2507",
                    "timeout": 1,
                }
            )


if __name__ == "__main__":
    unittest.main()
