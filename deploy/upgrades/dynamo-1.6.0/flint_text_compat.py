"""Adapt Dynamo 1.6.0 to the pinned Flint text-generation runtime."""
from pathlib import Path
import sys
root=Path(sys.argv[1])
def replace(path, old, new):
    p=root/path;s=p.read_text()
    if new in s:return
    assert s.count(old)==1,(str(p),'unexpected source')
    p.write_text(s.replace(old,new))
replace('dynamo/vllm/embedding_worker_processes.py',
 'from vllm.v1.engine.utils import get_engine_zmq_addresses, launch_core_engines',
 'from vllm.v1.engine.utils import launch_core_engines')
replace('dynamo/vllm/embedding_worker_processes.py',
 '        addresses = get_engine_zmq_addresses(vllm_config, process_count)',
 '        from vllm.v1.engine.utils import get_engine_zmq_addresses\n\n        addresses = get_engine_zmq_addresses(vllm_config, process_count)')
replace('dynamo/vllm/main.py',
 '    if getattr(vllm_config.model_config, "model_weights", ""):\n        return vllm_config.model_config.model\n    return config.model',
 '    if getattr(vllm_config.model_config, "model_weights", ""):\n        return vllm_config.model_config.model\n    # Separate checkpoint files from their tokenizer/configuration directory.\n    return vllm_config.model_config.hf_config_path or config.model')
