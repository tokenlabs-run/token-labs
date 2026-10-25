#!/usr/bin/env python3
"""Keep one existing-model stream open across the aggregator selector switch."""
import argparse,base64,datetime,json,pathlib,subprocess,time,urllib.request
p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--started',type=pathlib.Path,required=True);a=p.parse_args()
k=['kubectl','--context=kubernetes-admin@kubernetes','-n','token-labs']
s=json.loads(subprocess.check_output(k+['get','secret','openrouter-provider-auth','-o','json']));key=base64.b64decode(s['data']['api-key']).decode()
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise RuntimeError('Redirect refused')
opener=urllib.request.build_opener(NoRedirect(),urllib.request.ProxyHandler({}))
body={'model':'nvidia/Qwen3.6-35B-A3B-NVFP4','messages':[{'role':'user','content':'Explain database indexing, transaction isolation, and query planning in detail.'}],'temperature':0,'max_tokens':2048,'min_tokens':2048,'ignore_eos':True,'stream':True,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
request=urllib.request.Request('https://api.tokenlabs.run/openrouter/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
a.output.parent.mkdir(parents=True,exist_ok=True);start=time.monotonic();first=None;usage=None;done=False
with opener.open(request,timeout=180) as response:
 for raw in response:
  line=raw.decode().strip()
  if not line.startswith('data:'):continue
  value=line[5:].strip()
  if value=='[DONE]':done=True;break
  d=json.loads(value);assert not d.get('error'),'SSE error'
  if d.get('usage'):usage=d['usage']
  if first is None and any(c.get('delta',{}).get('content') for c in d.get('choices',[])):
   first=time.monotonic();a.started.write_text(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'ttft_s':first-start})+'\n');print('STREAM STARTED',flush=True)
passed=done and first is not None and usage is not None and usage['completion_tokens']==2048
result={'passed':passed,'completed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_s':time.monotonic()-start,'ttft_s':None if first is None else first-start,'done':done,'usage':usage}
a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
raise SystemExit(0 if passed else 1)
