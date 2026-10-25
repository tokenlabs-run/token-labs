#!/usr/bin/env python3
"""Verify both models using the provider credential in memory only; no redirects."""
import argparse,base64,json,pathlib,subprocess,time,urllib.error,urllib.request
p=argparse.ArgumentParser();p.add_argument('--url',default='https://api.tokenlabs.run');p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--existing-only',action='store_true');a=p.parse_args()
k=['kubectl','--context=kubernetes-admin@kubernetes','-n','token-labs']
service=json.loads(subprocess.check_output(k+['get','svc','model-aggregator-qwen38-blue','-o','json']))
assert a.url in {'https://api.tokenlabs.run','http://'+service['spec']['clusterIP']+':8000'}
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise RuntimeError('Redirect refused')
opener=urllib.request.build_opener(NoRedirect(),urllib.request.ProxyHandler({}))
secret=json.loads(subprocess.check_output(k+['get','secret','openrouter-provider-auth','-o','json']))
key=base64.b64decode(secret['data']['api-key']).decode();models={'nvidia/Qwen3.6-35B-A3B-NVFP4','nvidia/Qwen3.8-27B-NVFP4'};results=[]
def request(path,body=None,auth=False):
 headers={'Content-Type':'application/json'}
 if auth:headers['Authorization']='Bearer '+key
 return opener.open(urllib.request.Request(a.url+path,data=None if body is None else json.dumps(body).encode(),headers=headers),timeout=180)
for path,auth in [('/v1/models',False),('/openrouter/v1/models',True)]:
 with request(path,auth=auth) as r:d=json.load(r)
 found={x['id'] for x in d['data']}
 assert (found <= models and 'nvidia/Qwen3.6-35B-A3B-NVFP4' in found) if a.existing_only else found==models,d
 results.append({'path':path,'passed':True})
try:request('/openrouter/v1/models').close();raise AssertionError('Anonymous access accepted')
except urllib.error.HTTPError as e:assert e.code==401
results.append({'check':'authentication','passed':True})
for model in sorted({'nvidia/Qwen3.6-35B-A3B-NVFP4'} if a.existing_only else models):
 for stream in [False,True]:
  body={'model':model,'messages':[{'role':'user','content':'Compute 17+25. Reply with only the integer answer.'}],'temperature':0,'max_tokens':32,'stream':stream,'chat_template_kwargs':{'enable_thinking':False}}
  started=time.monotonic()
  with request('/openrouter/v1/chat/completions',body,True) as r:
   if stream:
    raw=r.read().decode();assert 'data: [DONE]' in raw and '"error"' not in raw
    chunks=[json.loads(line[5:].strip()) for line in raw.splitlines() if line.startswith('data:') and line[5:].strip()!='[DONE]']
    content=''.join(c.get('delta',{}).get('content') or '' for chunk in chunks for c in chunk.get('choices',[]))
   else:content=json.load(r)['choices'][0]['message']['content']
  assert content.strip()=='42','Arithmetic completion did not match'
  results.append({'model':model,'stream':stream,'passed':True,'elapsed_s':round(time.monotonic()-started,3)});print(json.dumps(results[-1]),flush=True)
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'passed':True,'url':a.url,'checks':results},indent=2)+'\n')
