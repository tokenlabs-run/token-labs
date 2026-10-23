#!/usr/bin/env python3
"""Confirm a lower offered rate after a failed operating point; retain the frozen limit."""
import argparse
import json
import os
import pathlib
import shutil
import signal
import time
import numpy as np
from run_batching_experiment import Experiment, CONTEXT, DGD, NS, k, get, write, wait_until, worker_pods, selectors


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=pathlib.Path,required=True)
    p.add_argument('--out',type=pathlib.Path,required=True)
    p.add_argument('--candidate-rate',type=float,required=True)
    p.add_argument('--authorized-downtime',action='store_true',required=True)
    a=p.parse_args();source=a.source.resolve();out=a.out.resolve()
    if out.exists():raise SystemExit('Fresh output directory required')
    restored=json.loads((source/'restoration.json').read_text())
    assert restored['dgd_spec_matches_original'] and restored['service_selectors_unchanged']
    original=json.loads((source/'original-dgd.json').read_text())
    assert get('dynamographdeployment','token-labs',DGD)['spec']==original['spec']
    assert not [x for x in get('namespaces')['items'] if x['metadata']['name']==NS]
    baseline=json.loads((source/'raw/confirm-s1-r1/summary.json').read_text())
    threshold=json.loads((source/'frozen-threshold.json').read_text())
    assert baseline['valid'] and baseline['completed']==1000 and baseline['e2e_p99_s']<=threshold['limit_s']
    assert 0<a.candidate_rate<.6903562609975488
    out.mkdir(parents=True);(out/'raw').mkdir()
    for name in ['original-dgd.json','original-service-selectors.json','frozen-threshold.json','client-environment.txt']:
        shutil.copy2(source/name,out/name)
    for name in ['frozen-threshold.sha256','exploratory-best.json']:
        if (source/name).exists():shutil.copy2(source/name,out/name)
    (out/'workload.jsonl').symlink_to(os.path.relpath((source/'workload.jsonl').resolve(),out))
    for folder in (source/'raw').iterdir():shutil.copytree(folder,out/'raw'/folder.name,copy_function=os.link)
    for folder in source.glob('config-*'):shutil.copytree(folder,out/folder.name)
    e=Experiment(out);e.original=original;e.offset=json.loads((source/'cursor.json').read_text())['offset'];e.baseline_limit=threshold['limit_s']
    e.runs=json.loads((source/'runs.json').read_text())
    baseline['name']='confirm-s1-r1'
    selected={1:[baseline],4:[]}
    write(out/'authorization.json',{'user_message':'Authorizing downtime for this perf config updates','continued_from':str(source),'candidate_rate':a.candidate_rate,'reason':'Higher offered-rate confirmation failed the unchanged P99 limit','preserved_frozen_limit_seconds':e.baseline_limit,'time':time.time()})
    write(out/'selected-confirmation-plan.json',{'baseline_retained':'confirm-s1-r1','candidate_rate':a.candidate_rate,'baseline_rate':baseline['offered_rps'],'order':[1,4,4,1,1,4],'remaining_order':[4,4,1,1,4],'retained_failed_operating_points':True})
    def terminate(signum,frame):raise KeyboardInterrupt(f'Signal {signum}; restoring')
    signal.signal(signal.SIGTERM,terminate)
    try:
        assert selectors()==json.loads((out/'original-service-selectors.json').read_text())
        e.scaled=True
        k('-n','token-labs','patch','dynamographdeployment',DGD,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec/components/1/replicas','value':0}]))
        wait_until(lambda:not worker_pods(),240,'production worker termination')
        k('create','namespace',NS);e.ns_created=True
        for seqs,repeat in [(4,1),(4,2),(1,2),(1,3),(4,3)]:
            if e.seqs!=seqs:e.configure(seqs)
            rate=a.candidate_rate if seqs==4 else baseline['offered_rps']
            r=e.run(f'confirm-s{seqs}-r{repeat}-lower-rate',rate,1000);selected[seqs].append(r)
        stats={}
        for seqs,runs in selected.items():
            rates=[r['output_tokens_per_second'] for r in runs]
            stats[seqs]={'completed':sum(r['completed'] for r in runs),'every_run_passes':all(r['valid'] and r['e2e_p99_s']<=e.baseline_limit for r in runs),'mean_output_tokens_per_second':float(np.mean(rates)),'std_output_tokens_per_second':float(np.std(rates,ddof=1)),'min_output_tokens_per_second':min(rates),'max_output_tokens_per_second':max(rates),'p99_seconds':[r['e2e_p99_s'] for r in runs]}
        one,four=stats[1],stats[4]
        best_one=max(r['output_tokens_per_second'] for r in e.runs if r['seqs']==1 and r['passes_limit'] and r['name'].startswith(('sweep','refine','confirm')))
        passes=all(x['every_run_passes'] and x['completed']>=3000 for x in stats.values()) and four['min_output_tokens_per_second']>=1.1*best_one and four['min_output_tokens_per_second']>one['max_output_tokens_per_second']+max(one['max_output_tokens_per_second']-one['min_output_tokens_per_second'],four['max_output_tokens_per_second']-four['min_output_tokens_per_second'])
        write(out/'conclusion.json',{'candidate':4,'candidate_offered_rps':a.candidate_rate,'confirmation_stats':stats,'selected_confirmation_runs':{s:[r['name'] for r in runs] for s,runs in selected.items()},'mean_improvement_fraction':four['mean_output_tokens_per_second']/one['mean_output_tokens_per_second']-1,'improvement_demonstrated':passes,'frozen_limit_seconds':e.baseline_limit,'best_passing_s1_output_tokens_per_second':best_one,'rule':'Every selected operating-point confirmation passes; all failed higher-rate attempts retained; candidate minimum >=1.1 times best passing seqs=1 and exceeds observed throughput ranges','complete':True})
    except BaseException as error:
        write(out/'experiment-failure.json',{'time':time.time(),'type':type(error).__name__,'message':str(error)})
        raise
    finally:e.restore()


if __name__=='__main__':main()
