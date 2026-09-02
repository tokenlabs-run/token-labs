#!/usr/bin/env python3
"""Resumable controller-side Qwen3 llm-d/Dynamo AIPerf matrix.

Run one process per backend. A point is accepted only after checking the
export's request/error counts and actual server-reported output length.
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import time
import urllib.request

MODEL = 'Qwen/Qwen3-30B-A3B-Instruct-2507-FP8'
COMBOS = [(1024, 8192), (8192, 8192), (8192, 1024)]
CONCURRENCIES = [1, 2, 4, 8, 16, 32, 64]
BACKENDS = {
    'llm-d': 'http://10.107.76.65:8000',
    'dynamo': 'http://10.96.28.158:8000',
}


def validate(path, count, osl, isl=None):
    d = json.loads(path.read_text())
    errors = d.get('error_summary')
    if errors:
        raise ValueError(f'benchmark errors: {errors}')
    metric = d.get('request_count') or {}
    completed = metric.get('avg')
    if completed != count:
        raise ValueError(f'completed {completed}, expected {count}')
    output = d.get('output_sequence_length') or {}
    if any(abs(float(output.get(k, -1)) - osl) > 0.01 for k in ('avg', 'min', 'max')):
        raise ValueError(f'output length mismatch: {output}, requested {osl}')
    if isl is not None:
        inp = d.get("input_sequence_length") or {}
        if any(abs(float(inp.get(k, -1)) - isl) > 0.01 for k in ("avg", "min", "max")):
            raise ValueError(f"input length mismatch: {inp}, requested {isl}")
    return d


def wait_ready(url, model):
    deadline = time.monotonic() + 7200
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + '/v1/models', timeout=10) as r:
                if any(m['id'] == model for m in json.load(r)['data']):
                    return
        except Exception:
            pass
        time.sleep(15)
    raise RuntimeError(f'endpoint did not become ready: {url}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('backend', choices=BACKENDS)
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--aiperf', default='/home/nvidia/aiperf-venv/bin/aiperf')
    ap.add_argument('--url')
    ap.add_argument('--smoke', action='store_true')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    url = args.url or BACKENDS[args.backend]
    model = MODEL + '-' + args.backend
    print(f'Waiting for {args.backend}: {url}', flush=True)
    wait_ready(url, model)
    combos = [(128, 32)] if args.smoke else COMBOS
    levels = [1] if args.smoke else CONCURRENCIES
    for isl, osl in combos:
        for c in levels:
            # At least two full waves, and four samples even at c=1.
            count = 2 if args.smoke else max(4, 2*c)
            name = f'isl{isl}-osl{osl}__{args.backend}-c{c}'
            run_dir = args.out / name
            export = run_dir / 'profile_export_aiperf.json'
            if export.exists():
                validate(export, count, osl, isl)
                print(f'RESUME {name}: valid export already exists', flush=True)
                continue
            cmd = [args.aiperf, 'profile', '-m', model, '--url', url,
                   '--endpoint-type', 'completions', '--streaming',
                   '--concurrency', str(c), '--request-count', str(count),
                   '--num-warmup-requests', '1',
                   '--synthetic-input-tokens-mean', str(isl),
                   '--synthetic-input-tokens-stddev', '0',
                   '--output-tokens-mean', str(osl), '--output-tokens-stddev', '0',
                   '--num-dataset-entries', str(count+1),
                   '--tokenizer', MODEL, '--use-server-token-count',
                   '--use-legacy-max-tokens', '--random-seed', '42',
                   '--extra-inputs', json.dumps({'ignore_eos': True, 'temperature': 0}),
                   '--request-timeout-seconds', '7200',
                   '--artifact-dir', str(run_dir)]
            record = {'backend': args.backend, 'isl': isl, 'osl': osl,
                      'concurrency': c, 'requests': count, 'command': cmd,
                      'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
            (args.out / (name + '.command.json')).write_text(json.dumps(record, indent=2)+'\n')
            print(f'START {name} requests={count}', flush=True)
            with (args.out / (name+'.log')).open('w') as log:
                result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=43200)
            if result.returncode:
                raise RuntimeError(f'{name} failed: exit {result.returncode}; see its log')
            validate(export, count, osl, isl)
            print(f'OK {name}', flush=True)
    print(f'COMPLETE {args.backend}', flush=True)


if __name__ == '__main__':
    main()
