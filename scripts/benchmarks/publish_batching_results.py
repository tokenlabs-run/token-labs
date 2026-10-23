#!/usr/bin/env python3
"""Build a benchmark website entry only after complete confirmation and restoration."""
import argparse
import datetime
import hashlib
import html
import json
import pathlib
import shutil
import tarfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=pathlib.Path,required=True)
    p.add_argument('--site',type=pathlib.Path,required=True,help='Existing docs directory in an isolated publication checkout')
    a=p.parse_args();root=a.root.resolve();site=a.site.resolve()
    decision=json.loads((root/'conclusion.json').read_text())
    restored=json.loads((root/'restoration.json').read_text())
    threshold=json.loads((root/'frozen-threshold.json').read_text())
    rows=json.loads((root/'verified-runs.json').read_text())
    config=json.loads((root/'benchmark-config.json').read_text())
    assert decision['complete'] and restored['dgd_spec_matches_original'] and restored['service_selectors_unchanged']
    assert decision['frozen_limit_seconds']==threshold['limit_s']
    assert all(s['completed']>=3000 for s in decision['confirmation_stats'].values())
    selected={name for names in decision['selected_confirmation_runs'].values() for name in names}
    assert len(selected)==6
    confirmed=[r for r in rows if r['name'] in selected]
    assert len(confirmed)==6 and all(r['completed']>=1000 for r in confirmed)
    assert all(r['errors']==r['timeouts']==r['cancelled']==0 for r in confirmed) or not decision['improvement_demonstrated']
    if decision['improvement_demonstrated']:assert all(r['passes_limit'] for r in confirmed)
    baseline=next(r for r in rows if r['name']=='threshold-baseline-s1')
    assert baseline['completed']>=1000 and threshold['limit_s']==1.2*baseline['e2e_p99_s']
    workload_hash=hashlib.sha256((root/'workload.jsonl').read_bytes()).hexdigest()
    assert workload_hash==config['workload_sha256']
    slug='vllm-batching-2026-10-15';dest=site/'results'/slug;dest.mkdir(parents=True,exist_ok=True)
    public_config={k:config[k] for k in ['model','model_revision','image','vllm_version','weight_precision','compute_dtype','kv_cache_dtype','max_num_seqs','max_num_batched_tokens','max_model_len','prefix_caching','speculative_decoding','kv_cache_memory_bytes','seed','workload_sha256','dataset_count','arrivals']}
    public_config['hardware']={k:v for k,v in config['hardware'].items() if k in ['accelerator','gpus_per_worker','cpu_cores','node_memory_capacity','architecture','driver_version','memory_reporting']}
    public_fields=['name','seqs','requested','launched','completed','errors','timeouts','cancelled','offered_rps','actual_dispatch_rps','achieved_rps','output_tokens_per_second','observed_output_tokens_per_second_all_statuses','e2e_p50_s','e2e_p95_s','e2e_p99_s','ttft_p99_s','itl_p99_s','per_request_mean_itl_p99_s','coalesced_events','length_invalid','token_timing_invalid','dispatch_lag_p99_s','output_length_counts','max_running','max_waiting','kv_cache_use_max','preemptions_delta','gpu_util_mean_pct','gpu_temp_max_c','gpu_power_mean_w','host_mem_available_min_bytes','valid','passes_limit']
    public_rows=[{k:r[k] for k in public_fields if k in r} for r in rows]
    summary={'study':slug,'status':'complete','conclusion':decision,'calibration':threshold,'configuration':public_config,'runs':public_rows,'restoration':{'verified':True,'restored_at_epoch':restored['restored_at_epoch'],'original_configuration_restored':True,'routing_selectors_unchanged':True,'qwen_generation_verified':bool(restored['qwen_generation_response']['choices']),'muse_model_list_verified':bool(restored['muse_model_list']['data'])},'evidence_scope':'Public aggregates and benchmark methodology only. Raw per-request records, telemetry, deployment configuration, workload and scripts are retained in the local experiment artifacts.'}
    (dest/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    for name in ['comparison.csv','throughput-versus-p99.png','throughput-versus-p99.svg']:
        shutil.copy2(root/name,dest/name)
    bundle=root/'reproduction-evidence.tar.gz'
    public_bundle=dest/bundle.name
    if public_bundle.exists():public_bundle.unlink()
    with tarfile.open(bundle,'w:gz',compresslevel=6) as archive:
        for name in ['workload.jsonl','frozen-threshold.json','benchmark-config.json','client-environment.txt','conclusion.json','selected-confirmation-plan.json','comparison.csv','verified-runs.json','REPORT.md']:
            archive.add((root/name).resolve(),arcname=name)
        for name in ['setup-and-rejected-attempts.json','restoration-initial-probe-failure.json','script-provenance.json','post-restoration-health.json','RERUN.md']:
            if (root/name).exists():archive.add(root/name,arcname=name)
        for run in sorted((root/'raw').iterdir()):
            for name in ['requests.jsonl','telemetry.jsonl','run-config.json','summary.json']:
                if (run/name).exists():archive.add(run/name,arcname='raw/'+run.name+'/'+name)
        for directory in sorted(root.glob('config-*')):
            for file in sorted(directory.iterdir()):
                if file.name=='deployment.json' or file.name.startswith(('feasibility-','runtime-','startup-')):
                    archive.add(file,arcname=directory.name+'/'+file.name)
        archive.add(root/'scripts',arcname='scripts')
    assert bundle.stat().st_size<95*1024**2,'Split the evidence bundle before publishing a file near GitHub limits'
    (dest/'REPORT.md').write_text(f'''# Controlled vLLM batching results

Increasing max_num_seqs from 1 to {decision['candidate']} changed confirmed output throughput from {decision['confirmation_stats']['1']['mean_output_tokens_per_second']:.3f} to {decision['confirmation_stats'][str(decision['candidate'])]['mean_output_tokens_per_second']:.3f} tokens/second, a {100*decision['mean_improvement_fraction']:.1f}% increase. All six selected confirmations passed; each configuration completed 3,000 requests.

The experimental P99 limit was frozen at {threshold['limit_s']:.6f} seconds, 1.2 times the 1,000-request light-load baseline P99 of {threshold['baseline_p99_s']:.6f} seconds. It is not a customer-derived SLO.

Each request had 512 verified input and exactly 128 generated tokens. A custom aiohttp client generated open-loop arrivals independently of request completion. It had no client concurrency cap. Warmup preceded measurements. Prefix caching and speculative decoding were off; context 4,096, batched-token budget 2,048 and KV memory budget 2 GiB were fixed. The standalone single-worker path bypassed framework routing. The model revision, precision, image digest, vLLM version and hardware are disclosed in summary.json. These findings apply to this synthetic workload and test configuration.

The first candidate confirmation at 0.690356 RPS reached 88.335 tokens/second but failed with P99 2.288324 seconds. It remains in the aggregate exports and plot. The final candidate confirmations used 0.625 RPS without changing the limit. Caps 2 and 8 have short exploratory results only and were not confirmed. Four and eight were essentially tied in exploration; this study does not establish an optimal cap.

Single-sequence waiting requests and TTFT increased at failing loads, showing admission queueing. Kernel timings and memory-bandwidth profiling were unavailable; neither physical bottleneck is established. Missing telemetry fields remain unavailable rather than zero.

Every run is in comparison.csv and summary.json, including latency failures and five safety cancellations during a backlog stop. No selected confirmation had errors or timeouts. Output throughput includes drain. End-to-end latency includes dispatch delay; percentiles were recomputed from individual client records. Client-observed ITL uses token arrival gaps; coalesced tokens share an event timestamp, and a separate P99 of per-request mean ITL is disclosed.

The original configuration and routing were restored, and model generation and service health were verified. An initial readiness probe returned HTTP 404 and passed on a subsequent read-only retry; the rerun orchestrator now waits for generation readiness.

Public artifacts contain sanitized aggregate results, methodology and the plot. Full raw client records, telemetry, workload, configurations and rerunnable scripts remain in the local experiment directory.
''')
    hashes={file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in dest.iterdir() if file.is_file() and file.name!='SHA256SUMS'}
    (dest/'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name,digest in sorted(hashes.items())))
    one=decision['confirmation_stats']['1'];candidate=decision['confirmation_stats'][str(decision['candidate'])]
    outcome=f"Confirmed output throughput increased {100*decision['mean_improvement_fraction']:.1f}%" if decision['improvement_demonstrated'] else 'A qualifying throughput improvement was not established'
    evidence='results/'+slug+'/'
    def esc(value):return html.escape(str(value))
    aggregate=[]
    for seqs,stats in decision['confirmation_stats'].items():
        rates=[r['offered_rps'] for r in confirmed if r['seqs']==int(seqs)]
        aggregate.append(f"<tr><td>{esc(seqs)}</td><td>{rates[0]:.4f}</td><td>{stats['completed']:,}</td><td>{stats['mean_output_tokens_per_second']:.3f} ± {stats['std_output_tokens_per_second']:.3f}</td><td>{min(stats['p99_seconds']):.4f}–{max(stats['p99_seconds']):.4f}</td><td>{'Pass' if stats['every_run_passes'] else 'Fail'}</td></tr>")
    individual=[]
    for r in sorted([r for r in rows if r['name'].startswith('confirm')],key=lambda r:(r['seqs'],r['offered_rps'],r['name'])):
        individual.append(f"<tr><td>{esc(r['name'])}</td><td>{r['offered_rps']:.4f}</td><td>{r['completed']:,}</td><td>{r['output_tokens_per_second']:.3f}</td><td>{r['e2e_p99_s']:.4f}</td><td>{'Pass' if r['passes_limit'] else 'Fail'}</td></tr>")
    exploratory=[]
    for seqs in [1,2,4,8]:
        points=[r for r in rows if r['seqs']==seqs and r['name'].startswith(('sweep','refine')) and r['passes_limit']]
        if points:
            r=max(points,key=lambda r:r['output_tokens_per_second'])
            exploratory.append(f"<tr><td>{seqs}</td><td>{r['offered_rps']:.4f}</td><td>{r['output_tokens_per_second']:.3f}</td><td>{r['e2e_p99_s']:.4f}</td><td>{r['completed']}</td></tr>")
    restored_at=datetime.datetime.fromtimestamp(restored['restored_at_epoch'],datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    failures=sum(r['errors'] for r in rows);timeouts=sum(r['timeouts'] for r in rows);cancelled=sum(r['cancelled'] for r in rows)
    section=f'''<!-- BEGIN {slug} -->
<section class="section" id="{slug}" aria-labelledby="{slug}-title">
<h2 class="section-title" id="{slug}-title">Qwen3.6 NVFP4 on one DGX Spark under a fixed P99 limit</h2>
<p class="section-desc">Study started 2026-10-15 UTC · service restored {restored_at}.</p>
<p class="section-desc"><strong>{outcome}.</strong> The selected comparison uses max_num_seqs=1 and {decision['candidate']}, with three 1,000-request confirmations each. The experimental P99 limit is <strong>{threshold['limit_s']:.6f} seconds</strong>, frozen at 1.2 times the warmed 1,000-request light-load baseline. This is an experimental threshold, not a customer-derived SLO.</p>
<div class="table-wrap" style="overflow-x:auto;margin-bottom:1rem"><table><thead><tr><th>max_num_seqs</th><th>Offered RPS</th><th>Completed</th><th>Output tok/s mean ± SD</th><th>Run P99 range s</th><th>All three runs</th></tr></thead><tbody>{''.join(aggregate)}</tbody></table></div>
<p class="section-desc">Single-worker standalone vLLM 0.28.0 on one NVIDIA GB10; nvidia/Qwen3.6-35B-A3B-NVFP4, NVFP4 weights, bfloat16 compute and FP8 KV. Every completed request was checked for 512 input and exactly 128 output tokens, using unique seeded prompts, ignore_eos and fixed output limits. A custom Python aiohttp client generated deterministic open-loop arrivals from controller, with no client concurrency cap. Measurements are from per-request records, not AIPerf exports or server latency histograms.</p>
<img src="{evidence}throughput-versus-p99.png" alt="Output tokens per second versus per-request P99 latency for sequence caps 1, 2, 4 and 8, including the frozen limit and failed higher-rate confirmation" style="display:block;width:100%;height:auto;background:white;border-radius:8px;margin:1rem 0" loading="lazy"/>
<p class="section-desc">Context length 4,096, max_num_batched_tokens=2,048, 2 GiB KV budget, prefix caching off and speculative decoding off were fixed; only max_num_seqs varied. The image and model revision are pinned in the evidence. These findings apply to this workload and test configuration, rather than the original 262,144-token production configuration.</p>
<details><summary>Four-setting exploratory search</summary><p class="section-desc">Best passing short-run points before confirmation. Caps 2 and 8 were not confirmed with 3,000 requests; these rows are provisional and do not establish sustainable capacity. Caps 4 and 8 were essentially tied. The fastest short-run cap 4 point subsequently failed its 1,000-request confirmation; the confirmed lower-rate result appears above.</p><div class="table-wrap" style="overflow-x:auto;margin:1rem 0"><table><thead><tr><th>max_num_seqs</th><th>Offered RPS</th><th>Output tok/s</th><th>P99 s</th><th>Completed</th></tr></thead><tbody>{''.join(exploratory)}</tbody></table></div></details>
<details><summary>Individual confirmations including the rejected higher offered rate</summary><div class="table-wrap" style="overflow-x:auto;margin:1rem 0"><table><thead><tr><th>Run</th><th>Offered RPS</th><th>Completed</th><th>Output tok/s</th><th>P99 s</th><th>Frozen limit</th></tr></thead><tbody>{''.join(individual)}</tbody></table></div></details>
<p class="section-desc">The initial 0.690356 RPS candidate completed 1,000 requests at 88.335 output tokens/s but failed the frozen limit with P99 2.288324 s. It remains in the table, plot and raw evidence. The selected lower-rate candidate uses {decision['candidate_offered_rps']:.3f} RPS and a distinct confirmation series. All selected confirmations must meet the same limit with no errors, timeouts or sustained backlog growth; improvement must exceed 10% over the best passing single-sequence result and observed run-to-run variation.</p>
<p class="section-desc">At the failing single-sequence loads, waiting requests and increased TTFT show admission queueing. At the passing multi-sequence loads, sampled running requests reached two. Kernel timings and memory-bandwidth profiling were unavailable, so this study does not establish either physical bottleneck. Across all retained runs: {failures} request errors, {timeouts} timeouts and {cancelled} safety cancellations, including failed exploratory points. Aggregate telemetry and metric definitions are in the machine-readable export. Full raw records remain in the local experiment artifacts.</p>
<p class="section-desc"><strong>Service restored:</strong> the original Qwen configuration and unchanged routing selectors were verified, Qwen generated successfully, and Muse health passed. The benchmark configuration was not promoted.</p>
<p class="section-desc"><a href="{evidence}summary.json">Machine-readable results and provenance</a> · <a href="{evidence}comparison.csv">Every run CSV</a> · <a href="{evidence}REPORT.md">Full report</a> · <a href="{evidence}SHA256SUMS">SHA256 checksums</a></p>
</section>
<!-- END {slug} -->
'''
    section=section.replace('<table>','<table style="width:100%;border-collapse:collapse;text-align:left">').replace('<th>','<th style="padding:.5rem .7rem;white-space:nowrap">').replace('<td>','<td style="padding:.5rem .7rem">')
    page=site/'benchmark-results.html';text=page.read_text();begin=f'<!-- BEGIN {slug} -->';end=f'<!-- END {slug} -->'
    if begin in text:
        start=text.index(begin);stop=text.index(end,start)+len(end);text=text[:start]+section.rstrip()+text[stop:]
    else:
        marker='<!-- ── Summary Stats ────────────────────────────────────── -->'
        assert text.count(marker)==1
        text=text.replace(marker,section+'\n'+marker)
    page.write_text(text)
    print(json.dumps({'section':slug,'local_evidence_bundle_bytes':bundle.stat().st_size,'destination':str(dest),'index':str(page)}))


if __name__=='__main__':main()
