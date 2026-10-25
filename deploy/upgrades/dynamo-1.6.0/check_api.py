#!/usr/bin/env python3
"""Probe actual model identity, generation, streaming, tools, and PR17105 behavior."""
import argparse, json, urllib.request, urllib.error
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--model',required=True);p.add_argument('--output',required=True);p.add_argument('--chat-only',action='store_true');a=p.parse_args()
rows=[]
def call(name,path,payload=None,stream=False):
    req=urllib.request.Request(a.url.rstrip('/')+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    row={'name':name,'passed':False}
    try:
        with urllib.request.urlopen(req,timeout=240) as r:
            row['http_status']=r.status
            if stream:
                events=[]
                for line in r:
                    if line.startswith(b'data:'):
                        data=line[5:].strip()
                        if data==b'[DONE]': events.append({'done':True});continue
                        if data: events.append(json.loads(data))
                assert not any(e.get('error') or e.get('type') in ('error','response.failed') for e in events), 'stream error event'
                if path=='/v1/responses': assert any(e.get('type')=='response.completed' for e in events),'missing response.completed'
                else: assert any(e.get('done') for e in events),'missing DONE'
                data=events
            else: data=json.load(r)
            if path=='/v1/models': assert a.model in [m['id'] for m in data['data']], 'wrong model identity'
            elif name=='chat-tools':
                calls=data['choices'][0]['message'].get('tool_calls',[])
                assert calls and calls[0]['function']['name']=='get_weather','missing tool call'
                assert json.loads(calls[0]['function']['arguments']).get('city')=='Paris','wrong tool arguments'
            elif path=='/v1/chat/completions' and not stream:
                text=data['choices'][0]['message'].get('content') or ''
                assert '4' in text,'incorrect arithmetic response'
            elif path=='/v1/responses' and not stream:
                assert data.get('status')=='completed' and not data.get('error'), 'response incomplete'
            row['passed']=True
    except Exception as e: row['error']=str(e)[:1000]
    rows.append(row); print(json.dumps(row),flush=True)
call('models','/v1/models')
base={'model':a.model,'messages':[{'role':'user','content':'What is 2 plus 2? Answer with only the digit.'}],'max_tokens':256,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}
call('chat','/v1/chat/completions',base)
call('chat-stream','/v1/chat/completions',{**base,'stream':True},True)
tool={**base,'messages':[{'role':'user','content':'Call get_weather for Paris.'}],'tools':[{'type':'function','function':{'name':'get_weather','description':'Get weather','parameters':{'type':'object','properties':{'city':{'type':'string'}},'required':['city']}}}],'tool_choice':{'type':'function','function':{'name':'get_weather'}}}
call('chat-tools','/v1/chat/completions',tool)
if not a.chat_only:
    for stream in [False,True]:
        for tools in [None,[]]:
            body={'model':a.model,'input':'Say hello.','max_output_tokens':256,'tool_choice':'auto','stream':stream,'chat_template_kwargs':{'enable_thinking':False}}
            if tools is not None:body['tools']=tools
            call(f'responses-auto-{stream}-{tools is None}','/v1/responses',body,stream)
report={'model':a.model,'passed':all(r['passed'] for r in rows),'checks':rows};Path(a.output).write_text(json.dumps(report,indent=2)+'\n');raise SystemExit(0 if report['passed'] else 1)
