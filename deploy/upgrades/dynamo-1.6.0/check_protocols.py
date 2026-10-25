#!/usr/bin/env python3
"""Exercise unary, streaming, tools, and namespace tools through a Dynamo frontend."""
import argparse
import json
import os
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--header', action='append', default=[])
    parser.add_argument('--chat-only', action='store_true')
    parser.add_argument('--skip-anthropic', action='store_true')
    args = parser.parse_args()
    function = {'name': 'get_weather', 'description': 'Get weather for a city', 'parameters': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']}}
    common = {'model': args.model, 'messages': [{'role': 'user', 'content': 'Reply with exactly OK.'}], 'max_tokens': 256, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}}
    cases = [('chat', '/v1/chat/completions', common), ('chat-stream', '/v1/chat/completions', {**common, 'stream': True}), ('chat-tool', '/v1/chat/completions', {**common, 'messages': [{'role': 'user', 'content': 'Call get_weather for Paris.'}], 'tools': [{'type': 'function', 'function': function}], 'tool_choice': {'type': 'function', 'function': {'name': 'get_weather'}}})]
    if not args.chat_only:
        responses = {'model': args.model, 'input': 'Reply with exactly OK.', 'max_output_tokens': 256, 'store': False, 'temperature': 0}
        messages = {'model': args.model, 'messages': common['messages'], 'max_tokens': 512, 'temperature': 0, 'thinking': {'type': 'disabled'}}
        cases += [('responses', '/v1/responses', responses), ('responses-stream', '/v1/responses', {**responses, 'stream': True}), ('messages', '/v1/messages', messages), ('messages-stream', '/v1/messages', {**messages, 'stream': True}), ('responses-tool', '/v1/responses', {**responses, 'input': 'Call get_weather for Paris.', 'max_output_tokens': 512, 'tools': [{'type': 'function', **function}], 'tool_choice': {'type': 'function', 'name': 'get_weather'}}), ('messages-tool', '/v1/messages', {**messages, 'messages': [{'role': 'user', 'content': 'Call get_weather for Paris.'}], 'tools': [{'name': function['name'], 'description': function['description'], 'input_schema': function['parameters']}], 'tool_choice': {'type': 'tool', 'name': 'get_weather'}})]
        tools = [{'type': 'namespace', 'name': ns, 'description': ns, 'tools': [{'type': 'function', **function}]} for ns in ('crm', 'billing')]
        for stream in (False, True):
            for ns in (None, 'crm', 'billing'):
                choice = 'none' if ns is None else {'type': 'allowed_tools', 'mode': 'required', 'tools': [{'type': 'function', 'namespace': ns, 'name': 'get_weather'}]}
                cases.append(('namespace-' + str(ns) + ('-stream' if stream else ''), '/v1/responses', {**responses, 'input': 'Reply with exactly OK.' if ns is None else 'Call get_weather for Paris.', 'tools': tools, 'tool_choice': choice, 'max_output_tokens': 512, 'stream': stream}))
    failed = []
    if args.skip_anthropic:
        cases = [case for case in cases if case[1] != '/v1/messages']
    for name, path, body in cases:
        start = time.monotonic()
        headers = {'Content-Type': 'application/json', 'Host': 'api.tokenlabs.run'}
        headers.update(dict(value.split('=', 1) for value in args.header))
        key = os.environ.get('TOKENLABS_API_KEY')
        if key:
            headers['Authorization'] = 'Bearer ' + key
        request = urllib.request.Request(args.base_url.rstrip('/') + path, data=json.dumps(body).encode(), headers=headers)
        text = ''
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=180) as response:
                text = response.read().decode()
            if body.get('stream'):
                events = [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith('data:') and line[5:].strip() != '[DONE]']
                assert events and all(not e.get('error') and e.get('type') not in ('error', 'response.failed') for e in events)
                if path.endswith('responses'):
                    data = next(e['response'] for e in events if e.get('type') == 'response.completed')
                    assert data['status'] == 'completed'
                elif path.endswith('messages'):
                    assert any(e.get('type') == 'message_stop' for e in events)
                    data = {}
                else:
                    assert '[DONE]' in text
                    data = {}
            else:
                data = json.loads(text)
                assert not data.get('error')
                if name == 'chat':
                    assert data['choices'][0]['message']['content'].strip()
                elif name == 'chat-tool':
                    assert data['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'get_weather'
                elif name == 'messages-tool':
                    assert any(x.get('type') == 'tool_use' and x.get('name') == 'get_weather' for x in data['content'])
                elif name.startswith('responses'):
                    assert data['status'] == 'completed'
                elif name == 'messages':
                    assert any(x.get('text') for x in data['content'])
            if name.startswith('namespace-') or name == 'responses-tool':
                calls = [x for x in data['output'] if x['type'] == 'function_call']
                if body['tool_choice'] == 'none':
                    assert not calls
                else:
                    assert calls and all(x['name'] == 'get_weather' and json.loads(x['arguments'])['city'].lower() == 'paris' for x in calls)
                    if name.startswith('namespace-'):
                        expected = body['tool_choice']['tools'][0]['namespace']
                        assert all(x.get('namespace') == expected for x in calls)
            passed, error = True, None
        except Exception as exc:
            passed, error = False, str(exc)
            if isinstance(exc, urllib.error.HTTPError):
                text = exc.read().decode()
            failed.append(name)
        print(json.dumps({'test': name, 'passed': passed, 'elapsed_s': round(time.monotonic() - start, 2), 'error': error, 'response': text}), flush=True)
    if failed:
        raise SystemExit('Failed: ' + ', '.join(failed))


if __name__ == '__main__':
    main()
