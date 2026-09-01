"""Discover serving Services and expose only their live OpenAI model IDs."""
import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os
from pathlib import Path
import time

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

REFRESH_INTERVAL = 28.0
SA_PATH = Path('/var/run/secrets/kubernetes.io/serviceaccount')
log = logging.getLogger(__name__)
_cache = []
_last_success = 0.0
_http_client = None
_kube_client = None
_namespace = None


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
    global _cache, _last_success
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
        _cache = [models[key] for key in sorted(models)]
        _last_success = time.monotonic()
    except Exception:
        # Never substitute stale or configured models for failed discovery.
        log.exception('Service discovery failed')
        _cache = []
        _last_success = 0.0


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
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as backend_client, \
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


@app.get('/health')
async def health():
    return {'status': 'ok'}
