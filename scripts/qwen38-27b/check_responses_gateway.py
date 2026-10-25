#!/usr/bin/env python3
"""Exercise native Responses text, SSE, namespace tool calls, and continuation."""
import argparse
import json
from pathlib import Path
import time
import urllib.request

MODEL = 'nvidia/Qwen3.8-27B-NVFP4'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    rows = []

    def call(label, payload):
        start = time.monotonic()
        body = {'model': MODEL, 'store': False, 'max_output_tokens': 256, **payload}
        req = urllib.request.Request(args.url.rstrip('/') + '/v1/responses',
                                     data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        with opener.open(req, timeout=120) as response:
            assert response.status == 200
            if payload.get('stream'):
                events = [json.loads(line[5:].strip()) for line in response
                          if line.startswith(b'data:') and line[5:].strip() not in (b'', b'[DONE]')]
                assert not any(e.get('type') in ('error', 'response.failed') or e.get('error') for e in events)
                completed = [e['response'] for e in events if e.get('type') == 'response.completed']
                assert len(completed) == 1
                result = completed[0]
                assert any(e.get('type') == 'response.output_text.delta' for e in events) if label.startswith('text') else True
            else:
                result = json.load(response)
        assert result['status'] == 'completed' and not result.get('error'), result
        rows.append({'case': label, 'passed': True, 'elapsed_s': round(time.monotonic() - start, 3)})
        print(json.dumps(rows[-1]), flush=True)
        return result

    def text(result):
        return ''.join(p.get('text', '') for i in result['output'] if i['type'] == 'message'
                       for p in i['content'] if p['type'] == 'output_text').strip()

    for stream in (False, True):
        result = call('text-' + str(stream), {'input': 'Compute 17+25. Reply with only the integer answer.',
                                              'stream': stream, 'tool_choice': 'auto'})
        assert text(result) == '42', result
        tools = [{'type': 'namespace', 'name': 'functions', 'description': 'Diagnostic tools', 'tools': [
            {'type': 'function', 'name': 'lookup', 'description': 'Return a stored integer.',
             'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False,
                            'required': []}, 'strict': True}]}]
        history = [{'role': 'user', 'content': 'Call functions.lookup, then report its returned integer.'}]
        result = call('namespace-tool-' + str(stream), {'input': history, 'tools': tools,
                      'tool_choice': 'required', 'stream': stream})
        calls = [i for i in result['output'] if i['type'] == 'function_call']
        assert len(calls) == 1 and calls[0]['name'].endswith('lookup'), result
        history += result['output'] + [{'type': 'function_call_output',
                                       'call_id': calls[0]['call_id'], 'output': '314159'}]
        result = call('tool-continuation-' + str(stream), {'input': history, 'tools': tools,
                                                         'tool_choice': 'none', 'stream': stream})
        assert '314159' in text(result), result
    args.output.write_text(json.dumps({'passed': True, 'url': args.url, 'checks': rows}, indent=2) + '\n')


if __name__ == '__main__':
    main()
