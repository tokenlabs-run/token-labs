#!/usr/bin/env bash
set -euo pipefail

site_dir="${1:?usage: install_moriio_overlay.sh DYNAMO_SITE_PACKAGES_DIR}"
protocols="${site_dir}/dynamo/vllm/kv_connector_protocols.py"
overlay="${site_dir}/dynamo/vllm/moriio_protocol.py"
test -f "${protocols}"
install -m 0644 "$(dirname "$0")/moriio_protocol.py" "${overlay}"
grep -q '^from dynamo.vllm.moriio_protocol import MoriioConnectorProtocol$' "${protocols}" || sed -i '/^import uuid$/a from dynamo.vllm.moriio_protocol import MoriioConnectorProtocol' "${protocols}"
grep -q '"MoRIIOConnector": MoriioConnectorProtocol' "${protocols}" || sed -i '/"MooncakeConnector": MooncakeConnectorProtocol,/a\    "MoRIIOConnector": MoriioConnectorProtocol,' "${protocols}"
python -m py_compile "${protocols}" "${overlay}"
python - <<'PY'
from types import SimpleNamespace
from dynamo.vllm.kv_connector_protocols import make_kv_connector_protocol
extra = {"decode_host": "172.18.0.5", "decode_handshake_port": 5601, "decode_notify_port": 5602, "tp_size": 1, "remote_dp_size": 1}
cfg = SimpleNamespace(kv_transfer_config=SimpleNamespace(kv_connector="MoRIIOConnector", kv_connector_extra_config=extra))
p = make_kv_connector_protocol(cfg)
prefill = p.prefill_request_kv_transfer_params()
assert prefill["transfer_id"].startswith("tx") and prefill["remote_host"] == "172.18.0.5"
decode = p.decode_request_kv_transfer_params(SimpleNamespace(kv_transfer_params={"remote_block_ids": [1]}))
assert decode["transfer_id"] == prefill["transfer_id"] and decode["do_remote_prefill"] is True
print("MoRIIO Dynamo protocol overlay: PASS")
PY
