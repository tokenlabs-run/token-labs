#!/usr/bin/env python3
"""Verify completed observation evidence and current selectors before closing rollout."""
import argparse,datetime,json,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('--evidence',type=pathlib.Path,required=True);a=p.parse_args()
def read(name):return json.loads((a.evidence/name).read_text())
def lines(name):return [json.loads(s) for s in (a.evidence/name).read_text().splitlines()]
public=lines('public-observation.jsonl');hardware=lines('public-hardware-observation.jsonl')
assert public[-1]['elapsed_s']>=1800 and all(r['passed'] for r in public),'Public observation failed or incomplete'
assert hardware[-1]['elapsed_s']>=1800 and all(r.get('ready') and not r.get('error') for r in hardware),'Hardware observation failed or incomplete'
assert all(c['restarts']==0 for r in hardware for p in r['pods'] for c in p['containers'])
assert all(r['gpu']['software_thermal_slowdown']=='Not Active' and r['gpu']['hardware_thermal_slowdown']=='Not Active' for r in hardware)
assert all(n['conditions']['Ready']=='True' and all(n['conditions'].get(c)=='False' for c in ['DiskPressure','MemoryPressure','PIDPressure']) for r in hardware for n in r['nodes'])
assert len({c['lastTransitionTime'] for r in hardware for p in r['pods'] for c in p['conditions'] if c['type']=='Ready'})==1
for file in ['gateway-public.json','gateway-public-final.json','portal.json','portal-final.json','conformance.json','conformance-aggregator.json','long-context.json','cutover-stream.json']:
 assert read(file)['passed'],file
assert read('public-benchmark-c1.json')['summary']['passed']
k=['kubectl','--context=kubernetes-admin@kubernetes','-n','token-labs']
for name,selector in [('model-aggregator',{'app':'model-aggregator-qwen38-blue'}),('qwen38-nvfp4',{'token-labs/model-id':'qwen38-nvfp4','token-labs/slot':'blue'})]:
 d=json.loads(subprocess.check_output(k+['get','svc',name,'-o','json']));assert d['spec']['selector']==selector
 slices=json.loads(subprocess.check_output(k+['get','endpointslices','-l','kubernetes.io/service-name='+name,'-o','json']))
 assert len([e for s in slices['items'] for e in s.get('endpoints',[]) if e.get('conditions',{}).get('ready')])==1
for name in ['qwen38-nvfp4-blue','model-aggregator-qwen38-blue','model-aggregator-qwen-recovery']:
 d=json.loads(subprocess.check_output(k+['get','deployment',name,'-o','json']));assert d['status'].get('availableReplicas')==1
report=read('report.json');report['status']='complete';report['completed_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
report['post_publication_observation']={'passed':True,'rounds':len(public),'duration_s':public[-1]['elapsed_s'],'worker_restarts':0,'readiness_drops':0,'thermal_throttling_samples':0,'node_pressure_samples':0}
(a.evidence/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['post_publication_observation']))
