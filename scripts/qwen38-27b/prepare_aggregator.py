#!/usr/bin/env python3
"""Render a separate aggregator and a stable new-model Service, without promotion."""
import argparse, copy, json, pathlib, subprocess
p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--concurrency',type=int,default=4);a=p.parse_args()
k=['kubectl','--context=kubernetes-admin@kubernetes','-n','token-labs']
def read(kind,name):return json.loads(subprocess.check_output(k+['get',kind,name,'-o','json']))
stable=read('service','model-aggregator')
assert stable['spec']['selector']=={'app':'model-aggregator-qwen-recovery'},'Unexpected active aggregator; review before proceeding'
spec=copy.deepcopy(read('deployment','model-aggregator-qwen-recovery')['spec'])
name='model-aggregator-qwen38-blue'; labels={'app':name}
spec['selector']={'matchLabels':labels};spec['template']['metadata']={'labels':labels}
c=spec['template']['spec']['containers'][0]
for env in c['env']:
 if env['name']=='MODEL_BACKEND_SERVICES':env['value']+=',qwen38-nvfp4'
 if env['name']=='MODEL_CONCURRENCY_LIMITS':
  limits=json.loads(env['value']);limits['nvidia/Qwen3.8-27B-NVFP4']=a.concurrency;env['value']=json.dumps(limits)
deployment={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'namespace':'token-labs','name':name},'spec':spec}
def service(name,selector,labels=None):return {'apiVersion':'v1','kind':'Service','metadata':{'namespace':'token-labs','name':name,'labels':labels or {}},'spec':{'selector':selector,'ports':[{'name':'http','port':8000,'targetPort':'http'}]}}
items=[deployment,service(name,labels),service('qwen38-nvfp4',{'token-labs/model-id':'qwen38-nvfp4','token-labs/slot':'blue'},{'token-labs/model':'true'})]
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'apiVersion':'v1','kind':'List','items':items},indent=2)+'\n')
print(a.output)
