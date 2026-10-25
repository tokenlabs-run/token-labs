#!/usr/bin/env python3
"""Switch only the stable aggregator selector after recorded validation passes."""
import argparse,json,pathlib,subprocess,urllib.request
p=argparse.ArgumentParser();p.add_argument('--evidence',type=pathlib.Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
k=['kubectl','--context=kubernetes-admin@kubernetes','-n','token-labs'];name='model-aggregator-qwen38-blue'
def read(kind,name):return json.loads(subprocess.check_output(k+['get',kind,name,'-o','json']))
for file in ['conformance.json','conformance-aggregator.json','gateway-private.json','overload.json']:
 d=json.loads((a.evidence/file).read_text());assert d['passed'],file+' failed'
capacity=json.loads((a.evidence/'capacity-c4.json').read_text());assert capacity['summary']['passed'] and capacity['elapsed_s']>=1800 and capacity['concurrency']==4
limits=json.loads((a.evidence/'capacity-acceptance.json').read_text())
assert capacity['summary']['p95_ttft_s']<=limits['max_p95_ttft_s'],'TTFT gate failed'
assert capacity['summary']['p95_e2e_s']<=limits['max_p95_e2e_s'],'End-to-end latency gate failed'
rows=[json.loads(s) for s in (a.evidence/'capacity-observation.jsonl').read_text().splitlines()]
assert rows[-1]['elapsed_s']>=1800 and all(r.get('ready') and not r.get('error') for r in rows),'Readiness observation failed'
ready_transitions={c['lastTransitionTime'] for r in rows for pod in r['pods'] for c in pod['conditions'] if c['type']=='Ready'}
assert len(ready_transitions)==1,'Readiness changed during observation'
assert all(c['restarts']==0 for r in rows for pod in r['pods'] for c in pod['containers']),'Worker restart observed'
assert all(n['conditions']['Ready']=='True' and all(n['conditions'].get(x)=='False' for x in ['DiskPressure','MemoryPressure','PIDPressure']) for r in rows for n in r['nodes']),'Node unhealthy'
assert all(r['gpu']['software_thermal_slowdown']=='Not Active' and r['gpu']['hardware_thermal_slowdown']=='Not Active' for r in rows),'Thermal throttling observed'
cache=[float(line.rsplit(' ',1)[1]) for r in rows for line in r['metrics'] if line.startswith('vllm:kv_cache_usage_perc{')]
assert len(cache)>=len(rows) and max(cache)<0.9,'KV cache saturation or missing metrics'
long=json.loads((a.evidence/'long-context.json').read_text());assert long['passed']
service=read('svc','model-aggregator');old=service['spec']['selector'];assert old=={'app':'model-aggregator-qwen-recovery'}
diag=read('svc',name)
with urllib.request.urlopen('http://'+diag['spec']['clusterIP']+':8000/v1/models',timeout=15) as r:models=json.load(r)
assert {m['id'] for m in models['data']}=={'nvidia/Qwen3.6-35B-A3B-NVFP4','nvidia/Qwen3.8-27B-NVFP4'}
slices=json.loads(subprocess.check_output(k+['get','endpointslices','-l','kubernetes.io/service-name='+name,'-o','json']))
endpoints=[e for s in slices['items'] for e in s.get('endpoints',[]) if e.get('conditions',{}).get('ready')]
assert len(endpoints)==1 and endpoints[0]['targetRef']['name'].startswith(name+'-')
assert read('deployment','model-aggregator-qwen-recovery')['status'].get('availableReplicas')==1,'Rollback aggregator unavailable'
(a.evidence/'aggregator-service-before.json').write_text(json.dumps(service,indent=2)+'\n')
(a.evidence/'aggregator-candidate-endpoints.json').write_text(json.dumps(slices,indent=2)+'\n')
patch=[{'op':'test','path':'/spec/selector','value':old},{'op':'replace','path':'/spec/selector','value':{'app':name}}]
(a.evidence/'aggregator-selector-patch.json').write_text(json.dumps(patch,indent=2)+'\n')
cmd=k+['patch','svc','model-aggregator','--type=json','-p',json.dumps(patch)]
subprocess.run(cmd+['--dry-run=server'],check=True)
if a.apply:subprocess.run(cmd,check=True)
