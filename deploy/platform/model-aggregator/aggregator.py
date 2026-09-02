"""Discover serving Services and expose only their live OpenAI model IDs."""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import os
from pathlib import Path
import secrets
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

REFRESH_INTERVAL = 28.0
SA_PATH = Path('/var/run/secrets/kubernetes.io/serviceaccount')
log = logging.getLogger(__name__)
_cache = []
_model_backends = {}
_last_success = 0.0
_http_client = None
_kube_client = None
_namespace = None
PROVIDER_DOCUMENT_PATH = Path(os.environ.get(
    'OPENROUTER_MODEL_DOCUMENT_PATH', '/etc/openrouter/models.json'))
OPENROUTER_CONCURRENCY = int(os.environ.get('OPENROUTER_MAX_CONCURRENCY', '16'))
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
_admission_lock = asyncio.Lock()
_inflight = 0


def service_url(service):
    meta, spec = service.get('metadata', {}), service.get('spec', {})
    labels, selector = meta.get('labels', {}), spec.get('selector', {})
    serving = (
        labels.get('token-labs/model') == 'true'
        or (selector.get('llm-d.ai/inference-serving') == 'true'
            and selector.get('llm-d.ai/role') == 'decode')
        or selector.get('nvidia.com/dynamo-component-type') == 'frontend'
    )
    if not serving or spec.get('type') == 'ExternalName' or not selector:
        return None
    ports = [p for p in spec.get('ports', []) if p.get('protocol', 'TCP') == 'TCP']
    port = next((p['port'] for p in ports if p.get('name') == 'http'), None)
    if port is None:
        port = next((p['port'] for p in ports if p.get('port') == 8000), None)
    if port is None:
        return None
    return f"http://{meta['name']}.{meta['namespace']}.svc.cluster.local:{port}/v1/models"


async def fetch_live_models(url):
    try:
        response = await _http_client.get(url)
        response.raise_for_status()
        data = response.json()['data']
        if not isinstance(data, list):
            return []
        return [dict(id=m['id'], object='model', owned_by='token-labs')
                for m in data if isinstance(m, dict)
                and isinstance(m.get('id'), str) and m['id'].strip()]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        log.warning('Model endpoint unavailable: %s', url)
        return []


async def refresh_cache():
    global _cache, _last_success, _model_backends
    try:
        # Read the projected token each time so Kubernetes token rotation works.
        token = SA_PATH.joinpath('token').read_text().strip()
        response = await _kube_client.get(
            f'/api/v1/namespaces/{_namespace}/services',
            headers={'Authorization': f'Bearer {token}'})
        response.raise_for_status()
        services = response.json()['items']
        urls = sorted({url for service in services if (url := service_url(service))})
        results = await asyncio.gather(*(fetch_live_models(url) for url in urls))
        models = {m['id']: m for group in results for m in group}
        _model_backends = {
            model['id']: url.removesuffix('/v1/models')
            for url, group in zip(urls, results)
            for model in group
        }
        _cache = [models[key] for key in sorted(models)]
        _last_success = time.monotonic()
    except Exception:
        # Never substitute stale or configured models for failed discovery.
        log.exception('Service discovery failed')
        _cache = []
        _model_backends = {}
        _last_success = 0.0


def provider_document():
    """Load the approved static provider document from the mounted ConfigMap."""
    try:
        envelope = json.loads(PROVIDER_DOCUMENT_PATH.read_text())
        documents = envelope['data']
        if not isinstance(documents, list) or not all(
                isinstance(document, dict) for document in documents):
            raise ValueError('data must be an array')
        return envelope
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        log.exception('Approved OpenRouter model document unavailable')
        return None


async def admit():
    global _inflight
    async with _admission_lock:
        if _inflight >= OPENROUTER_CONCURRENCY:
            return False
        _inflight += 1
        return True


async def release():
    global _inflight
    async with _admission_lock:
        _inflight -= 1


def provider_authorized(authorization: str | None) -> bool:
    if not OPENROUTER_API_KEY or not authorization:
        return False
    scheme, separator, credential = authorization.partition(' ')
    return (separator == ' ' and scheme.lower() == 'bearer'
            and secrets.compare_digest(credential, OPENROUTER_API_KEY))


async def background_refresh():
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        await refresh_cache()


