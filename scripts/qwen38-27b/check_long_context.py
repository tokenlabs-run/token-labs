#!/usr/bin/env python3
"""Run inside the worker to test the advertised context boundary, recording no text."""
import json,time,urllib.request
from transformers import AutoTokenizer
model='nvidia/Qwen3.8-27B-NVFP4';revision='482ca0f3832238542f8f5295dde86b5f22711d80'
t=AutoTokenizer.from_pretrained('/model-cache/hub/models--nvidia--Qwen3.8-27B-NVFP4/snapshots/'+revision,local_files_only=True)
text='Background: the sky is blue and the grass is green.\n'*16000
ids=t.encode(text,add_special_tokens=False)[:130800]
prompt=t.decode(ids)+'\nThe verification code is 73921. Reply with only the verification code.'
messages=[{'role':'user','content':prompt}]
n=len(t.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=False,return_dict=False));assert 130000<n<131040,n
body={'model':model,'messages':messages,'max_tokens':32,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}
start=time.monotonic()
with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'}),timeout=900) as r:d=json.load(r)
passed=d['choices'][0]['message']['content'].strip()=='73921'
print(json.dumps({'passed':passed,'prompt_tokens':d['usage']['prompt_tokens'],'completion_tokens':d['usage']['completion_tokens'],'elapsed_s':time.monotonic()-start}))
raise SystemExit(0 if passed else 1)
