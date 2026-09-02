"""Small real-CUDA GMS process-sharing probe; no model or serving process changed."""
import argparse
import asyncio
import ctypes
import json
import multiprocessing as mp
import os
from pathlib import Path
import tempfile
import time

SIZE = 4096
PATTERN = bytes((i % 251 for i in range(SIZE)))


def server(socket_path):
    from gpu_memory_service.server.rpc import GMSRPCServer
    asyncio.run(GMSRPCServer(socket_path, device=0, allocation_retry_timeout=5).serve())


def check(result):
    if int(result[0]) != 0:
        raise RuntimeError(str(result))


def client(socket_path, pipe, mode):
    import torch
    from cuda.bindings import driver
    from gpu_memory_service.client.memory_manager import GMSClientMemoryManager
    from gpu_memory_service.common.locks import RequestedLockType
    # Lazy CUDA init alone leaves no current driver context on this runtime.
    context_anchor = torch.empty(1, device="cuda")
    manager = GMSClientMemoryManager(socket_path, device=0)
    try:
        if mode == 'writer':
            manager.connect(RequestedLockType.RW, timeout_ms=5000)
            va = manager.create_mapping(size=SIZE, tag='weights')
            allocation_id = manager.mappings[va].allocation_id
            data = ctypes.create_string_buffer(PATTERN)
            check(driver.cuMemcpyHtoD(va, ctypes.addressof(data), SIZE))
            manager.metadata_put('probe', allocation_id, 0, b'probe')
            manager.commit()
            pipe.send({'pid': os.getpid(), 'allocation_id': allocation_id, 'published': True})
        else:
            manager.connect(RequestedLockType.RO, timeout_ms=5000)
            allocation_id, offset, _ = manager.metadata_get('probe')
            va = manager.create_mapping(allocation_id=allocation_id)
            for command in iter(pipe.recv, 'close'):
                if command != 'verify':
                    raise ValueError(command)
                data = ctypes.create_string_buffer(SIZE)
                check(driver.cuMemcpyDtoH(ctypes.addressof(data), va + offset, SIZE))
                pipe.send({'pid': os.getpid(), 'allocation_id': allocation_id,
                           'bytes_match': data.raw == PATTERN,
                           'layout_hash': manager.get_memory_layout_hash()})
    except BaseException as exc:
        pipe.send({'error': repr(exc), 'pid': os.getpid()})
        raise
    finally:
        manager.close()
        pipe.close()


def receive(pipe, timeout=45):
    if not pipe.poll(timeout):
        raise TimeoutError('client response timeout')
    result = pipe.recv()
    if 'error' in result:
        raise RuntimeError(result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    ctx = mp.get_context('spawn')
    processes = []
    connections = []
    started = time.monotonic()
    result = {'kind': 'real_cuda_gms_process_sharing', 'bytes': SIZE}
    with tempfile.TemporaryDirectory(prefix='gms-handoff-') as directory:
        socket_path = str(Path(directory) / 'weights.sock')
        owner = ctx.Process(target=server, args=(socket_path,))
        owner.start()
        processes.append(owner)
        try:
            deadline = time.monotonic() + 20
            while not Path(socket_path).exists():
                if not owner.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError('GMS did not start')
                time.sleep(.05)

            def launch(mode):
                parent, child = ctx.Pipe()
                process = ctx.Process(target=client, args=(socket_path, child, mode))
                process.start()
                child.close()
                processes.append(process)
                connections.append(parent)
                return process, parent

            writer, pipe = launch('writer')
            result['writer'] = receive(pipe)
            writer.join(20)
            assert writer.exitcode == 0, writer.exitcode
            result['writer_exited_before_readers'] = True
            old, old_pipe = launch('reader')
            old_pipe.send('verify')
            result['old_reader'] = receive(old_pipe)
            new, new_pipe = launch('reader')
            new_pipe.send('verify')
            result['new_reader_while_old_alive'] = receive(new_pipe)
            assert old.is_alive() and new.is_alive()
            old_pipe.send('close')
            old.join(20)
            assert old.exitcode == 0
            new_pipe.send('verify')
            result['new_reader_after_old_exit'] = receive(new_pipe)
            new_pipe.send('close')
            new.join(20)
            assert new.exitcode == 0
            readers = [result[k] for k in ['old_reader', 'new_reader_while_old_alive', 'new_reader_after_old_exit']]
            assert all(r['bytes_match'] for r in readers)
            assert all(r['allocation_id'] == result['writer']['allocation_id'] for r in readers)
            assert len({r['layout_hash'] for r in readers}) == 1
            result['passed'] = True
        except BaseException as exc:
            result.update(passed=False, error=repr(exc))
            raise
        finally:
            for connection in connections:
                connection.close()
            for process in reversed(processes):
                if process.is_alive():
                    process.terminate()
                process.join(5)
                if process.is_alive():
                    process.kill()
                    process.join(5)
            result['elapsed_seconds'] = time.monotonic() - started
            Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
