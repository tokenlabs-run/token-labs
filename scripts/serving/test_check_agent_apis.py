import contextlib
import io
import json
import types
import unittest
from unittest.mock import patch

import check_agent_apis as checks


class NamespaceRegressionTests(unittest.TestCase):
    def run_checker(self, wrong_namespace=False):
        seen = []

        def respond(command, input, **kwargs):
            body = json.loads(input)
            path = command[-1]
            choice = body.get('tool_choice')
            tool = choice is not None and choice != 'none'
            call = {'type': 'function_call', 'name': 'get_weather',
                    'arguments': '{"city":"Paris"}'}
            if isinstance(choice, dict) and choice.get('type') == 'allowed_tools':
                namespace = choice['tools'][0]['namespace']
                call['namespace'] = 'wrong' if wrong_namespace else namespace
                seen.append((namespace, body.get('stream', False)))
            if path.endswith('/responses'):
                response = {'status': 'completed', 'output': [call] if tool else [{'type': 'message'}]}
                event = {'type': 'response.completed', 'response': response}
            elif path.endswith('/messages'):
                response = {'content': [{'type': 'tool_use', 'name': 'get_weather', 'input': {'city': 'Paris'}}]
                            if tool else [{'type': 'text', 'text': 'OK'}]}
                event = {'type': 'message_stop'}
            else:
                response = {'choices': [{'message': {'content': 'OK', 'tool_calls': [{'function': call}]}}]}
                event = response
            output = json.dumps(response)
            if body.get('stream'):
                output = 'data: ' + json.dumps(event) + '\n\n'
                if path.endswith('/chat/completions'):
                    output += 'data: [DONE]\n\n'
            return types.SimpleNamespace(returncode=0, stdout=output, stderr='')

        with patch('sys.argv', ['check_agent_apis.py', '--base-url', 'http://test', '--model', 'test']), \
                patch.object(checks.subprocess, 'run', side_effect=respond), \
                contextlib.redirect_stdout(io.StringIO()):
            checks.main()
        return seen

    def test_round_trip_checks_both_namespaces_and_response_modes(self):
        self.assertEqual(self.run_checker(), [('crm', False), ('billing', False),
                                              ('crm', True), ('billing', True)])

    def test_wrong_namespace_is_a_failure(self):
        with self.assertRaisesRegex(SystemExit, 'responses-collision-crm'):
            self.run_checker(wrong_namespace=True)


if __name__ == '__main__':
    unittest.main()
