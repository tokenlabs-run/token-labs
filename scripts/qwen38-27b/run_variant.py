#!/usr/bin/env python3
"""Apply, warm and measure one unpublished candidate configuration."""
import argparse,json,pathlib,subprocess,sys,time,urllib.request
p=argparse.ArgumentParser();p.add_argument('--name',required=True);p.add_argument('--linear-backend',default='auto');p.add_argument('--speculative-tokens',type=int,default=3);p.add_argument('--skip-apply',action='store_true');a=p.parse_args()
root=pathlib.Path(__file__).resolve().parents[2];out=root/'results/2026-10-25-qwen38-spark'/a.name;out.mkdir(parents=True,exist_ok=True)
k=['kubectl','--context=kubernetes-admin@kubernetes','-n','token-labs'];url='http://10.104.229.232:8000'
def run(args,**kw):return subprocess.run(args,check=True,**kw)
manifest=subprocess.check_output([sys.executable,str(root/'scripts/qwen38-27b/render_candidate.py'),'--linear-backend',a.linear_backend,'--speculative-tokens',str(a.speculative_tokens)])
(out/'candidate.json').write_bytes(manifest)
if not a.skip_apply:run([sys.executable,str(root/'scripts/qwen38-27b/apply_candidate.py'),str(out/'candidate.json')])
start=time.monotonic()
while True:
 d=json.loads(subprocess.check_output(k+['get','deployment','qwen38-nvfp4-blue','-o','json']))
 s=d.get('status',{});ready=s.get('observedGeneration',0)>=d['metadata']['generation'] and s.get('availableReplicas',0)==1 and s.get('updatedReplicas',0)==1
 if ready:
  try:
   with urllib.request.urlopen(url+'/v1/models',timeout=10) as r: models=json.load(r)
   if 'nvidia/Qwen3.8-27B-NVFP4' in [x['id'] for x in models['data']]:break
  except Exception:pass
 if time.monotonic()-start>1200:raise RuntimeError('Candidate failed to become ready within 20 minutes')
 print(json.dumps({'variant':a.name,'waiting_s':round(time.monotonic()-start)}),flush=True);time.sleep(15)
(out/'startup.log').write_bytes(subprocess.check_output(k+['logs','deployment/qwen38-nvfp4-blue','-c','worker']))
run([sys.executable,str(root/'scripts/qwen38-27b/benchmark.py'),'--url',url,'--config',a.name,'--output',str(out/'benchmark-c1.json')])
print('COMPLETE '+a.name,flush=True)
