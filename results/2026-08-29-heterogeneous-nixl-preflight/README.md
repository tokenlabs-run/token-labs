# H200 to MI300X cross-team NIXL preflight

Date: 2026-08-29 UTC

## Topology

| Role | GPU | Provider/team | Region | Public IP | Private IP |
| --- | --- | --- | --- | --- | --- |
| Prefill candidate | NVIDIA H200 141 GB | DigitalOcean My Team | ATL1 | `165.245.128.246` | `10.116.0.2/20` |
| Decode candidate | AMD MI300X VF 192 GB | AMD Developer Cloud MyAMD | ATL1 | `165.245.141.196` | `10.128.0.2/20` |

The nodes were in the same datacenter region but isolated team VPCs. Private-IP
ICMP failed in both directions. Public-IP ICMP succeeded.

## Network results

| Direction | TCP streams | Receiver throughput |
| --- | ---: | ---: |
| MI300X to H200 | 1 | 10.00 Gb/s |
| MI300X to H200 | 8 | 9.42 Gb/s |
| H200 to MI300X | 1 | 9.97 Gb/s |

Public-path unloaded ICMP RTT averaged 0.83 ms from MI300X to H200 and 1.39 ms
from H200 to MI300X. Eight TCP streams caused heavy retransmission and did not
improve aggregate bandwidth.

## NIXL GPU-memory test

- NVIDIA: CUDA 13, GPU-enabled PyTorch, NIXL 1.3.2 UCX plugin.
- AMD: ROCm 7.1.5, GPU-enabled PyTorch, `nixl_rocm` 1.3.2, UCX 1.22.x built
  with `--with-rocm=/opt/rocm`.
- Both NIXL agents instantiated the UCX backend.
- NIXL successfully registered an MI300X VRAM buffer.
- Peer discovery, metadata exchange, and transfer-handle construction succeeded.
- The official two-peer example failed on ROCm-to-CUDA READ.
- A write-only variant, matching H200 prefill to MI300X decode, failed on the
  CUDA-to-ROCm GPU-memory PUT.

Required-direction error:

```text
UCX ERROR cannot find remote protocol for: ucp_context_0 inter-node cfg#2 |
put(multi) from cuda/GPU0 to rocm
NIXL_ERR_REMOTE_DISCONNECT
```

## Decision

Do not proceed with the full Dynamo heterogeneous P/D benchmark on this pair
using direct NIXL/UCX GPU-memory transfer. Ordinary public networking is viable
at approximately 10 Gb/s, but the tested UCX/NIXL stacks do not negotiate a
CUDA-to-ROCm GPU-memory protocol. A host-staged connector would be a different
experiment and would add copies and public-network overhead.
