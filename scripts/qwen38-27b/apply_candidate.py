#!/usr/bin/env python3
"""Apply only the unpublished Qwen3.8 candidate, refusing active Service selectors."""
import argparse,json,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('manifest',type=pathlib.Path);a=p.parse_args()
doc=json.loads(a.manifest.read_text());deploy=next(x for x in doc['items'] if x['kind']=='Deployment')
assert deploy['metadata']['name']=='qwen38-nvfp4-blue'
labels=deploy['spec']['template']['metadata']['labels']
k=['kubectl','--context=kubernetes-admin@kubernetes','-n','token-labs']
services=json.loads(subprocess.check_output(k+['get','service','-o','json']))['items']
for s in services:
 selector=s['spec'].get('selector',{})
 if s['metadata']['name']=='qwen38-nvfp4-blue':continue
 if selector and all(labels.get(key)==value for key,value in selector.items()):
  raise SystemExit('Refusing to change candidate selected by Service '+s['metadata']['name'])
subprocess.run(k+['apply','--dry-run=server','-f',str(a.manifest)],check=True)
subprocess.run(k+['apply','-f',str(a.manifest)],check=True)
