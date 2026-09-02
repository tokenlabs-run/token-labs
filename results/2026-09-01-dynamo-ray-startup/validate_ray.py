import json, time, ray
from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy
ray.init(address='auto', logging_level='ERROR')
deadline=time.monotonic()+45
while True:
 nodes=[n for n in ray.nodes() if n['Alive']]
 if len(nodes)==4: break
 assert time.monotonic()<deadline, f'Only {len(nodes)} live nodes'
 time.sleep(1)
@ray.remote
def identify():
 import socket
 return {'hostname':socket.gethostname(),'node_id':ray.get_runtime_context().get_node_id()}
results=ray.get([identify.options(scheduling_strategy=NodeAffinitySchedulingStrategy(n['NodeID'],soft=False)).remote() for n in nodes],timeout=30)
assert len({r['node_id'] for r in results})==4,results
print(json.dumps({'ray_version':ray.__version__,'alive_nodes':len(nodes),'tasks':results,'result':'PASS'},indent=2))
