#!/usr/bin/env python3
"""Open-loop streaming completion measurement. No concurrency semaphore or connector cap.

All launched requests, including cancellations and timeouts, are written to JSONL.
Latency begins at scheduled arrival, including controller dispatch delay. ITL is
measured from client token arrival events. Tokens coalesced in one event share its
arrival timestamp. Also report P99 per-request mean ITL. Engine timings inside a
coalesced event are unavailable; all event counts and timestamps are retained.
"""
import argparse
import asyncio
import json
import math
import pathlib
import re
import time

import aiohttp
import numpy as np


def percentile(values, q):
    return float(np.percentile(values, q)) if values else None


def metrics(text):
    selected = {}
    for line in text.splitlines():
        if line.startswith('#'):
            continue
        if any(line.startswith('vllm:' + k) for k in ['num_requests_running{', 'num_requests_waiting{', 'kv_cache_usage_perc{', 'gpu_cache_usage_perc{', 'num_preemptions_total{', 'request_success_total{', 'prompt_tokens_total{', 'generation_tokens_total{', 'prefix_cache_hits_total{']):
            key = line.split('{')[0]
            try:
                value = float(line.rsplit(' ', 1)[1])
                if math.isfinite(value):
                    selected[key] = selected.get(key, 0) + value
            except ValueError:
                pass
    return selected


