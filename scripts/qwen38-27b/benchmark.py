#!/usr/bin/env python3
"""Repeatable streaming decode comparison and sustained-load check.

Uses fixed prompts, output lengths, temperature and seed across configurations.
Reports observed token rate from server usage, not text chunks or word counts.
Stores timing and usage only. No credentials or generated text are saved.
"""
import argparse, concurrent.futures, datetime, json, math, os, pathlib, statistics, time, urllib.request
p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--config',required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--requests',type=int,default=9);p.add_argument('--concurrency',type=int,default=1);p.add_argument('--tokens',type=int,default=256);p.add_argument('--duration',type=float,default=0);p.add_argument('--mixed-context',action='store_true');p.add_argument('--api-key-env');a=p.parse_args()
headers={'Content-Type':'application/json'}
if a.api_key_env:
 assert a.url=='https://api.tokenlabs.run/openrouter','Authenticated benchmarks are restricted to the authorized public provider URL'
 headers['Authorization']='Bearer '+os.environ[a.api_key_env]
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise RuntimeError('Redirect refused')
opener=urllib.request.build_opener(NoRedirect(),urllib.request.ProxyHandler({}))
MODEL='nvidia/Qwen3.8-27B-NVFP4'
PROMPTS=[
'Explain how a hash table works, with collision resolution and a Python example. Be detailed.',
'Write a Python LRU cache class and explain its invariants and time complexity. Be detailed.',
'Explain the tradeoffs between caching, batching, and speculative decoding for language model serving. Be detailed.'
]
def one(i,warm=False):
 prefix=('Reference material: caching avoids repeated work. Batching shares computation. Latency depends on queueing. ' * [0,32,256][i%3]) if a.mixed_context else ''
 body={'model':MODEL,'messages':[{'role':'user','content':prefix+f'Case {i:08d}. '+PROMPTS[i%len(PROMPTS)]}],'max_tokens':a.tokens,'min_tokens':a.tokens,'ignore_eos':True,'temperature':0,'seed':42,'chat_template_kwargs':{'enable_thinking':False},'stream':True,'stream_options':{'include_usage':True}}
 req=urllib.request.Request(a.url.rstrip('/')+'/v1/chat/completions',data=json.dumps(body).encode(),headers=headers)
 start=time.perf_counter();first=None;last=None;usage=None;done=False;events=0
 try:
  with opener.open(req,timeout=300) as r:
   for raw in r:
    line=raw.decode().strip()
    if not line.startswith('data:'): continue
    data=line[5:].strip()
    if data=='[DONE]':done=True;break
    d=json.loads(data)
    if d.get('error'):raise RuntimeError('SSE error returned')
    if d.get('usage'): usage=d['usage']
    for c in d.get('choices',[]):
     delta=c.get('delta',{})
     if delta.get('content') or delta.get('reasoning_content') or delta.get('reasoning'):
      now=time.perf_counter();first=now if first is None else first;last=now;events+=1
  end=time.perf_counter()
  assert done and first is not None and usage, 'Incomplete stream or missing usage'
  n=usage['completion_tokens'];assert n==a.tokens, f'Output length {n}, expected {a.tokens}'
  return {'index':i,'ok':True,'completion_tokens':n,'prompt_tokens':usage['prompt_tokens'],'elapsed_s':end-start,'ttft_s':first-start,'decode_s':last-first,'decode_tok_s':(n-1)/(last-first),'stream_events':events}
 except Exception as e:return {'index':i,'ok':False,'error':str(e),'elapsed_s':time.perf_counter()-start}
# Warm each prompt before measurements. Warm-up is recorded separately.
warm=[one(i,True) for i in range(3)]
assert all(r['ok'] for r in warm),warm
started=time.perf_counter();rows=[];i=0
with concurrent.futures.ThreadPoolExecutor(max_workers=a.concurrency) as pool:
 while i<a.requests or (a.duration and time.perf_counter()-started<a.duration):
  batch=list(pool.map(one,range(i,i+a.concurrency)));rows.extend(batch);i+=a.concurrency
  ok=[r for r in rows if r['ok']]
  print(json.dumps({'completed':len(rows),'errors':len(rows)-len(ok),'median_decode_tok_s':statistics.median(r['decode_tok_s'] for r in ok) if ok else None,'elapsed_s':round(time.perf_counter()-started,1)}),flush=True)
  if not all(r['ok'] for r in batch):break
span=time.perf_counter()-started;ok=[r for r in rows if r['ok']]
def pct(key,q):
 v=sorted(r[key] for r in ok)
 if not v:return None
 return statistics.median(v) if q==.5 else v[min(len(v)-1,max(0,math.ceil(len(v)*q)-1))]
out={'model':MODEL,'config':a.config,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'mixed_context':a.mixed_context,'concurrency':a.concurrency,'target_output_tokens':a.tokens,'warmup':warm,'requests':rows,'elapsed_s':span,'summary':{'passed':len(ok)==len(rows),'requests':len(rows),'errors':len(rows)-len(ok),'median_decode_tok_s':pct('decode_tok_s',.5),'p95_ttft_s':pct('ttft_s',.95),'p95_e2e_s':pct('elapsed_s',.95),'aggregate_output_tok_s':sum(r['completion_tokens'] for r in ok)/span}}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out['summary']),flush=True)
raise SystemExit(0 if out['summary']['passed'] else 1)
