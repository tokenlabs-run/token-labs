#!/usr/bin/env python3
"""Run the authorized maintenance experiment and restore the original Qwen worker.

Requires explicit --authorized-downtime. Reuses the cached model and pinned image
on spark-02, with an isolated standalone vLLM API in a temporary namespace.
Public Service selectors and routing are never mutated. Qwen is unavailable
until restoration; Muse on spark-01 is not modified. Run from the controller.
"""
import argparse
import asyncio
import copy
import csv
import hashlib
import json
import pathlib
import signal
import subprocess
import sys
import time
import urllib.request

import numpy as np

from run_batching_open_loop import measure, metrics

CONTEXT = 'kubernetes-admin@kubernetes'
DGD = 'qwen36-nvfp4-dynamo-agg-151-epp'
NS = 'batching-experiment'
NAME = 'qwen-batching'
MODEL = 'nvidia/Qwen3.6-35B-A3B-NVFP4'
REVISION = '1355db6a052410cfd62085d94b58866fd0f2c3c5'
IMAGE = 'nvcr.io/nvidia/ai-dynamo/vllm-runtime:1.5.1@sha256:2b224a823d52a198ec0eeb0e3e4f5cf26cd8a7fc2e9812ee16204b6b1e974870'


def k(*args, data=None):
    r = subprocess.run(['kubectl','--context',CONTEXT,*args],input=data,text=True,capture_output=True,timeout=90)
    if r.returncode:
        raise RuntimeError(f'kubectl {args}: {r.stderr}')
    return r.stdout


def get(kind, namespace=None, name=None):
    return json.loads(k(*(['-n',namespace] if namespace else []),'get',kind,*([name] if name else ([] if namespace else ['-A'])),'-o','json'))


def write(path, obj):
    pathlib.Path(path).write_text(json.dumps(obj,indent=2)+'\n')


class ConfigurationBlocked(RuntimeError):
    pass


def wait_until(fn, seconds, message):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            result = fn()
            if result:
                return result
        except Exception as e:
            if isinstance(e, ConfigurationBlocked):
                raise
            last = str(e)
        time.sleep(5)
    raise TimeoutError(f'{message}: {last}')


def selectors():
    return {s['metadata']['name']:s['spec'].get('selector') for s in get('services','token-labs')['items']}


def worker_pods():
    return [p for p in get('pods','token-labs')['items'] if p['metadata'].get('labels',{}).get('nvidia.com/dynamo-graph-deployment-name') == DGD and p['metadata'].get('labels',{}).get('nvidia.com/dynamo-component') == 'VllmWorker' and p['status']['phase'] not in ['Succeeded','Failed']]


def test_pods():
    pods = get('pods',NS)['items']
    if any(p['metadata']['namespace'] != NS for p in pods):
        raise RuntimeError('Namespace isolation check failed')
    return pods


def manifest(seqs):
    args = ['--model', '/model-cache/hub/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/'+REVISION, '--served-model-name',MODEL,'--revision',REVISION,'--tokenizer-revision',REVISION,'--trust-remote-code','--dtype','bfloat16','--tensor-parallel-size','1','--max-model-len','4096','--max-num-seqs',str(seqs),'--max-num-batched-tokens','2048','--gpu-memory-utilization','0.70','--kv-cache-memory-bytes','2147483648','--kv-cache-dtype','fp8','--no-enable-prefix-caching','--moe-backend','marlin','--attention-backend','flashinfer','--block-size','128','--generation-config','vllm','--host','0.0.0.0','--port','8000','--no-enable-log-requests']
    pod = {'metadata':{'labels':{'app':NAME}},'spec':{'nodeSelector':{'kubernetes.io/hostname':'spark-02'},'tolerations':[{'key':'nvidia.com/gpu','operator':'Exists','effect':'NoSchedule'}],'terminationGracePeriodSeconds':30,'containers':[{'name':'vllm','image':IMAGE,'imagePullPolicy':'IfNotPresent','command':['python3','-m','vllm.entrypoints.openai.api_server'],'args':args,'env':[{'name':'HF_HOME','value':'/model-cache'},{'name':'HF_HUB_OFFLINE','value':'1'},{'name':'VLLM_WORKER_MULTIPROC_METHOD','value':'spawn'},{'name':'PYTHONUNBUFFERED','value':'1'}],'resources':{'requests':{'cpu':'4','memory':'32Gi','nvidia.com/gpu':'1'},'limits':{'cpu':'12','memory':'112Gi','nvidia.com/gpu':'1'}},'ports':[{'containerPort':8000}],'startupProbe':{'httpGet':{'path':'/health','port':8000},'periodSeconds':10,'failureThreshold':180},'readinessProbe':{'httpGet':{'path':'/health','port':8000},'periodSeconds':5},'volumeMounts':[{'name':'cache','mountPath':'/model-cache'},{'name':'shm','mountPath':'/dev/shm'}]}],'volumes':[{'name':'cache','hostPath':{'path':'/home/nvidia/.cache/huggingface','type':'Directory'}},{'name':'shm','emptyDir':{'medium':'Memory','sizeLimit':'16Gi'}}]}}
    return {'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':NAME,'namespace':NS},'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':{'app':NAME}},'template':pod}}


