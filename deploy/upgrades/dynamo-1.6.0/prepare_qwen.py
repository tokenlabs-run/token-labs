#!/usr/bin/env python3
"""Render the authorized DGX Qwen upgrade and exact spec rollback from snapshots."""
import argparse, copy, json
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--image',required=True); a=p.parse_args()
if '@sha256:' not in a.image: p.error('Require an immutable ARM64 image reference')
root=Path(__file__).resolve().parent
names=['qwen36-nvfp4-dynamo-agg','qwen36-nvfp4-frontend-blue']
for name in names:
    before=json.loads((root/'inputs'/(name+'-before.json')).read_text())
    obj={k:copy.deepcopy(before[k]) for k in ('apiVersion','kind','spec')}
    obj['metadata']={k:before['metadata'][k] for k in ('name','namespace')}
    (root/'rollback'/(name+'-rollback.json')).write_text(json.dumps(obj,indent=2)+'\n')
    if obj['kind']=='DynamoGraphDeployment':
        for component in obj['spec']['components']:
            component['runtimeVersionOverride']='1.6.0'
            for c in component['podTemplate']['spec']['containers']:
                if c['name'] in ('main','sidecar-frontend'): c['image']=a.image
    else:
        obj['spec']['strategy']={'type':'Recreate'}
        pod=obj['spec']['template']['spec']; pod['nodeSelector']={'kubernetes.io/hostname':'spark-02'}
        pod.setdefault('tolerations',[])
        if not any(t.get('key')=='nvidia.com/gpu' for t in pod['tolerations']):
            pod['tolerations'].append({'key':'nvidia.com/gpu','operator':'Exists','effect':'NoSchedule'})
        for c in pod['containers']: c['image']=a.image
    (root/'manifests'/(name+'-160.json')).write_text(json.dumps(obj,indent=2)+'\n')
print('Rendered Qwen manifests and exact spec rollback; selectors and serving arguments preserved.')
