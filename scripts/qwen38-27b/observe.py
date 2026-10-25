#!/usr/bin/env python3
"""Record readiness, restart counts, node pressure and cache metrics during a gate."""
import argparse,datetime,json,pathlib,subprocess,time,urllib.request
p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--duration',type=int,default=1800);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
k=['kubectl','--context=kubernetes-admin@kubernetes']
def get(args):return json.loads(subprocess.check_output(k+args+['-o','json']))
def fetch(url):
 with urllib.request.urlopen(url,timeout=15) as r:return r.read().decode()
a.output.parent.mkdir(parents=True,exist_ok=True);start=time.monotonic()
with a.output.open('w') as f:
 while True:
  row={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_s':round(time.monotonic()-start,1)}
  try:
   pods=get(['-n','token-labs','get','pods','-l','app=qwen38-nvfp4-blue'])['items']
   row['pods']=[{'name':v['metadata']['name'],'conditions':v['status'].get('conditions',[]),'containers':[{'name':c['name'],'ready':c['ready'],'restarts':c['restartCount']} for c in v['status'].get('containerStatuses',[])]} for v in pods]
   row['ready']=len(pods)==1 and all(c['ready'] for c in pods[0]['status'].get('containerStatuses',[])) and len(pods[0]['status'].get('containerStatuses',[]))==2
   row['models']=[v['id'] for v in json.loads(fetch(a.url.rstrip('/')+'/v1/models'))['data']]
   gpu=subprocess.check_output(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','nvidia@192.168.1.76','nvidia-smi --query-gpu=temperature.gpu,power.draw,utilization.gpu,clocks_event_reasons.sw_thermal_slowdown,clocks_event_reasons.hw_thermal_slowdown --format=csv,noheader,nounits'],timeout=15,text=True).strip().split(', ')
   row['gpu']={'temperature_c':float(gpu[0]),'power_w':float(gpu[1]),'utilization_percent':float(gpu[2]),'software_thermal_slowdown':gpu[3],'hardware_thermal_slowdown':gpu[4]}
   row['nodes']=[{'name':n['metadata']['name'],'conditions':{c['type']:c['status'] for c in n['status']['conditions']}} for n in get(['get','nodes'])['items']]
   ip=pods[0]['status']['podIP'];metrics=fetch('http://'+ip+':9090/metrics')
   row['metrics']=[line for line in metrics.splitlines() if not line.startswith('#') and any(x in line for x in ['cache_usage','num_requests_running','num_requests_waiting','spec_decode_num','request_success'])]
  except Exception as e:row['error']=str(e)
  f.write(json.dumps(row)+'\n');f.flush();print(json.dumps({'elapsed_s':row['elapsed_s'],'ready':row.get('ready'),'error':row.get('error')}),flush=True)
  if time.monotonic()-start>=a.duration:break
  time.sleep(min(30,max(0,a.duration-(time.monotonic()-start))))
