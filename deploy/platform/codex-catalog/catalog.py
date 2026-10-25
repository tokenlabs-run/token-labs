"""Authenticated Codex catalog, isolated from production inference deployments."""
import hashlib
import hmac
import json
import os
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import build_opener, ProxyHandler

MODEL_BACKENDS = {
    "nvidia/Qwen3.6-35B-A3B-NVFP4": "http://qwen36-nvfp4-frontend:8000/v1/models",
    "RecursiveSI/flint": "http://flint-nvfp4:8000/v1/models",
}


def live_model(model, url):
    # Never forward the caller's credential to model servers, or use proxy env vars.
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=3) as response:
            document = json.load(response)
        for entry in document["data"]:
            context = entry.get("context_window", entry.get("max_model_len"))
            if entry.get("id") == model and type(context) is int and context > 0:
                return model, context
    except (URLError, OSError, ValueError, KeyError, TypeError):
        pass
    return model, None


def ready_catalog(document):
    with ThreadPoolExecutor(max_workers=len(MODEL_BACKENDS)) as pool:
        contexts = dict(pool.map(lambda item: live_model(*item), MODEL_BACKENDS.items()))
    models = []
    for entry in document["models"]:
        context = contexts.get(entry["slug"])
        if context is not None:
            models.append({**entry, "context_window": context, "max_context_window": context})
    return {"models": models}


def authorized(header, digest):
    scheme, _, token = (header or "").partition(" ")
    return bool(digest and token and scheme.lower() == "bearer" and hmac.compare_digest(
        hashlib.sha256(token.encode()).hexdigest(), digest))


def handler(document, digest):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/health":
                self.respond(200, {"status": "ok"})
                return
            if parsed.path != "/codex/models":
                self.respond(404, {"error": "Not found"})
                return
            if not digest:
                self.respond(503, {"error": "Catalog authentication unavailable"})
                return
            if not authorized(self.headers.get("Authorization"), digest):
                self.respond(401, {"error": "Unauthorized"})
                return
            version = parse_qs(parsed.query).get("client_version", [""])[0]
            if version and (len(version) > 32 or not all(
                    part.isdecimal() for part in version.split(".")) or len(version.split(".")) != 3):
                self.respond(400, {"error": "client_version must be major.minor.patch"})
                return
            catalog = ready_catalog(document)
            self.respond(200 if catalog["models"] else 503, catalog)

        def respond(self, status, document):
            body = json.dumps(document).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if status == 401:
                self.send_header("WWW-Authenticate", "Bearer")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            # Do not log headers, request targets or query strings.
            pass

    return Handler


if __name__ == "__main__":
    document = json.loads(Path(os.environ.get("CATALOG_PATH", "/app/models.json")).read_text())
    digests_path = Path(os.environ.get("AUTH_DIGEST_PATH", "/auth/sha256"))
    digest = digests_path.read_text().strip()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Catalog credential digest must be SHA-256 hex")
    ThreadingHTTPServer(("0.0.0.0", 8000), handler(document, digest)).serve_forever()