async def measure(url, model, dataset, rate, count, path, telemetry_urls, timeout=60, seqs=1):
    path = pathlib.Path(path)
    path.mkdir(parents=True, exist_ok=False)
    (path / 'run-config.json').write_text(json.dumps({'url': url, 'model': model, 'rate': rate, 'count': count, 'timeout': timeout, 'seqs': seqs, 'arrivals': 'deterministic open-loop', 'connector_limit': 0, 'semaphore': None, 'dataset_ids': [x['id'] for x in dataset[:count]]}, indent=2))
    if len(dataset) < count:
        raise ValueError('Insufficient distinct prompts')
    records = []
    samples = []
    stop = asyncio.Event()
    stop_reasons = []
    tasks = set()
    start = time.perf_counter() + 0.2
    epoch = time.time() + 0.2
    record_file = (path / 'requests.jsonl').open('w', buffering=1)
    telemetry_file = (path / 'telemetry.jsonl').open('w', buffering=1)
    request_timeout = aiohttp.ClientTimeout(total=timeout)
    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=connector, timeout=request_timeout) as session:
        async def one(item, scheduled):
            dispatched = time.perf_counter()
            row = {'id': item['id'], 'scheduled_s': scheduled - start, 'scheduled_epoch': epoch + scheduled - start, 'dispatch_lag_s': dispatched - scheduled, 'input_tokens_expected': 512, 'output_tokens_expected': 128, 'status': 'error', 'error': None, 'usage': None, 'token_events': [], 'finish_reason': None}
            payload = {'model': model, 'prompt': item['prompt'], 'max_tokens': 128, 'min_tokens': 128, 'ignore_eos': True, 'temperature': 0, 'seed': 20261015, 'stream': True, 'stream_options': {'include_usage': True}, 'logprobs': 1}
            done = False
            try:
                async with session.post(url + '/v1/completions', json=payload) as response:
                    row['http_status'] = response.status
                    if response.status != 200:
                        raise RuntimeError((await response.text())[:2000])
                    async for line in response.content:
                        if not line.startswith(b'data: '):
                            continue
                        content = line[6:].strip()
                        if content == b'[DONE]':
                            done = True
                            break
                        chunk = json.loads(content)
                        if chunk.get('error'):
                            raise RuntimeError(str(chunk['error']))
                        if chunk.get('usage'):
                            row['usage'] = chunk['usage']
                        for choice in chunk.get('choices', []):
                            if choice.get('finish_reason'):
                                row['finish_reason'] = choice['finish_reason']
                            tokens = (choice.get('logprobs') or {}).get('tokens') or []
                            if tokens:
                                row['token_events'].append({'t_s': time.perf_counter() - scheduled, 'n_tokens': len(tokens), 'tokens': tokens})
                if not done:
                    raise RuntimeError('Stream ended without DONE')
                row['status'] = 'completed'
            except asyncio.TimeoutError:
                row['status'] = 'timeout'
                row['error'] = 'Request timeout'
            except asyncio.CancelledError:
                row['status'] = 'cancelled'
                row['error'] = 'Run stopped by safety monitor'
            except Exception as e:
                row['error'] = f'{type(e).__name__}: {e}'
            finally:
                row['e2e_s'] = time.perf_counter() - scheduled
                row['completed_s'] = time.perf_counter() - start
                row['ttft_s'] = row['token_events'][0]['t_s'] if row['token_events'] else None
                usage = row['usage'] or {}
                row['length_valid'] = usage.get('prompt_tokens') == 512 and usage.get('completion_tokens') == 128
                row['token_timing_valid'] = sum(x['n_tokens'] for x in row['token_events']) == 128
                row['observed_output_tokens'] = sum(x['n_tokens'] for x in row['token_events'])
                row['coalesced_events'] = sum(x['n_tokens'] > 1 for x in row['token_events'])
                row['mean_itl_s'] = (row['token_events'][-1]['t_s']-row['token_events'][0]['t_s'])/127 if row['token_timing_valid'] else None
                record_file.write(json.dumps(row) + '\n')
                records.append(row)
                if row['status'] != 'completed' or not row['length_valid']:
                    stop_reasons.append(f"request {row['id']}: {row['status']}, length_valid={row['length_valid']}")
                    stop.set()

        async def monitor():
            failures = 0
            while not stop.is_set():
                sample = {'t_s': time.perf_counter() - start, 'client_outstanding': len(tasks), 'metrics': {}, 'raw': {}}
                for endpoint in telemetry_urls:
                    try:
                        async with session.get(endpoint, timeout=aiohttp.ClientTimeout(total=4)) as r:
                            if r.status != 200:
                                raise RuntimeError(f'HTTP {r.status}')
                            raw = await r.text()
                            sample['metrics'].update(metrics(raw))
                            if ':9100/' in endpoint:
                                raw = '\n'.join(line for line in raw.splitlines() if line.startswith(('node_memory_', 'node_pressure_memory_', 'node_hwmon_temp_', 'node_hwmon_power_')))
                            elif '/metrics' in endpoint and ':9400/' not in endpoint:
                                raw = '\n'.join(line for line in raw.splitlines() if line.split('{')[0] in sample['metrics'])
                            sample['raw'][endpoint] = raw
                    except Exception as e:
                        sample['raw'][endpoint] = {'unavailable': str(e)}
                if not sample['metrics']:
                    failures += 1
                else:
                    failures = 0
                samples.append(sample)
                telemetry_file.write(json.dumps(sample) + '\n')
                waiting = sample['metrics'].get('vllm:num_requests_waiting', 0)
                cache = sample['metrics'].get('vllm:kv_cache_usage_perc', sample['metrics'].get('vllm:gpu_cache_usage_perc', 0))
                available_memory = None
                for raw in sample['raw'].values():
                    if isinstance(raw,str):
                        for line in raw.splitlines():
                            if line.startswith('node_memory_MemAvailable_bytes '):
                                available_memory = float(line.split()[1])
                memory_low = available_memory is not None and available_memory < 8*1024**3
                if len(tasks) > 128 or waiting > max(16, 4 * seqs) or cache > .95 or failures >= 5 or memory_low:
                    stop_reasons.append(f'health/backlog stop: outstanding={len(tasks)}, waiting={waiting}, cache={cache}, metric_failures={failures}, available_memory={available_memory}')
                    stop.set()
                # Six consecutive 5-second bins growing by >=1 request is sustained backlog.
                recent = [x for x in samples if x['t_s'] >= sample['t_s'] - 30]
                if recent and recent[-1]['t_s'] - recent[0]['t_s'] >= 29:
                    bins = []
                    for offset in range(6):
                        vals = [x['metrics'].get('vllm:num_requests_waiting', 0) for x in recent if recent[0]['t_s'] + 5*offset <= x['t_s'] < recent[0]['t_s'] + 5*(offset+1)]
                        bins.append(float(np.mean(vals)) if vals else 0)
                    slope = float(np.polyfit(range(6),bins,1)[0])/5
                    if (all(bins[i+1] >= bins[i] + .5 for i in range(5)) or (slope > .05 and bins[-1]-bins[0] >= 3 and all(x >= 2 for x in bins[-3:]))):
                        stop_reasons.append(f'Sustained backlog growth: {bins}')
                        stop.set()
                await asyncio.sleep(1)

        monitor_task = asyncio.create_task(monitor())
        launched = 0
        for i, item in enumerate(dataset[:count]):
            scheduled = start + i / rate
            delay = scheduled - time.perf_counter()
            if delay > 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
            if stop.is_set():
                break
            task = asyncio.create_task(one(item, scheduled))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            launched += 1
            if time.perf_counter() - scheduled > .25:
                stop_reasons.append('Controller dispatch exceeded 250 ms; offered rate invalid')
                stop.set()
                break
        while tasks and not stop.is_set():
            await asyncio.wait(tasks, timeout=.5)
        if stop.is_set():
            for task in list(tasks):
                task.cancel()
        if tasks:
            await asyncio.gather(*list(tasks), return_exceptions=True)
        stop.set()
        monitor_task.cancel()
        await asyncio.gather(monitor_task, return_exceptions=True)
    record_file.close()
    telemetry_file.close()
    completed = [r for r in records if r['status'] == 'completed']
    total_time = max([r['completed_s'] for r in records] or [0])
    mean_itls = [r['mean_itl_s'] for r in completed if r['mean_itl_s'] is not None]
    gaps = []
    for row in completed:
        if row['token_timing_valid']:
            arrivals = [event['t_s'] for event in row['token_events'] for _ in range(event['n_tokens'])]
            gaps.extend(b-a for a,b in zip(arrivals,arrivals[1:]))
    elapsed_arrivals = max(1/rate, (launched-1)/rate)
    actual_dispatch = [r['scheduled_s'] + r['dispatch_lag_s'] for r in records]
    actual_rate = (launched-1)/(max(actual_dispatch)-min(actual_dispatch)) if len(actual_dispatch)>1 else None
    summary = {'requested': count, 'launched': launched, 'completed': len(completed), 'errors': sum(r['status'] == 'error' for r in records), 'timeouts': sum(r['status'] == 'timeout' for r in records), 'cancelled': sum(r['status'] == 'cancelled' for r in records), 'offered_rps': rate, 'actual_dispatch_rps': actual_rate, 'achieved_rps': len(completed)/total_time if total_time else 0, 'output_tokens_per_second': sum((r['usage'] or {}).get('completion_tokens',0) for r in completed)/total_time if total_time else 0, 'observed_output_tokens_all_statuses': sum(r['observed_output_tokens'] for r in records), 'observed_output_tokens_per_second_all_statuses': sum(r['observed_output_tokens'] for r in records)/total_time if total_time else 0, 'duration_s': total_time, 'arrival_span_s': elapsed_arrivals, 'seqs': seqs, 'e2e_p50_s': percentile([r['e2e_s'] for r in completed],50), 'e2e_p95_s': percentile([r['e2e_s'] for r in completed],95), 'e2e_p99_s': percentile([r['e2e_s'] for r in completed],99), 'ttft_p99_s': percentile([r['ttft_s'] for r in completed if r['ttft_s'] is not None],99), 'itl_p99_s': percentile(gaps,99), 'itl_sample_count': len(gaps), 'itl_definition': 'P99 of client-observed token arrival gaps; coalesced tokens share event arrival time', 'per_request_mean_itl_p99_s': percentile(mean_itls,99), 'coalesced_events': sum(r['coalesced_events'] for r in completed), 'length_invalid': sum(not r['length_valid'] for r in completed), 'token_timing_invalid': sum(not r['token_timing_valid'] for r in completed), 'dispatch_lag_p99_s': percentile([r['dispatch_lag_s'] for r in records],99), 'stop_reasons': stop_reasons, 'output_length_counts': {str(k):sum((r['usage'] or {}).get('completion_tokens')==k for r in records) for k in set((r['usage'] or {}).get('completion_tokens') for r in records)}, 'max_running': max([s['metrics'].get('vllm:num_requests_running',0) for s in samples] or [0]), 'max_waiting': max([s['metrics'].get('vllm:num_requests_waiting',0) for s in samples] or [0])}
    summary['valid'] = len(completed) == count and not stop_reasons and summary['length_invalid'] == 0 and summary['token_timing_invalid'] == 0 and summary['dispatch_lag_p99_s'] < .05 and (count<2 or abs(actual_rate/rate-1)<.02)
    (path/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--workload', type=pathlib.Path, required=True)
    p.add_argument('--offset', type=int, default=0)
    p.add_argument('--rate', type=float, required=True)
    p.add_argument('--count', type=int, required=True)
    p.add_argument('--seqs', type=int, required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--telemetry-url', action='append', required=True)
    a = p.parse_args()
    rows = [json.loads(line) for line in a.workload.open()]
    print(json.dumps(asyncio.run(measure(a.url,a.model,rows[a.offset:],a.rate,a.count,a.out,a.telemetry_url,seqs=a.seqs)),indent=2))
