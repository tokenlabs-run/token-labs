#!/usr/bin/env python3
"""Recompute latency/throughput from per-request records and plot the experiment."""
import argparse
import csv
import json
import pathlib
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def pct(values,q):
    return float(np.percentile(values,q)) if values else None


def field_values(samples,prefix):
    values=[]
    for sample in samples:
        for endpoint,raw in sample['raw'].items():
            if not isinstance(raw,str):
                continue
            for line in raw.splitlines():
                if line.startswith(prefix+'{') or line.startswith(prefix+' '):
                    try:
                        value=float(line.rsplit(' ',1)[-1])
                        # DCGM blank/not-supported sentinel values must not become zeros.
                        if np.isfinite(value) and abs(value)<1e12:
                            values.append(value)
                    except ValueError:
                        pass
    return values


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=pathlib.Path,required=True);a=p.parse_args();root=a.root
    threshold=json.loads((root/'frozen-threshold.json').read_text())
    assert threshold['experimental_threshold_not_customer_slo']
    rows=[]
    for folder in sorted((root/'raw').iterdir()):
        if not (folder/'summary.json').exists():
            continue
        r=json.loads((folder/'summary.json').read_text());r['name']=folder.name
        requests=[json.loads(line) for line in (folder/'requests.jsonl').open()]
        samples=[json.loads(line) for line in (folder/'telemetry.jsonl').open()]
        completed=[x for x in requests if x['status']=='completed']
        actual=pct([x['e2e_s'] for x in completed],99)
        assert actual==r['e2e_p99_s'],folder
        for q,key in [(50,'e2e_p50_s'),(95,'e2e_p95_s')]:
            assert pct([x['e2e_s'] for x in completed],q)==r[key],folder
        seconds=max([x['completed_s'] for x in requests] or [0])
        tokens=sum((x['usage'] or {}).get('completion_tokens',0) for x in completed)
        assert abs(tokens/seconds-r['output_tokens_per_second'])<1e-8,folder
        assert len(completed)==r['completed'],folder
        assert sum(not x['length_valid'] for x in completed)==r['length_invalid'],folder
        assert sum(not x['token_timing_valid'] for x in completed)==r['token_timing_invalid'],folder
        for request in completed:
            if request['length_valid']:
                assert request['usage']['prompt_tokens']==512 and request['usage']['completion_tokens']==128,folder
            if request['token_timing_valid']:
                assert sum(event['n_tokens'] for event in request['token_events'])==128,folder
        assert pct([x['ttft_s'] for x in completed if x['ttft_s'] is not None],99)==r['ttft_p99_s'],folder
        gaps=[]
        for row in completed:
            if row['token_timing_valid']:
                arrivals=[event['t_s'] for event in row['token_events'] for _ in range(event['n_tokens'])]
                gaps.extend(b-a for a,b in zip(arrivals,arrivals[1:]))
        assert pct(gaps,99)==r['itl_p99_s'],folder
        assert r['errors']==sum(x['status']=='error' for x in requests),folder
        assert r['timeouts']==sum(x['status']=='timeout' for x in requests),folder
        assert r['cancelled']==sum(x['status']=='cancelled' for x in requests),folder
        r['passes_limit']=bool(r['valid'] and actual is not None and actual<=threshold['limit_s'])
        r['mean_ttft_s']=float(np.mean([x['ttft_s'] for x in completed if x['ttft_s'] is not None])) if completed else None
        r['post_first_token_p99_s']=pct([x['e2e_s']-x['ttft_s'] for x in completed if x['ttft_s'] is not None],99)
        for prefix,key,op in [('DCGM_FI_DEV_GPU_UTIL','gpu_util_mean_pct',np.mean),('DCGM_FI_DEV_GPU_TEMP','gpu_temp_max_c',max),('DCGM_FI_DEV_POWER_USAGE','gpu_power_mean_w',np.mean),('node_memory_MemAvailable_bytes','host_mem_available_min_bytes',min),('vllm:kv_cache_usage_perc','kv_cache_use_max',max),('vllm:gpu_cache_usage_perc','legacy_kv_cache_use_max',max)]:
            vals=field_values(samples,prefix);r[key]=float(op(vals)) if vals else None
        preemptions=field_values(samples,'vllm:num_preemptions_total');r['preemptions_delta']=max(preemptions)-min(preemptions) if preemptions else None
        r['profiling_fields_status']='unavailable unless explicitly exported; no bandwidth or kernel bottleneck inferred'
        rows.append(r)
    calibration=next(r for r in rows if r['name']==threshold['baseline_run'])
    assert calibration['completed']>=1000 and threshold['limit_s']==threshold['multiplier']*calibration['e2e_p99_s']
    (root/'verified-runs.json').write_text(json.dumps(rows,indent=2)+'\n')
    fields=['name','seqs','requested','completed','offered_rps','actual_dispatch_rps','achieved_rps','output_tokens_per_second','observed_output_tokens_per_second_all_statuses','e2e_p50_s','e2e_p95_s','e2e_p99_s','ttft_p99_s','itl_p99_s','per_request_mean_itl_p99_s','coalesced_events','errors','timeouts','cancelled','max_running','max_waiting','kv_cache_use_max','preemptions_delta','gpu_util_mean_pct','gpu_temp_max_c','gpu_power_mean_w','host_mem_available_min_bytes','valid','passes_limit']
    with (root/'comparison.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    fig,axes=plt.subplots(1,2,figsize=(12,5),sharex=True)
    for ax in axes:
        for seqs,color in [(1,'#2266aa'),(2,'#dd7722'),(4,'#339955'),(8,'#9955aa')]:
            selected=[r for r in rows if r['seqs']==seqs and r['name'].startswith(('sweep','refine','confirm')) and r['e2e_p99_s'] is not None]
            exploratory=sorted([r for r in selected if not r['name'].startswith('confirm')],key=lambda r:r['output_tokens_per_second'])
            ax.plot([r['output_tokens_per_second'] for r in exploratory],[r['e2e_p99_s'] for r in exploratory],color=color,alpha=.4)
            for passed,marker in [(True,'o'),(False,'x')]:
                points=[r for r in selected if r['passes_limit']==passed and not r['name'].startswith('confirm')]
                ax.scatter([r['output_tokens_per_second'] for r in points],[r['e2e_p99_s'] for r in points],color=color,marker=marker,label=f'max_num_seqs={seqs}' if passed else None)
            confirms=[r for r in selected if r['name'].startswith('confirm')]
            ax.scatter([r['output_tokens_per_second'] for r in confirms],[r['e2e_p99_s'] for r in confirms],marker='*',s=120,color=color)
            failed_confirms=[r for r in confirms if not r['passes_limit']]
            ax.scatter([r['output_tokens_per_second'] for r in failed_confirms],[r['e2e_p99_s'] for r in failed_confirms],marker='x',s=85,color='red')
        ax.axhline(threshold['limit_s'],color='black',linestyle='--',label=f"Experimental limit {threshold['limit_s']:.3f} s")
        ax.set(xlabel='Completed output tokens/second, including drain',ylabel='Per-request P99 end-to-end latency, seconds',title='vLLM batching on one DGX Spark, 512 input / 128 output tokens')
        ax.grid(alpha=.2)
    axes[0].set_title('All measured points')
    axes[1].set_title('Near the frozen latency limit')
    axes[1].set_ylim(bottom=min(r['e2e_p99_s'] for r in rows if r['e2e_p99_s'] is not None)*.95,top=threshold['limit_s']*1.15)
    axes[0].legend(fontsize=8)
    fig.suptitle('vLLM batching on one DGX Spark, 512 input / 128 output tokens')
    fig.tight_layout();fig.savefig(root/'throughput-versus-p99.png',dpi=180);fig.savefig(root/'throughput-versus-p99.svg');plt.close(fig)
    conclusion=json.loads((root/'conclusion.json').read_text()) if (root/'conclusion.json').exists() else {'complete':False}
    exploratory=[r for r in rows if r['name'].startswith(('sweep','refine'))]
    best={s:max((r for r in exploratory if r['seqs']==s and r['passes_limit']),key=lambda r:r['output_tokens_per_second'],default=None) for s in [1,2,4,8]}
    capacity_table=['| max_num_seqs | Best passing exploratory RPS | Output tok/s | P99 s | Completed | Sampled peak running |', '| ---: | ---: | ---: | ---: | ---: | ---: |']
    for seqs,r in best.items():
        if r:
            capacity_table.append(f"| {seqs} | {r['offered_rps']:.4f} | {r['output_tokens_per_second']:.2f} | {r['e2e_p99_s']:.4f} | {r['completed']} | {r['max_running']:.0f} |")
        else:
            capacity_table.append(f'| {seqs} | No passing point; inspect blocked records and raw results | | | | |')
    selected_names={name for names in conclusion.get('selected_confirmation_runs',{}).values() for name in names}
    variability=['| Seqs | Confirmation runs | Completed | Output tok/s mean ± sample SD | Range | P99 range, s | Every run passes |', '| ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for seqs in [1,2,4,8]:
        runs=[r for r in rows if r['seqs']==seqs and r['name'].startswith('confirm') and (not selected_names or r['name'] in selected_names)]
        if runs:
            rates=[r['output_tokens_per_second'] for r in runs]
            tails=[r['e2e_p99_s'] for r in runs]
            sd=statistics.stdev(rates) if len(rates)>1 else 0
            variability.append(f"| {seqs} | {len(runs)} | {sum(r['completed'] for r in runs)} | {statistics.mean(rates):.3f} ± {sd:.3f} | {min(rates):.3f}–{max(rates):.3f} | {min(tails):.4f}–{max(tails):.4f} | {all(r['passes_limit'] for r in runs)} |")
    if not conclusion.get('complete'):
        outcome='Confirmation is in progress. Exploratory points do not establish an improvement.'
    elif conclusion.get('improvement_demonstrated'):
        outcome=f"Increasing max_num_seqs from 1 to {conclusion['candidate']} demonstrated a sustainable output-throughput improvement of {100*conclusion['mean_improvement_fraction']:.1f}% between confirmation means. All six selected confirmations at the final operating rates met the frozen limit; the conservative throughput and variability gates passed."
    else:
        outcome='The confirmation protocol did not establish an improvement. The frozen latency limit was retained; inspect the confirmation table and decision below.'
    failures=[r for r in rows if r['errors'] or r['timeouts'] or r['cancelled'] or not r['valid']]
    failure_text='No completed run contained a client error, timeout, safety cancellation or invalid token count.' if not failures else '\n'.join(f"- {r['name']}: {r['errors']} errors, {r['timeouts']} timeouts, {r['cancelled']} cancellations; stop reasons: {json.dumps(r.get('stop_reasons',[]))}." for r in failures)
    rejected=[r for r in rows if r['name'].startswith('confirm') and selected_names and r['name'] not in selected_names]
    rejected_text=''
    if rejected:
        rejected_text='Higher offered-rate confirmation attempts remain visible and do not qualify the selected lower-rate operating point:\n\n'+'\n'.join(f"- {r['name']}: offered {r['offered_rps']:.6f} RPS, {r['completed']} completed, P99 {r['e2e_p99_s']:.6f} s, passes frozen limit: {r['passes_limit']}." for r in rejected)
    if conclusion.get('complete') and selected_names:
        for seqs,stats in conclusion['confirmation_stats'].items():
            runs=[r for r in rows if r['name'] in selected_names and r['seqs']==int(seqs)]
            assert len(runs)==3 and sum(r['completed'] for r in runs)==stats['completed']>=3000
            rates=[r['output_tokens_per_second'] for r in runs]
            assert abs(statistics.mean(rates)-stats['mean_output_tokens_per_second'])<1e-9
            assert abs(statistics.stdev(rates)-stats['std_output_tokens_per_second'])<1e-9
            assert all(r['passes_limit'] for r in runs)==stats['every_run_passes']
            assert sorted(r['e2e_p99_s'] for r in runs)==sorted(stats['p99_seconds'])
        one=conclusion['confirmation_stats']['1'];other=conclusion['confirmation_stats'][str(conclusion['candidate'])]
        best_one=max(r['output_tokens_per_second'] for r in rows if r['seqs']==1 and r['passes_limit'] and r['name'].startswith(('sweep','refine','confirm')))
        passes=one['every_run_passes'] and other['every_run_passes'] and other['min_output_tokens_per_second']>=1.1*best_one and other['min_output_tokens_per_second']>one['max_output_tokens_per_second']+max(one['max_output_tokens_per_second']-one['min_output_tokens_per_second'],other['max_output_tokens_per_second']-other['min_output_tokens_per_second'])
        assert bool(passes)==bool(conclusion['improvement_demonstrated'])
    bottleneck=[]
    baseline=next((r for r in rows if r['name']=='threshold-baseline-s1'),None)
    failing=sorted([r for r in rows if r['seqs']==1 and r['name'].startswith(('sweep','refine')) and not r['passes_limit'] and r['e2e_p99_s'] is not None],key=lambda r:r['offered_rps'])
    if baseline and failing:
        first=failing[0]
        bottleneck.append(f"At the lowest tested failing seqs=1 rate, {first['offered_rps']:.4f} requests/s, sampled running requests peaked at {first['max_running']:.0f} and waiting requests at {first['max_waiting']:.0f}. P99 TTFT changed from {baseline['ttft_p99_s']:.4f} s in the light baseline to {first['ttft_p99_s']:.4f} s. P99 ITL changed from {baseline['itl_p99_s']:.4f} s to {first['itl_p99_s']:.4f} s.")
        if first['max_waiting']>0 and first['ttft_p99_s']>baseline['ttft_p99_s']*1.5:
            bottleneck.append('The waiting queue and TTFT increase show admission queueing at the single-sequence limit. This identifies an observed scheduling limit at that load; it does not identify the physical GPU bottleneck.')
    if best[1] and best[4]:
        one,four=best[1],best[4]
        bottleneck.append(f"The passing exploratory seqs=4 point reached {four['output_tokens_per_second']:.2f} output tokens/s while sampled running requests peaked at {four['max_running']:.0f}, below its configured cap. Its per-request post-first-token P99 was {four['post_first_token_p99_s']:.4f} s, versus {one['post_first_token_p99_s']:.4f} s at the passing seqs=1 point. Larger configured caps were therefore not fully occupied at the selected rates. Four and eight produced essentially equal exploratory throughput; the short sweeps do not establish that four is superior to eight.")
    bottleneck.append('Kernel timings and memory-bandwidth counters were not collected. Neither a kernel bottleneck nor a memory-bandwidth bottleneck is established by this experiment.')
    selected_rows=[r for r in rows if r['name'] in selected_names]
    if selected_rows:
        memory=[r['host_mem_available_min_bytes'] for r in selected_rows if r['host_mem_available_min_bytes'] is not None]
        cache=[r['kv_cache_use_max'] for r in selected_rows if r['kv_cache_use_max'] is not None]
        preemptions=[r['preemptions_delta'] for r in selected_rows if r['preemptions_delta'] is not None]
        if memory and cache and len(preemptions)==len(selected_rows):
            bottleneck.append(f"Across selected confirmations, sampled host MemAvailable stayed at or above {min(memory)/1024**3:.2f} GiB, KV-cache use peaked at {100*max(cache):.2f}%, and observed preemption-counter increases totaled {sum(preemptions):.0f}. Memory-capacity pressure was not observed at these operating rates. Dedicated GPU memory.total/free readings are unavailable on this unified-memory platform.")
    bottleneck_text='\n\n'.join(bottleneck)
    table=['| Run | Seqs | Completed | Offered RPS | Achieved RPS | Output tok/s | P99 s | Pass |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for r in rows:
        if not r['name'].startswith(('confirm','threshold')):
            continue
        table.append(f"| {r['name']} | {r['seqs']} | {r['completed']} | {r['offered_rps']:.4f} | {r['achieved_rps']:.4f} | {r['output_tokens_per_second']:.2f} | {r['e2e_p99_s']:.4f} | {r['passes_limit']} |")
    restoration_note=''
    if (root/'restoration-initial-probe-failure.json').exists():
        restoration_note='The first generation probe immediately after worker readiness returned HTTP 404. Later inventory and generation probes returned HTTP 200 without further service mutations; restoration was then verified. The event is retained in restoration-initial-probe-failure.json. The exported rerun orchestrator now retries generation readiness for up to 120 seconds. The original measured orchestrator is preserved under scripts/recorded, with hashes and the operational-only change in script-provenance.json.'
    text=f'''# Controlled vLLM batching experiment

Status: {'complete' if conclusion.get('complete') else 'in progress; no final claim'}.

{outcome}

Frozen experimental P99 limit: {threshold['limit_s']:.6f} seconds, 1.2 times the warmed 1,000-request light-load max_num_seqs=1 baseline P99 of {threshold['baseline_p99_s']:.6f} seconds at {threshold['light_rate']:.6f} RPS. This is not a customer-derived SLO.

A single NVIDIA GB10 on spark-02 served the cached nvidia/Qwen3.6-35B-A3B-NVFP4 revision 1355db6a052410cfd62085d94b58866fd0f2c3c5 with NVFP4 weights, bfloat16 compute and FP8 KV. The pinned Dynamo 1.5.1 image contains vLLM 0.28.0. The test used its standalone vLLM API, bypassing Dynamo routing. Load came from controller. Qwen downtime was explicitly authorized; Muse and production routing were not changed.

Controls were 4,096-token context, 2,048 max batched tokens, 2 GiB KV budget, the image's default CUDA graph policy, no prefix caching and no speculative decoding. Only max_num_seqs varied across configurations. These results apply to this test configuration, not the original 262,144-token production configuration. Exact manifests and startup logs are saved under config-*.

The saved seed-20261015 dataset contains 30,000 unique prompts, verified by round-tripping the exact cached tokenizer to 512 tokens. Every measured response is checked for 512 input and exactly 128 output tokens. Requests set ignore_eos, min_tokens=128 and max_tokens=128. Each run uses a distinct dataset slice. Streaming log probabilities verify total generated token counts, and coalesced output events are retained and counted. Client-observed ITL is the P99 of token arrival gaps; tokens delivered in the same event share that observed arrival timestamp. P99 per-request average ITL is also saved, using last-token arrival minus first-token arrival divided by 127. Internal engine timings inside coalesced events are unavailable. End-to-end latency includes dispatch delay from the scheduled open-loop arrival. Completed-request output throughput includes final request drain. Raw records retain partial output token counts for failed requests; observed throughput across all statuses is saved separately. Failed, cancelled, wrong-length and timed-out requests remain in raw records and invalidate the point.

Best passing exploratory points (short runs; confirmation decides the result):

{chr(10).join(capacity_table)}

Calibration and individual confirmation runs:

{chr(10).join(table)}

Confirmation sample counts and run-to-run variability at the selected operating rates (all other attempts remain in the individual table):

{chr(10).join(variability)}

Stars in the plot are confirmation runs; crosses are invalid or latency-limit-violating points. All points and errors are in comparison.csv and raw/*/requests.jsonl. Percentiles and throughput were recomputed from those client records by report_batching_experiment.py.

![Throughput versus P99](throughput-versus-p99.png)

{bottleneck_text}

The telemetry contains sampled running/waiting requests, KV use, preemption counters, host memory and available GPU utilization, temperature and power. Missing values remain null. DCGM profiling fields are unavailable unless explicitly exported. Utilization alone does not establish a memory-bandwidth or kernel bottleneck.

Failures and exclusions:

{failure_text}

{rejected_text}

All latency-limit violations remain in comparison.csv, including completed requests at failed rates. Earlier setup failures and their restoration evidence remain in the parent directory and attempts 02–04. Those failures included an unavailable exporter command, an unsupported logging argument, a client namespace-selection bug and a coalesced-token validation assumption; their artifacts have not been deleted.

Confirmation decision and sample counts:

```json
{json.dumps(conclusion,indent=2)}
```

{restoration_note}

Reproduction requires controller access to the homelab context, the pinned model cached on spark-02, and explicit downtime authorization. Prepare a fresh output directory with original-dgd.json from the current DGD and workload.jsonl, then run:

```sh
python3 scripts/benchmarks/check_batching_open_loop.py
python3 scripts/benchmarks/run_batching_experiment.py --out <fresh-result-directory> --authorized-downtime
python3 scripts/benchmarks/report_batching_experiment.py --root <fresh-result-directory>
```

The orchestrator restores the original Qwen worker in a finally block and verifies original DGD specification, unchanged Service selectors, Qwen generation and Muse model-list health. Restoration evidence is in restoration.json. The selected confirmation run names are explicit in the decision JSON when a lower offered rate is retested. The comparison establishes a tested sustainable lower bound, with short exploratory runs bracketing higher rates; it does not establish an exact capacity maximum. The original production arguments are restored rather than promoting the test configuration. The immutable frozen threshold and its SHA256 record, pinned deployment manifests, startup logs, client environment, workload hash and script snapshots are retained alongside the raw results.
'''
    (root/'REPORT.md').write_text(text)
    print(f'Verified {len(rows)} runs from raw request records; report and plots written to {root}')


if __name__=='__main__':main()
