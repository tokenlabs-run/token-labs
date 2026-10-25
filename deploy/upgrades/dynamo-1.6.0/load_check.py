#!/usr/bin/env python3
"""Run a bounded streaming load and record latency, completion, and errors."""
import argparse, concurrent.futures, json, math, threading, time, urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--model',required=True);p.add_argument('--seconds',type=int,default=1800);p.add_argument('--max-tokens',type=int,default=64);p.add_argument('--include-reasoning',action='store_true',help='Count reasoning_content as generated tokens for capacity/TTFT; final-answer checks remain separate');p.add_argument('--concurrency',type=int,required=True);p.add_argument('--header',action='append',default=[]);p.add_argument('--output',required=True);a=p.parse_args()
headers={'Content-Type':'application/json'}
for h in a.header:
 k,v=h.split('=',1);headers[k]=v
start=time.monotonic();deadline=start+a.seconds;lock=threading.Lock();rows=[];out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
def worker(n):
 i=0
 while time.monotonic()<deadline:
  shape=(32,256,2048)[i%3];i+=1
  body={'model':a.model,'messages':[{'role':'user','content':f'Request {n}-{i}. Read this passage:\n'+('The sky is blue. '*shape)+'\nExplain in two sentences why the sky looks blue.'}],'max_tokens':a.max_tokens,'temperature':0,'stream':True,'chat_template_kwargs':{'enable_thinking':False}}
  row={'worker':n,'shape_repetitions':shape,'passed':False};t=time.monotonic();first=None;done=False;has_text=False;content_chars=0;reasoning_chars=0
  try:
   req=urllib.request.Request(a.url.rstrip('/')+'/v1/chat/completions',data=json.dumps(body).encode(),headers=headers)
   with urllib.request.urlopen(req,timeout=180) as response:
    row['status']=response.status
    for line in response:
     if not line.startswith(b'data:'):continue
     v=line[5:].strip()
     if v==b'[DONE]':done=True;continue
     if not v:continue
     d=json.loads(v)
     if d.get('error'):raise ValueError(str(d['error'])[:200])
     content=''.join(c.get('delta',{}).get('content') or '' for c in d.get('choices',[]))
     reasoning=''.join(c.get('delta',{}).get('reasoning_content') or c.get('delta',{}).get('reasoning') or '' for c in d.get('choices',[]))
     content_chars+=len(content);reasoning_chars+=len(reasoning)
     if content or (a.include_reasoning and reasoning):
      has_text=True
      if first is None:first=time.monotonic()-t
   row['passed']=done and has_text and response.status==200
  except Exception as e:row['error']=str(e)[:300]
  row['duration_s']=time.monotonic()-t;row['ttft_s']=first;row['content_characters']=content_chars;row['reasoning_characters']=reasoning_chars
  with lock:
   rows.append(row)
   with out.with_suffix('.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
  if not row['passed']:return
with concurrent.futures.ThreadPoolExecutor(max_workers=a.concurrency) as pool:list(pool.map(worker,range(a.concurrency)))
def percentile(xs):
 xs=sorted(xs);return xs[max(0,math.ceil(.95*len(xs))-1)] if xs else None
report={'model':a.model,'requested_seconds':a.seconds,'max_tokens':a.max_tokens,'include_reasoning':a.include_reasoning,'elapsed_s':time.monotonic()-start,'concurrency':a.concurrency,'requests':len(rows),'errors':sum(not r['passed'] for r in rows),'p95_ttft_s':percentile([r['ttft_s'] for r in rows if r['ttft_s'] is not None]),'p95_duration_s':percentile([r['duration_s'] for r in rows]),'by_shape':{str(s):{'requests':sum(r['shape_repetitions']==s for r in rows),'p95_ttft_s':percentile([r['ttft_s'] for r in rows if r['shape_repetitions']==s and r['ttft_s'] is not None]),'p95_duration_s':percentile([r['duration_s'] for r in rows if r['shape_repetitions']==s])} for s in (32,256,2048)}}
report['passed']=bool(rows) and report['errors']==0 and report['elapsed_s']>=a.seconds;out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));raise SystemExit(0 if report['passed'] else 1)
