# Heterogeneous Mooncake VRAM transfer preflight

Date: 2026-08-29 (UTC)

## Outcome

PASS. Mooncake Transfer Engine v0.3.13 successfully transferred and validated data between one NVIDIA H200 and one AMD MI300X over its TCP transport.

The initiator completed 927 batches in 10.01 seconds and reported 6.22 Gb/s. Each batch contained eight 1 MiB requests. The validator reported `Data validation passed` after a WRITE from H200 to MI300X followed by a READ back to H200 and a byte comparison.

This proves functional heterogeneous transfer, but it is **not a direct GPU-to-GPU/RDMA path**. Mooncake's TCP transport stages GPU buffers through host DRAM on both machines:

```text
H200 VRAM -> H200 host DRAM -> public TCP -> MI300X host DRAM -> MI300X VRAM
```

The reported 6.22 Gb/s is the validator's logical payload rate for a loop that performs both WRITE and READ. It should not be interpreted as isolated one-way WRITE bandwidth.

## Topology

| Role | GPU | Provider | Address used |
| --- | --- | --- | --- |
| Initiator | NVIDIA H200 141 GB | DigitalOcean | 165.245.137.223 |
| Target | AMD MI300X 192 GB | AMD Developer Cloud | 165.245.141.196 |

The providers' private VPC addresses were not mutually routable, so this test used their public addresses.

## Software and build

- Mooncake release: `v0.3.13`
- Commit: `e5598b0992cc258b06d22f24d875480e8931a28e`
- NVIDIA build: `USE_CUDA=ON`, `USE_HIP=OFF`
- AMD build: `USE_CUDA=OFF`, `USE_HIP=ON`
- Transport: `tcp`
- Metadata exchange: `P2PHANDSHAKE`
- GPU buffer: 64 MiB
- Request block: 1 MiB
- Batch size: 8
- Worker threads: 1
- Duration: 10 seconds

Only the standalone Transfer Engine validator was built; Mooncake Store and unrelated components were disabled.

## Target command (MI300X)

```bash
HSA_OVERRIDE_GFX_VERSION=9.4.2 \
LD_LIBRARY_PATH=/opt/rocm/lib:/opt/Mooncake/build-mooncake/mooncake-common \
/opt/Mooncake/build-mooncake/mooncake-transfer-engine/example/transfer_engine_validator \
  --mode=target \
  --metadata_server=P2PHANDSHAKE \
  --protocol=tcp \
  --local_server_name=165.245.141.196:0 \
  --use_vram=true \
  --gpu_id=0 \
  --buffer_size=67108864 \
  --block_size=1048576 \
  --batch_size=8 \
  --threads=1 \
  --duration=10 \
  --report_unit=Gb
```

The target advertised handshake endpoint `165.245.141.196:15280` and logged `VRAM is used`.

## Initiator command (H200)

```bash
LD_LIBRARY_PATH=/usr/local/cuda/lib64:/opt/Mooncake/build-mooncake/mooncake-common \
/opt/Mooncake/build-mooncake/mooncake-transfer-engine/example/transfer_engine_validator \
  --mode=initiator \
  --metadata_server=P2PHANDSHAKE \
  --protocol=tcp \
  --local_server_name=165.245.137.223:0 \
  --segment_id=165.245.141.196:15280 \
  --use_vram=true \
  --gpu_id=0 \
  --buffer_size=67108864 \
  --block_size=1048576 \
  --batch_size=8 \
  --threads=1 \
  --duration=10 \
  --report_unit=Gb
```

## Initiator result

```text
VRAM is used
Worker 0 stopped! Data validation passed
Test completed: duration 10.01, batch count 927, throughput 6.22 Gb/s
```

## Interpretation

Mooncake TCP handles the CUDA/ROCm incompatibility by copying device data into a host allocation before socket I/O, then copying from a host allocation into the destination device. Source inspection of `tcp_transport_session_impl.h` shows host buffers allocated with `new char[...]` and device/host copies around the asynchronous socket reads and writes. On the AMD build, HIP compilation maps the device-copy operations to the ROCm runtime.

This path is useful as a functional compatibility shim and baseline. For production disaggregated prefill/decode, its two host-staging copies and public-network hop are likely to make KV transfer materially slower and less predictable than an RDMA-capable homogeneous GPU fabric. End-to-end Dynamo/vLLM benchmarking is still required before treating it as a viable serving path.
