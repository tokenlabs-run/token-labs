#!/usr/bin/env python3
"""Exercise the real model API and deterministic quality checks before promotion."""
import argparse,importlib.util,json,pathlib,time
import requests
p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--repetitions',type=int,default=2);a=p.parse_args()
path=pathlib.Path(__file__).resolve().parents[1]/'openrouter/check_api_conformance.py'
spec=importlib.util.spec_from_file_location('conformance',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
s=requests.Session();s.trust_env=False
ctx={'session':s,'url':a.url.rstrip('/'),'model':'nvidia/Qwen3.8-27B-NVFP4','timeout':300}
results=[]
for repetition in range(a.repetitions):
 for name in ['models','nonstream','stream','unknown-model','invalid-request','tools','structured-output']:
  started=time.monotonic()
  try: evidence=m.CHECKS[name](ctx);r={'name':name,'passed':True,'evidence':evidence}
  except Exception as e:r={'name':name,'passed':False,'error':str(e)}
  r.update(repetition=repetition,elapsed_s=time.monotonic()-started);results.append(r);print(json.dumps(r),flush=True)
for x,y in [(17,25),(123,456),(19,37),(8,9),(100,27)]:
 prompt=f'Compute {x}+{y}. Reply with only the integer answer.'
 try:
  r=s.post(ctx['url']+'/v1/chat/completions',json={'model':ctx['model'],'messages':[{'role':'user','content':prompt}],'max_tokens':32,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}},timeout=300);r.raise_for_status()
  text=r.json()['choices'][0]['message']['content'].strip();assert text==str(x+y),'Incorrect arithmetic answer'
  result={'name':f'arithmetic-{x}-{y}','passed':True}
 except Exception as e:result={'name':f'arithmetic-{x}-{y}','passed':False,'error':str(e)}
 results.append(result);print(json.dumps(result),flush=True)
report={'model':ctx['model'],'passed':all(r['passed'] for r in results),'checks':results}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