@asynccontextmanager
async def lifespan(app):
    global _http_client, _kube_client, _namespace
    _namespace = SA_PATH.joinpath('namespace').read_text().strip()
    host = os.environ['KUBERNETES_SERVICE_HOST']
    port = os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', '443')
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0),
                              trust_env=False) as backend_client, \
            httpx.AsyncClient(base_url=f'https://{host}:{port}', timeout=5.0,
                              verify=str(SA_PATH / 'ca.crt'), trust_env=False) as kube_client:
        # Separate clients ensure Kubernetes credentials never reach model servers.
        _http_client, _kube_client = backend_client, kube_client
        await refresh_cache()
        task = asyncio.create_task(background_refresh())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(lifespan=lifespan)


@app.get('/v1/models')
@app.get('/models')
async def list_models():
    headers = {'Cache-Control': 'no-store'}
    if not _last_success or time.monotonic() - _last_success > 2 * REFRESH_INTERVAL:
        return JSONResponse({'error': {'message': 'Model discovery unavailable'}},
                            status_code=503, headers=headers)
    return JSONResponse({'object': 'list', 'data': _cache}, headers=headers)


@app.get('/openrouter/v1/models')
async def list_openrouter_api_models(request: Request):
    if not OPENROUTER_API_KEY:
        return JSONResponse({'error': {'message': 'Provider credentials unavailable'}},
                            status_code=503)
    if not provider_authorized(request.headers.get('authorization')):
        return JSONResponse({'error': {'message': 'Unauthorized'}}, status_code=401,
                            headers={'WWW-Authenticate': 'Bearer'})
    return await list_models()


@app.get('/openrouter/models')
async def list_openrouter_models():
    headers = {'Cache-Control': 'no-store'}
    document = provider_document()
    if document is None:
        return JSONResponse({'error': {'message': 'Provider catalog unavailable'}},
                            status_code=503, headers=headers)
    return JSONResponse(document, headers=headers)


async def proxy_chat_completions(request: Request):
    """Bound queueing and proxy an accepted request to its discovered backend."""
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({'error': {'message': 'Invalid JSON'}}, status_code=400)
    model = payload.get('model') if isinstance(payload, dict) else None
    backend = _model_backends.get(model)
    if backend is None:
        return JSONResponse({'error': {'message': 'Model is not ready'}}, status_code=404)
    if not await admit():
        return JSONResponse(
            {'error': {'message': 'Capacity temporarily exhausted; retry later'}},
            status_code=429,
            headers={'Retry-After': '1', 'Cache-Control': 'no-store'},
        )
    upstream = None
    slot_owned = True
    try:
        upstream = await _http_client.send(
            _http_client.build_request(
                'POST', f'{backend}/v1/chat/completions', json=payload,
                headers={'accept': request.headers.get('accept', 'application/json')}),
            stream=True,
        )
        content_type = upstream.headers.get('content-type', 'application/json')
        if payload.get('stream'):
            async def stream_and_release():
                try:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
                finally:
                    await upstream.aclose()
                    await release()
            slot_owned = False
            return StreamingResponse(stream_and_release(), status_code=upstream.status_code,
                                     media_type=content_type)
        body = await upstream.aread()
        await upstream.aclose()
        await release()
        slot_owned = False
        return JSONResponse(content=json.loads(body), status_code=upstream.status_code)
    except Exception:
        if upstream is not None:
            await upstream.aclose()
        if slot_owned:
            await release()
        log.exception('OpenRouter upstream request failed')
        return JSONResponse({'error': {'message': 'Upstream unavailable'}},
                            status_code=502)


@app.post('/v1/chat/completions')
async def direct_chat_completions(request: Request):
    """Proxy the public Token Labs API using the same live catalog mapping."""
    return await proxy_chat_completions(request)


@app.post('/openrouter/v1/chat/completions')
async def openrouter_chat_completions(request: Request):
    """Authenticate OpenRouter, then use the shared live backend mapping."""
    if not OPENROUTER_API_KEY:
        return JSONResponse({'error': {'message': 'Provider credentials unavailable'}},
                            status_code=503)
    if not provider_authorized(request.headers.get('authorization')):
        return JSONResponse({'error': {'message': 'Unauthorized'}}, status_code=401,
                            headers={'WWW-Authenticate': 'Bearer'})
    return await proxy_chat_completions(request)


@app.get('/health')
async def health():
    return {'status': 'ok'}
