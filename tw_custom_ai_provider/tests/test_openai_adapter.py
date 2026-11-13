from unittest.mock import patch
from odoo.tests import TransactionCase

class OpenAIAdapterCase(TransactionCase):

    # Preserve system instructions and user text in the API request.
    def test_convert_simple_conversation(self):
        from ..utils import openai_adapter
        params = {
            'messages': [
                {'role': 'user', 'content': [{'type': 'text', 'text': 'Hello'}]},
            ],
            'instructions': 'You are a helper.',
        }
        body = openai_adapter._build_request('gpt-4o', params)
        self.assertEqual(
            body['messages'],
            [
                {'role': 'system', 'content': 'You are a helper.'},
                {'role': 'user', 'content': 'Hello'},
            ],
        )
        self.assertNotIn('tools', body)

    # Preserve tool calls, results and following user text in request order.
    def test_convert_tools_and_toolcalls_roundtrip(self):
        from ..utils import openai_adapter
        params = {
            'messages': [
                {'role': 'user', 'content': [{'type': 'text', 'text': 'Find leads in Paris'}]},
                {'role': 'assistant', 'content': [{
                    'type': 'tool_call',
                    'name': 'ai_tool_search',
                    'args': {'domain': []},
                    'call_id': 'call_abc',
                }]},
                {'role': 'user', 'content': [{
                    'type': 'tool_result',
                    'tool_name': 'ai_tool_search',
                    'tool_call_id': 'call_abc',
                    'result': [{'type': 'text', 'text': '2 leads'}],
                    'success': True,
                },
                {'type': 'text', 'text': 'and then answer'}]},
            ],
            'instructions': 'instructions',
            'tools': [{
                'name': 'ai_tool_search',
                'instructions': 'Search stuff',
                'schema': {'type': 'object', 'properties': {'domain': {'type': 'string'}}, 'required': ['domain']},
            }],
        }
        body = openai_adapter._build_request('gpt-4o', params)
        self.assertEqual(len(body['tools']), 1)
        self.assertEqual(body['tools'][0]['function']['name'], 'ai_tool_search')
        assistant = body['messages'][2]
        self.assertEqual(assistant['role'], 'assistant')
        self.assertEqual(assistant['tool_calls'][0]['id'], 'call_abc')
        tool = body['messages'][3]
        self.assertEqual(tool['role'], 'tool')
        self.assertEqual(tool['tool_call_id'], 'call_abc')
        self.assertEqual(tool['content'], '2 leads')
        final_user = body['messages'][4]
        self.assertEqual(final_user['role'], 'user')
        self.assertIn('and then answer', final_user['content'])

    # Convert provider tool calls into Odoo message parts.
    def test_convert_response_text_and_toolcalls(self):
        from ..utils import openai_adapter
        response = {
            'choices': [{
                'message': {
                    'content': None,
                    'tool_calls': [{
                        'id': 'call_1',
                        'type': 'function',
                        'function': {'name': 'ai_tool_search', 'arguments': '{"domain": "[[1, =, 1]]"}'},
                    }],
                },
            }],
            'model': 'gpt-4o-mini',
        }
        message = openai_adapter._convert_response(response)
        self.assertEqual(message['role'], 'assistant')
        self.assertEqual(len(message['content']), 1)
        self.assertEqual(message['content'][0]['type'], 'tool_call')
        self.assertEqual(message['content'][0]['name'], 'ai_tool_search')
        self.assertEqual(message['content'][0]['call_id'], 'call_1')

    # Send a structured response schema when no tools are present.
    def test_convert_response_schema_format(self):
        from ..utils import openai_adapter
        schema = {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']}
        params = {
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Q'}]}],
            'schema': schema,
        }
        body = openai_adapter._build_request('gpt-4o-mini', params)
        self.assertEqual(body['response_format']['type'], 'json_schema')
        self.assertEqual(body['response_format']['json_schema']['schema'], schema)

    # Omit the model key when OpenRouter selects the account default.
    def test_account_default_omits_model(self):
        from ..utils import openai_adapter
        body = openai_adapter._build_request(None, {'messages': []})
        self.assertNotIn('model', body)
        self.assertEqual(openai_adapter._build_request('gpt-test', {'messages': []})['model'], 'gpt-test')

    # Send a default-model request and retain the model returned by OpenRouter.
    def test_default_completion_request(self):
        from ..utils import openai_adapter
        with patch.object(openai_adapter.requests, 'post') as post:
            post.return_value.status_code = 200
            post.return_value.headers = {}
            post.return_value.json.return_value = {'model': 'resolved/model', 'choices': [{'message': {'content': 'Hello'}}]}
            result = openai_adapter.get_completion({'base_url': 'https://openrouter.ai/api/v1', 'api_key': 'test'}, None, {'messages': []})
        self.assertNotIn('model', post.call_args.kwargs['json'])
        self.assertEqual(post.call_args.args[0], 'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual(result['provider_metadata']['custom_model'], 'resolved/model')
