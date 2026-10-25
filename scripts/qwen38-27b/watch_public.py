#!/usr/bin/env python3
"""Run authenticated public inference checks during the observation window."""
import argparse,datetime,json,pathlib,subprocess,sys,time
p=argparse.ArgumentParser();p.add_argument('--duration',type=int,default=1800);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--existing-only',action='store_true');a=p.parse_args()
root=pathlib.Path(__file__).resolve().parents[2];a.output.parent.mkdir(parents=True,exist_ok=True)
last=a.output.with_suffix('.last.json');start=time.monotonic()
with a.output.open('w') as f:
 while True:
  before=time.monotonic();r=subprocess.run([sys.executable,str(root/'scripts/qwen38-27b/verify_gateway.py'),'--output',str(last)]+(['--existing-only'] if a.existing_only else []),capture_output=True,text=True)
  row={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_s':round(time.monotonic()-start,1),'passed':r.returncode==0}
  if r.returncode==0:row['checks']=json.loads(last.read_text())['checks']
  else:row['error']='Public verification failed; inspect current API before continuing'
  f.write(json.dumps(row)+'\n');f.flush();print(json.dumps({k:v for k,v in row.items() if k!='checks'}),flush=True)
  if r.returncode:raise SystemExit(r.returncode)
  if time.monotonic()-start>=a.duration:break
  time.sleep(min(max(0,30-(time.monotonic()-before)),max(0,a.duration-(time.monotonic()-start))))