class Experiment:
    def __init__(self, out):
        self.out = out
        self.rows = [json.loads(x) for x in (out/'workload.jsonl').open()]
        self.offset = 0
        self.runs = []
        self.seqs = None
        self.url = None
        self.telemetry = None
        self.original = None
        self.scaled = False
        self.ns_created = False
        self.baseline_limit = None

    def configure(self, seqs):
        print(f'CONFIGURE max_num_seqs={seqs}',flush=True)
        if self.seqs is not None:
            k('-n',NS,'scale','deployment',NAME,'--replicas=0')
            wait_until(lambda:not test_pods(),180,'test worker termination')
        gpu_pods = []
        for p in get('pods')['items']:
            if p['spec'].get('nodeName') == 'spark-02' and p['status']['phase'] not in ['Failed','Succeeded']:
                if any(int(c.get('resources',{}).get('limits',{}).get('nvidia.com/gpu',0)) for c in p['spec']['containers']):
                    gpu_pods.append(p['metadata']['namespace']+'/'+p['metadata']['name'])
        with urllib.request.urlopen('http://192.168.1.77:9100/metrics',timeout=10) as response:
            memory = response.read().decode()
        available = int(float(next(x.split()[1] for x in memory.splitlines() if x.startswith('node_memory_MemAvailable_bytes '))))
        feasibility = {'seqs':seqs,'time':time.time(),'gpu_consumers':gpu_pods,'host_mem_available_bytes':available,'minimum_host_mem_available_bytes':48*1024**3,'kv_cache_memory_bytes':2147483648,'requested_gpu':1,'node':'spark-02'}
        feasibility['feasible'] = not gpu_pods and available > 48*1024**3
        d = self.out/f'config-{seqs}'
        d.mkdir(exist_ok=True)
        write(d/f'feasibility-{time.time_ns()}.json',feasibility)
        if not feasibility['feasible']:
            raise ConfigurationBlocked(f'Unsafe configuration blocked: {feasibility}')
        obj = manifest(seqs)
        write(d/'deployment.json',obj)
        k('apply','-f','-',data=json.dumps(obj))
        self.seqs = seqs
        def ready():
            pods = test_pods()
            if not pods:
                return None
            p = pods[0]
            if any(c.get('restartCount',0)>0 for c in p['status'].get('containerStatuses',[])):
                write(d/'startup-failure-pod.json',p)
                try:
                    logs = k('-n',NS,'logs',p['metadata']['name'],'--previous','--tail=200')
                except RuntimeError as error:
                    logs = str(error)
                (d/'startup-failure.log').write_text(logs)
                raise ConfigurationBlocked('test worker restarted')
            if all(c.get('ready') for c in p['status'].get('containerStatuses',[])) and p['status'].get('containerStatuses'):
                return p
            return None
        p = wait_until(ready,1800,'vLLM readiness')
        write(d/f'pod-{time.time_ns()}.json',p)
        runtime = k('-n',NS,'exec',p['metadata']['name'],'--','python3','-c',
                    "import importlib.metadata,subprocess; print('vllm',importlib.metadata.version('vllm')); print(subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total,memory.free,utilization.gpu,temperature.gpu,power.draw','--format=csv'],text=True))")
        (d/f'runtime-{time.time_ns()}.txt').write_text(runtime)
        (d/f'startup-{time.time_ns()}.log').write_text(k('-n',NS,'logs',p['metadata']['name']))
        self.url = 'http://'+p['status']['podIP']+':8000'
        self.telemetry = [self.url+'/metrics','http://10.244.1.15:9400/metrics','http://192.168.1.77:9100/metrics']
        # The same fixed settings, including the default graph policy and the 2 GiB KV budget,
        # are used in all four arms. Prefix caching and speculative decoding are off.
        warm = self.run(f'warm-{seqs}-{len(self.runs)}',.5,16)
        if not warm['valid']:
            raise RuntimeError('Warmup failed validation')

    def run(self, name, rate, count):
        if self.offset+count>len(self.rows):
            raise RuntimeError('Dataset exhausted; refusing prompt reuse')
        def idle():
            with urllib.request.urlopen(self.url+'/metrics',timeout=5) as response:
                current = metrics(response.read().decode())
            return current.get('vllm:num_requests_running') == 0 and current.get('vllm:num_requests_waiting') == 0
        wait_until(idle,120,'previous workload did not drain')
        time.sleep(2)
        wait_until(idle,120,'worker not idle before measurement')
        print(f'RUN {name} seqs={self.seqs} offered_rps={rate:.6f} count={count} offset={self.offset}',flush=True)
        dataset = self.rows[self.offset:self.offset+count]
        self.offset += count
        write(self.out/'cursor.json',{'offset':self.offset})
        summary = asyncio.run(measure(self.url,MODEL,dataset,rate,count,self.out/'raw'/name,self.telemetry,timeout=60,seqs=self.seqs))
        summary.update({'name':name,'offset':self.offset-count})
        summary['passes_limit'] = bool(summary['valid'] and self.baseline_limit is not None and summary['e2e_p99_s'] <= self.baseline_limit)
        self.runs.append(summary)
        write(self.out/'runs.json',self.runs)
        print('RESULT '+json.dumps(summary),flush=True)
        return summary

    def sweep(self, seqs, light_rate):
        if self.seqs != seqs:
            self.configure(seqs)
        low = None
        high = None
        rate = light_rate
        results = []
        for step in range(20):
            count = max(80,min(300,int(rate*90)))
            r = self.run(f'sweep-s{seqs}-{step}',rate,count)
            results.append(r)
            if not r['passes_limit']:
                high = rate
                break
            low = rate
            rate *= 1.35
        if low is not None and high is not None:
            for step in range(3):
                rate = (low+high)/2
                r = self.run(f'refine-s{seqs}-{step}',rate,max(100,min(300,int(rate*120))))
                results.append(r)
                if r['passes_limit']:
                    low = rate
                else:
                    high = rate
        passing = [r for r in results if r['passes_limit']]
        return max(passing,key=lambda r:r['output_tokens_per_second']) if passing else None

    def restore(self):
        print('RESTORE original Qwen worker',flush=True)
        if self.ns_created:
            k('delete','namespace',NS,'--wait=false')
            wait_until(lambda:not [p for p in get('pods')['items'] if p['metadata']['namespace']==NS],240,'test pods deleted')
        if self.scaled:
            original_worker = self.original['spec']['components'][1]
            patch = [{'op':'replace','path':'/spec/components/1/replicas','value':original_worker['replicas']}]
            k('-n','token-labs','patch','dynamographdeployment',DGD,'--type=json','-p',json.dumps(patch))
            wait_until(lambda:any(all(c.get('ready') for c in p['status'].get('containerStatuses',[])) and p['status'].get('containerStatuses') for p in worker_pods()),1800,'original Qwen worker readiness')
        current = get('dynamographdeployment','token-labs',DGD)
        request = urllib.request.Request('http://10.109.45.176:8000/v1/chat/completions',data=json.dumps({'model':MODEL,'messages':[{'role':'user','content':'Reply with OK.'}],'max_tokens':8,'temperature':0}).encode(),headers={'Content-Type':'application/json'})
        def generated():
            with urllib.request.urlopen(request,timeout=15) as response:
                result = json.load(response)
            if not result.get('choices') or result.get('usage',{}).get('completion_tokens',0)<=0:
                raise RuntimeError('Original Qwen generation not ready after worker readiness')
            return result
        qwen = wait_until(generated,120,'original Qwen generation after model discovery')
        with urllib.request.urlopen('http://10.98.54.109:8000/v1/models',timeout=15) as r:
            muse = json.load(r)
        health = {'restored_at_epoch':time.time(),'dgd_spec_matches_original':current['spec']==self.original['spec'],'service_selectors_unchanged':selectors()==json.loads((self.out/'original-service-selectors.json').read_text()),'qwen_generation_response':qwen,'muse_model_list':muse,'worker_pods':worker_pods()}
        write(self.out/'restoration.json',health)
        if not health['dgd_spec_matches_original'] or not health['service_selectors_unchanged']:
            raise RuntimeError('Restoration verification mismatch')
        print('RESTORATION VERIFIED',flush=True)

    def execute(self):
        if get('dynamographdeployment','token-labs',DGD)['spec'] != json.loads((self.out/'original-dgd.json').read_text())['spec']:
            raise RuntimeError('Original DGD changed since inspection')
        try:
            k('get','namespace',NS)
        except RuntimeError:
            pass
        else:
            raise RuntimeError('Experiment namespace already exists; refusing to overwrite')
        with urllib.request.urlopen('http://192.168.1.77:9100/metrics',timeout=10) as response:
            if 'node_memory_MemAvailable_bytes ' not in response.read().decode():
                raise RuntimeError('Host memory telemetry unavailable before maintenance')
        self.original = get('dynamographdeployment','token-labs',DGD)
        write(self.out/'original-dgd.json',self.original)
        write(self.out/'original-service-selectors.json',selectors())
        write(self.out/'nodes-before.json',get('nodes'))
        write(self.out/'pods-before.json',get('pods'))
        write(self.out/'authorization.json',{'user_message':'Authorizing downtime for this perf config updates','scope':'Temporarily stop Qwen worker on spark-02; reuse its GPU for isolated batching experiment; restore original; leave drivers and routing unchanged','time':time.time()})
        try:
            self.scaled = True
            k('-n','token-labs','patch','dynamographdeployment',DGD,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec/components/1/replicas','value':0}]))
            wait_until(lambda:not worker_pods(),240,'production worker termination')
            k('create','namespace',NS)
            self.ns_created = True
            self.configure(1)
            pilot = self.run('pilot-s1',.5,20)
            if not pilot['valid']:
                raise RuntimeError('Pilot validation failed')
            light_rate = .5/pilot['e2e_p50_s']
            baseline = self.run('threshold-baseline-s1',light_rate,1000)
            if not baseline['valid']:
                raise RuntimeError('Threshold baseline validation failed')
            self.baseline_limit = 1.2*baseline['e2e_p99_s']
            with (self.out/'frozen-threshold.json').open('x') as f:
                json.dump({'experimental_threshold_not_customer_slo':True,'baseline_run':baseline['name'],'baseline_completed':baseline['completed'],'baseline_p99_s':baseline['e2e_p99_s'],'multiplier':1.2,'limit_s':self.baseline_limit,'frozen_at_epoch':time.time(),'light_rate':light_rate},f,indent=2)
            print(f'FROZEN P99 LIMIT {self.baseline_limit:.6f} seconds',flush=True)
            best = {}
            for seqs in [1,2,4,8]:
                try:
                    best[seqs] = self.sweep(seqs,light_rate)
                except ConfigurationBlocked as error:
                    write(self.out/f'blocked-{seqs}.json',{'seqs':seqs,'reason':str(error),'time':time.time()})
                    if seqs == 1:
                        raise
                    k('-n',NS,'scale','deployment',NAME,'--replicas=0')
                    wait_until(lambda:not test_pods(),180,'blocked configuration cleanup')
                    self.seqs = None
                    best[seqs] = None
                write(self.out/'exploratory-best.json',best)
            if not best[1]:
                raise RuntimeError('No max_num_seqs=1 sweep result passes the frozen limit')
            candidates = [s for s in [2,4,8] if best[s]]
            candidate = max(candidates,key=lambda s:best[s]['output_tokens_per_second']) if candidates else None
            confirms = {1:[]}
            if candidate:
                confirms[candidate]=[]
            for repeat in range(3):
                order = [1,candidate] if candidate else [1]
                if repeat%2:
                    order.reverse()
                for seqs in order:
                    if self.seqs != seqs:
                        self.configure(seqs)
                    r = self.run(f'confirm-s{seqs}-r{repeat+1}',best[seqs]['offered_rps'],1000)
                    confirms[seqs].append(r)
            stats = {}
            for seqs, runs in confirms.items():
                rates = [r['output_tokens_per_second'] for r in runs]
                stats[seqs] = {'completed':sum(r['completed'] for r in runs),'every_run_passes':all(r['passes_limit'] for r in runs),'mean_output_tokens_per_second':float(np.mean(rates)),'std_output_tokens_per_second':float(np.std(rates,ddof=1)),'min_output_tokens_per_second':min(rates),'max_output_tokens_per_second':max(rates),'p99_seconds':[r['e2e_p99_s'] for r in runs]}
            improvement = None
            if candidate:
                baseline_stats=stats[1];candidate_stats=stats[candidate]
                improvement = candidate_stats['mean_output_tokens_per_second']/baseline_stats['mean_output_tokens_per_second']-1
                passing_s1 = [r['output_tokens_per_second'] for r in self.runs if r['seqs']==1 and r['passes_limit'] and r['name'].startswith(('sweep','refine','confirm'))]
                best_s1 = max(passing_s1)
                passes = baseline_stats['every_run_passes'] and candidate_stats['every_run_passes'] and candidate_stats['completed']>=3000 and candidate_stats['min_output_tokens_per_second']>=1.1*best_s1 and candidate_stats['min_output_tokens_per_second']>baseline_stats['max_output_tokens_per_second']+max(baseline_stats['max_output_tokens_per_second']-baseline_stats['min_output_tokens_per_second'],candidate_stats['max_output_tokens_per_second']-candidate_stats['min_output_tokens_per_second'])
            else:
                passes=False
            write(self.out/'conclusion.json',{'candidate':candidate,'confirmation_stats':stats,'mean_improvement_fraction':improvement,'improvement_demonstrated':passes,'frozen_limit_seconds':self.baseline_limit,'rule':'Every confirmation passes; candidate minimum throughput >=1.1 times best passing seqs=1 result and exceeds observed throughput ranges','complete':True})
        except BaseException as e:
            write(self.out/'experiment-failure.json',{'time':time.time(),'type':type(e).__name__,'message':str(e)})
            raise
        finally:
            self.restore()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=pathlib.Path,required=True)
    p.add_argument('--authorized-downtime',action='store_true',required=True)
    a=p.parse_args()
    if (a.out/'authorization.json').exists():
        raise SystemExit('Use a new output directory and fresh original-dgd.json; existing artifacts are immutable')
    def terminate(signum, frame):
        raise KeyboardInterrupt(f'Signal {signum}; restoring')
    signal.signal(signal.SIGTERM,terminate)
    experiment=Experiment(a.out)
    try:
        experiment.execute()
    finally:
        if experiment.runs:
            fields=['name','seqs','requested','completed','offered_rps','actual_dispatch_rps','achieved_rps','output_tokens_per_second','e2e_p50_s','e2e_p95_s','e2e_p99_s','ttft_p99_s','itl_p99_s','errors','timeouts','cancelled','max_running','max_waiting','valid','passes_limit']
            with (a.out/'comparison.csv').open('w') as f:
                w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(experiment.runs)


if __name__=='__main__':
    main()
