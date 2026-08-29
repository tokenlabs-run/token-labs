"""Dynamo vLLM protocol adapter for AMD MoRI-IO WRITE-mode P/D.

Loaded as a deployment overlay into Dynamo's kv_connector_protocols module.
The adapter mirrors the wire contract used by llm-d's MoRI sidecar: a unique
``tx`` transfer id is allocated before prefill, the destination decode engine
is supplied to the producer, and the same metadata is forwarded to decode.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional


class MoriioConnectorProtocol:
    """Push-based MoRI-IO coordination for one prefill/decode request."""

    def __init__(self, vllm_config: Any) -> None:
        self._vllm_config = vllm_config
        cfg = vllm_config.kv_transfer_config.kv_connector_extra_config
        required = ("decode_host", "decode_handshake_port", "decode_notify_port")
        missing = [key for key in required if cfg.get(key) in (None, "")]
        if missing:
            raise ValueError(
                "MoRIIOConnector Dynamo P/D requires kv_connector_extra_config "
                f"keys: {', '.join(missing)}"
            )
        self._decode_host = str(cfg["decode_host"])
        self._decode_handshake_port = int(cfg["decode_handshake_port"])
        self._decode_notify_port = int(cfg["decode_notify_port"])
        self._tp_size = int(cfg.get("tp_size", 1))
        self._dp_size = int(cfg.get("remote_dp_size", 1))
        self._transfer_id = "tx" + str(uuid.uuid4())

    def prefill_request_kv_transfer_params(self) -> Dict[str, Any]:
        return {
            "do_remote_decode": True,
            "do_remote_prefill": False,
            "remote_engine_id": None,
            "remote_block_ids": None,
            "remote_host": self._decode_host,
            "remote_port": None,
            "remote_notify_port": self._decode_notify_port,
            "remote_handshake_port": self._decode_handshake_port,
            "remote_dp_rank": 0,
            "remote_dp_rank_override": True,
            "remote_dp_size": self._dp_size,
            "tp_size": self._tp_size,
            "transfer_id": self._transfer_id,
        }

    def decode_request_kv_transfer_params(
        self, prefill_response: Any
    ) -> Optional[Dict[str, Any]]:
        params = dict(prefill_response.kv_transfer_params or {})
        params.update(
            {
                "do_remote_decode": False,
                "do_remote_prefill": True,
                "transfer_id": self._transfer_id,
                "remote_notify_port": self._decode_notify_port,
                "remote_handshake_port": self._decode_handshake_port,
                "remote_dp_rank": 0,
                "remote_dp_rank_override": True,
                "remote_dp_size": self._dp_size,
                "tp_size": self._tp_size,
            }
        )
        return params

