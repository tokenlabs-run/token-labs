#!/usr/bin/env python3
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--image',required=True);p.add_argument('--name',default='dynamo160-image-check');p.add_argument('--node',default='spark-02');p.add_argument('--wheel-dir',default='/opt/dynamo/wheelhouse');p.add_argument('--flint-metadata',action='store_true');a=p.parse_args()
assert '@sha256:' in a.image
code='''import importlib.metadata as m,platform,pathlib,hashlib,zipfile,json
assert platform.machine()=="aarch64",platform.machine()
versions={p:m.version(p) for p in ("ai-dynamo","ai-dynamo-runtime","vllm","torch")}
assert versions["ai-dynamo-runtime"]=="1.6.0"
import dynamo._core
from dynamo.vllm.main import main
core=pathlib.Path(dynamo._core.__file__)
wheel=next(pathlib.Path('''+repr(a.wheel_dir)+''').glob("ai_dynamo_runtime*.whl"))
with core.open("rb") as f: installed=hashlib.file_digest(f,"sha256").hexdigest()
with zipfile.ZipFile(wheel) as z:
 entry=next(n for n in z.namelist() if pathlib.PurePosixPath(n).name==core.name)
 with z.open(entry) as f: packaged=hashlib.file_digest(f,"sha256").hexdigest()
assert installed==packaged,"Installed Rust runtime differs from the supplied wheel"
print("IMAGE_CHECK "+json.dumps({"passed":True,"architecture":platform.machine(),"versions":versions,"core_sha256":installed}))
report=pathlib.Path('/opt/tokenlabs/dependency-check.json')
if report.exists():
 data=json.loads(report.read_text()); assert data['passed']; print('DEPENDENCY_CHECK '+json.dumps(data))
'''
j={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':a.name,'namespace':'token-labs'},'spec':{'backoffLimit':0,'activeDeadlineSeconds':1200,'template':{'metadata':{'labels':{'app':a.name}},'spec':{'restartPolicy':'Never','nodeSelector':{'kubernetes.io/hostname':a.node},'tolerations':[{'key':'nvidia.com/gpu','operator':'Exists','effect':'NoSchedule'}],'containers':[{'name':'check','image':a.image,'command':['/bin/bash','-lc'],'args':['set -euo pipefail\npython3 -m dynamo.frontend --help >/dev/null\npython3 -c '+__import__('shlex').quote(code)],'env':[{'name':'NVIDIA_VISIBLE_DEVICES','value':'void'}],'resources':{'requests':{'cpu':'1','memory':'1Gi'},'limits':{'cpu':'2','memory':'4Gi'}}}]}}}}
if a.flint_metadata:
    extra="""
from types import SimpleNamespace as NS
from dynamo._core import ModelDeploymentCard
from dynamo.vllm.main import _register_model_source_path
metadata='/model-cache/hub/models--RecursiveSI--flint/snapshots/2a247be0c0aec895ccb0ac7ca92229ec6df37288'
checkpoint='/model-cache/hub/models--RecursiveSI--flint-nvfp4-gguf/snapshots/6ec43e19b565fc8d560e2d04985d7724f20673bf/flint-nvfp4.gguf'
assert pathlib.Path(checkpoint).is_file()
source=_register_model_source_path(NS(model=checkpoint),NS(model_config=NS(model_weights='',hf_config_path=metadata)))
assert source==metadata
card=ModelDeploymentCard.load(source,'RecursiveSI/flint')
assert card.name()=='RecursiveSI/flint'
print('FLINT_METADATA_CHECK_PASSED')
"""
    job_pod=j['spec']['template']['spec'];job_pod['volumes']=[{'name':'model-cache','hostPath':{'path':'/home/nvidia/.cache/huggingface/hub','type':'Directory'}}]
    container=job_pod['containers'][0];container['volumeMounts']=[{'name':'model-cache','mountPath':'/model-cache/hub','readOnly':True}]
    container['args']=['set -euo pipefail\npython3 -m dynamo.frontend --help >/dev/null\npython3 -c '+__import__('shlex').quote(code+extra)]
Path(__file__).with_name(a.name+'.json').write_text(json.dumps(j,indent=2)+'\n')
