import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import catalog


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(Path(__file__).with_name("models.json").read_text())
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), catalog.handler(
            cls.document, hashlib.sha256(b"test-key").hexdigest()))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def get(self, path="/codex/models?client_version=0.164.0", key="test-key"):
        headers = {} if key is None else {"Authorization": f"Bearer {key}"}
        try:
            response = urlopen(Request(self.url + path, headers=headers), timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers

    def test_missing_and_wrong_credentials_rejected_before_discovery(self):
        with patch.object(catalog, "ready_catalog") as discover:
            for key in (None, "wrong"):
                status, _, headers = self.get(key=key)
                self.assertEqual(status, 401)
                self.assertEqual(headers["WWW-Authenticate"], "Bearer")
            discover.assert_not_called()

    def test_missing_server_credential_fails_closed(self):
        self.assertFalse(catalog.authorized("Bearer test-key", ""))

    def test_only_ready_models_listed_with_live_context(self):
        with patch.object(catalog, "live_model", side_effect=lambda model, url:
                          (model, 65536 if model.startswith("nvidia/") else None)):
            status, body, headers = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(len(body["models"]), 1)
        self.assertEqual(body["models"][0]["context_window"], 65536)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_all_backends_unavailable_returns_503(self):
        with patch.object(catalog, "live_model", side_effect=lambda model, url: (model, None)):
            self.assertEqual(self.get()[0], 503)

    def test_invalid_version_rejected(self):
        with patch.object(catalog, "ready_catalog") as discover:
            self.assertEqual(self.get("/codex/models?client_version=invalid")[0], 400)
            discover.assert_not_called()

    def test_health_and_unknown_paths(self):
        self.assertEqual(self.get("/health", key=None)[0], 200)
        self.assertEqual(self.get("/unknown", key=None)[0], 404)

    def test_no_credential_forwarding(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"data":[{"id":"test","context_window":128}]}'
        with patch.object(catalog, "build_opener") as opener:
            opener.return_value.open.return_value = Response()
            self.assertEqual(catalog.live_model("test", "http://backend/v1/models"), ("test",128))
            opener.return_value.open.assert_called_once_with("http://backend/v1/models", timeout=3)


if __name__ == "__main__":
    unittest.main()
