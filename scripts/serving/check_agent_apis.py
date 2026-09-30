#!/usr/bin/env python3
"""Smoke-test chat, Responses, Messages, streaming, and tool calls using curl.

Set TOKENLABS_API_KEY if the endpoint requires authentication. Output contains
synthetic test responses only; credentials never appear in command arguments.
"""
import argparse
import json
import os
import subprocess
import tempfile


def stream_succeeded(text, marker):
    if marker not in text:
        return False
    for line in text.splitlines():
        if not line.startswith('data:'):
            continue
        data = line[5:].strip()
        if data == '[DONE]':
            continue
        event = json.loads(data)
        if event.get('error') is not None or event.get('type') in ('error', 'response.failed'):
            return False
        response = event.get('response')
        if isinstance(response, dict) and response.get('error') is not None:
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True, help='URL before /v1')
    parser.add_argument('--model', required=True)
    parser.add_argument('--chat-only', action='store_true')
    args = parser.parse_args()
    function = {'name': 'get_weather', 'description': 'Get weather for a city', 'parameters': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']}}
    common = {'model': args.model, 'messages': [{'role': 'user', 'content': 'Reply with exactly OK.'}], 'max_tokens': 256, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}}
    cases = [('chat', '/v1/chat/completions', common), ('chat-stream', '/v1/chat/completions', {**common, 'stream': True}), ('chat-tool', '/v1/chat/completions', {**common, 'messages': [{'role': 'user', 'content': 'Call get_weather for Paris.'}], 'tools': [{'type': 'function', 'function': function}], 'tool_choice': {'type': 'function', 'function': {'name': 'get_weather'}}})]
    if not args.chat_only:
        responses = {'model': args.model, 'input': 'Reply with exactly OK.', 'max_output_tokens': 256, 'store': False}
        messages = {'model': args.model, 'messages': common['messages'], 'max_tokens': 512, 'temperature': 0, 'thinking': {'type': 'disabled'}}
        cases += [('responses', '/v1/responses', responses), ('responses-stream', '/v1/responses', {**responses, 'stream': True}), ('messages', '/v1/messages', messages), ('messages-stream', '/v1/messages', {**messages, 'stream': True})]
    if not args.chat_only:
        cases += [
            ('responses-tool', '/v1/responses', {'model': args.model, 'input': 'Call get_weather for Paris.', 'max_output_tokens': 512, 'store': False, 'tools': [{'type': 'function', **function}], 'tool_choice': {'type': 'function', 'name': 'get_weather'}}),
            ('messages-tool', '/v1/messages', {'model': args.model, 'thinking': {'type': 'disabled'}, 'messages': [{'role': 'user', 'content': 'Call get_weather for Paris.'}], 'max_tokens': 512, 'tools': [{'name': function['name'], 'description': function['description'], 'input_schema': function['parameters']}], 'tool_choice': {'type': 'tool', 'name': 'get_weather'}}),
        ]
    failures = []
    for name, path, body in cases:
        with tempfile.TemporaryDirectory() as directory:
            header_path = os.path.join(directory, 'headers')
            with open(header_path, 'w') as f:
                f.write('Content-Type: application/json\nanthropic-version: 2023-06-01\n')
                if os.environ.get('TOKENLABS_API_KEY'):
                    f.write('Authorization: Bearer '+os.environ['TOKENLABS_API_KEY']+'\n')
            command = ['curl', '--silent', '--show-error', '--fail-with-body', '--max-time', '180', '--header', '@'+header_path, '--data-binary', '@-', args.base_url.rstrip('/')+path]
            result = subprocess.run(command, input=json.dumps(body), text=True, capture_output=True)
        success = result.returncode == 0
        try:
            if 'stream' in name:
                marker = '[DONE]' if name.startswith('chat') else ('response.completed' if name.startswith('responses') else 'message_stop')
                success = success and stream_succeeded(result.stdout, marker)
            else:
                data = json.loads(result.stdout)
                success = success and data.get('error') is None
                if name == 'chat-tool':
                    call = data['choices'][0]['message']['tool_calls'][0]['function']
                    success = success and call['name'] == 'get_weather' and json.loads(call['arguments'])['city'].lower() == 'paris'
                elif name == 'chat':
                    success = success and bool(data['choices'][0]['message'].get('content'))
                elif name == 'responses-tool':
                    call = next(x for x in data['output'] if x.get('type') == 'function_call')
                    success = success and call['name'] == 'get_weather' and json.loads(call['arguments'])['city'].lower() == 'paris'
                elif name == 'messages-tool':
                    call = next(x for x in data['content'] if x.get('type') == 'tool_use')
                    success = success and call['name'] == 'get_weather' and call['input']['city'].lower() == 'paris'
                elif name == 'responses':
                    success = success and data.get('status') == 'completed' and any(x.get('type') == 'message' for x in data.get('output', []))
                elif name == 'messages':
                    success = success and any(x.get('type') == 'text' and x.get('text') for x in data.get('content', []))
        except (ValueError, KeyError, IndexError, TypeError, StopIteration):
            success = False
        print(json.dumps({'test': name, 'model': args.model, 'passed': success, 'response': result.stdout, 'stderr': result.stderr}), flush=True)
        if not success:
            failures.append(name)
    if failures:
        raise SystemExit('Failed: '+', '.join(failures))


if __name__ == '__main__':
    main()
