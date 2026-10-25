#!/usr/bin/env python3
"""Render Flint's Dynamo worker/frontend migration, preserving pinned model inputs."""
import argparse,copy,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--image',required=True);a=p.parse_args()
if '@sha256:' not in a.image:p.error('Require a digest-pinned Flint-compatible ARM64 image')
r=Path(__file__).resolve().parent;b=json.loads((r/'inputs'/'flint-nvfp4-vllm-green-before.json').read_text());o={k:copy.deepcopy(b[k]) for k in ('apiVersion','kind','spec')};o['metadata']={k:b['metadata'][k] for k in ('name','namespace')};(r/'rollback'/'flint-rollback.json').write_text(json.dumps(o,indent=2)+'\n')
s=o['spec'];s['strategy']={'type':'Recreate'};pod=s['template']['spec'];worker=pod['containers'][0]
args=worker['args'];new=['--model',args[0]];i=1
remove={'--enable-auto-tool-choice':0,'--tool-call-parser':1,'--reasoning-parser':1,'--host':1,'--port':1}
while i<len(args):
    if args[i] in remove:i+=1+remove[args[i]]
    else:new.append(args[i]);i+=1
new+=['--dyn-tool-call-parser','glm47','--dyn-reasoning-parser','glm45','--namespace','token-labs-flint-dynamo160','--discovery-backend','file']
worker['image']=a.image;worker['command']=['python3','-m','dynamo.vllm'];worker['args']=new
worker['env']=[e for e in worker['env'] if e['name']!='PYTHONPATH']+[{'name':'DYN_FILE_KV','value':'/dynamo-discovery'},{'name':'DYN_SYSTEM_ENABLED','value':'true'},{'name':'DYN_SYSTEM_PORT','value':'9090'}]
worker['ports']=[{'name':'system','containerPort':9090}]
for kind,path in [('startupProbe','/live'),('readinessProbe','/health'),('livenessProbe','/live')]:
    worker[kind]['httpGet']={'path':path,'port':'system'}
worker['volumeMounts']=[m for m in worker['volumeMounts'] if m['name']!='pr-runtime']+[{'name':'dynamo-discovery','mountPath':'/dynamo-discovery'}]
frontend={'name':'dynamo-frontend','image':a.image,'command':['python3','-m','dynamo.frontend'],'args':['--namespace','token-labs-flint-dynamo160','--discovery-backend','file'],'env':[{'name':'DYN_FILE_KV','value':'/dynamo-discovery'},{'name':'HF_HOME','value':'/model-cache'},{'name':'DYN_HTTP_PORT','value':'8000'}],'ports':[{'name':'http','containerPort':8000}],'resources':{'requests':{'cpu':'1','memory':'1Gi'},'limits':{'cpu':'2','memory':'4Gi'}},'volumeMounts':[{'name':'model-cache','mountPath':'/model-cache'},{'name':'dynamo-discovery','mountPath':'/dynamo-discovery'}],'startupProbe':{'httpGet':{'path':'/health','port':'http'},'periodSeconds':10,'failureThreshold':360},'readinessProbe':{'httpGet':{'path':'/health','port':'http'},'periodSeconds':10,'failureThreshold':3},'livenessProbe':{'httpGet':{'path':'/live','port':'http'},'periodSeconds':30,'failureThreshold':5}}
pod['containers']=[worker,frontend];pod['initContainers']=[x for x in pod['initContainers'] if x['name']!='build-vllm-pr'];pod['volumes']=[x for x in pod['volumes'] if x['name'] not in ('pr-runtime','pr-build-script')]+[{'name':'dynamo-discovery','emptyDir':{}}]
(r/'manifests'/'flint-160.json').write_text(json.dumps(o,indent=2)+'\n')
metrics=json.loads((r/'inputs'/'flint-provider-metrics-before.json').read_text())
metrics={k:copy.deepcopy(metrics[k]) for k in ('apiVersion','kind','metadata','spec')}
metrics['metadata']={k:metrics['metadata'][k] for k in ('name','namespace','labels')}
(r/'rollback'/'flint-metrics-rollback.json').write_text(json.dumps(metrics,indent=2)+'\n')
metrics['spec']['ports'][0]['targetPort']='system'
(r/'manifests'/'flint-metrics-160.json').write_text(json.dumps(metrics,indent=2)+'\n')
print('Rendered Flint migration, worker metrics routing, and exact spec rollback; public Service selectors preserved.')
