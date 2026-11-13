from odoo.tools.translate import LazyTranslate
import json
import logging

import requests

from .provider_http import UserErrorFromProvider, post_json

_lt = LazyTranslate(__name__)

_logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300
TEST_TIMEOUT = 15
REQUEST_BODY_KEYS = {'messages', 'instructions', 'tools', 'schema', 'boost_reasoning', 'web_grounding'}

# Build the provider request and omit an unspecified model.
def _build_request(technical_name, params):
    # Step 1: keep the completion fields supported by the adapter.
    params = {key: params[key] for key in REQUEST_BODY_KEYS if key in params}
    _degrade_unsupported_options(params)
    messages = params.get('messages') or []
    instructions = params.get('instructions') or ''
    tools = params.get('tools') or []
    schema = params.get('schema')
    # Step 2: add an explicit model only when one is selected.
    body = {
        'messages': _convert_messages(messages, instructions),
    }
    if technical_name:
        body['model'] = technical_name
    # Step 3: include tools or structured output options.
    if tools:
        body['tools'] = [_convert_tool(tool) for tool in tools]
        if schema:
            body['tool_choice'] = 'required'
    elif schema:
        body['response_format'] = {
            'type': 'json_schema',
            'json_schema': {
                'name': 'response',
                'strict': False,
                'schema': schema,
            },
        }
    if 'boost_reasoning' in params and params['boost_reasoning']:
        body['reasoning_effort'] = 'high'
    return body

# Log unsupported capabilities requested on a custom provider.
def _degrade_unsupported_options(params):
    if params.get('web_grounding'):
        _logger.info(
            "Custom AI provider: web_grounding is not "
            "supported, degrading to a text completion."
        )

# Convert messages and instructions to the provider format.
def _convert_messages(messages, instructions):
    openai_messages = []
    if instructions:
        openai_messages.append({'role': 'system', 'content': instructions})
    # Step 1: convert each message including tool results.
    for message in messages:
        openai_messages.extend(_convert_message(message))
    return openai_messages

# Convert one message including tool calls and results.
def _convert_message(message):
    role = message['role']
    parts = message.get('content') or []
    tool_calls = [part for part in parts if part['type'] == 'tool_call']
    tool_results = [part for part in parts if part['type'] == 'tool_result']
    other_parts = [part for part in parts if part['type'] not in ('tool_call', 'tool_result')]
    converted = []
    # Step 1: map user tool results and assistant tool calls to API roles.
    if role == 'user':
        converted.extend({
            'role': 'tool',
            'tool_call_id': tool_result.get('tool_call_id'),
            'content': _get_parts_text(tool_result.get('result') or []),
        } for tool_result in tool_results)
        if other_parts:
            converted.append({'role': 'user', 'content': _get_content(other_parts)})
    elif role == 'assistant':
        has_text_and_tools = bool(tool_calls)
        converted.append({
            'role': 'assistant',
            'content': _get_content(other_parts),
            **({'tool_calls': [_convert_tool_call(call) for call in tool_calls]} if has_text_and_tools else {}),
        })
    else:
        converted.append({'role': 'user', 'content': _get_content(other_parts)})
    return [msg for msg in converted if msg]

# Return plain text or mixed content parts.
def _get_content(parts):
    if all(part['type'] == 'text' for part in parts):
        return _get_parts_text(parts)
    return _get_openai_content_parts(parts)

# Convert a tool call to the provider format.
def _convert_tool_call(tool_call):
    return {
        'id': str(tool_call.get('call_id')),
        'type': 'function',
        'function': {
            'name': tool_call['name'],
            'arguments': json.dumps(tool_call.get('args') or {}),
        },
    }

# Convert text and supported attachments to provider content.
def _get_openai_content_parts(parts):
    content = []
    # Step 1: convert supported text, images and documents.
    for part in parts:
        if part['type'] == 'text':
            content.append({'type': 'text', 'text': part.get('text') or ''})
        elif part['type'] == 'inline_data':
            mimetype = part.get('mimetype') or ''
            data = part.get('data')
            if not data:
                continue
            if mimetype.startswith('image/'):
                content.append({
                    'type': 'image_url',
                    'image_url': {'url': f"data:{mimetype};base64,{data}"},
                })
            elif mimetype == 'application/pdf':
                content.append({
                    'type': 'file',
                    'file': {'format': 'pdf', 'file_data': f"data:application/pdf;base64,{data}"},
                })
            else:
                content.append({'type': 'text', 'text': "[unsupported document format omitted]"})
    return content

# Join the text from message parts.
def _get_parts_text(parts):
    return "\n".join(part.get('text', '') for part in parts if part['type'] == 'text' and part.get('text'))

# Convert the tool definition to the provider format.
def _convert_tool(tool):
    name = tool.get('name')
    parameters = tool.get('schema') or {'type': 'object', 'properties': {}, 'required': []}
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': tool.get('instructions') or '',
            'parameters': parameters,
            'strict': False,
        },
    }

# Convert the provider response and preserve its model and usage.
def _convert_response(response_json):
    choice = response_json['choices'][0]
    if choice.get('finish_reason') in ('error', 'content_filter') or choice.get('error'):
        raise UserErrorFromProvider(_lt("The AI model could not produce an allowed completion."), error_type=str(choice.get('finish_reason')))
    message = choice['message']
    content = []
    if message.get('content'):
        content.append({'type': 'text', 'text': message['content']})
    # Step 1: parse returned tool arguments into Odoo content.
    for tool_call in message.get('tool_calls') or []:
        function = tool_call['function']
        try:
            args = json.loads(function.get('arguments') or '{}')
        except ValueError:
            _logger.warning("Failed to parse tool call arguments: %s", function.get('arguments'))
            args = {}
        content.append({
            'type': 'tool_call',
            'name': function['name'],
            'args': args,
            'call_id': tool_call['id'],
        })
    return {
        'role': 'assistant',
        'content': content,
        'provider_metadata': {
            'provider': 'openai',
            'custom_model': response_json.get('model'),
            'usage': response_json.get('usage'),
        },
    }

# Send one provider completion and convert the response.
def get_completion(provider_vals, technical_name, params):
    body = _build_request(technical_name, params)
    _logger.info("Custom AI provider request: model=%s tools=%s schema=%s", body.get('model', '(account default)'), len(body.get('tools') or []), 'response_format' in body)
    payload = post_json(provider_vals, 'chat/completions', body, timeout=DEFAULT_TIMEOUT)
    try:
        message = _convert_response(payload)
    except (KeyError, IndexError, TypeError) as error:
        raise UserErrorFromProvider(_lt("The AI provider returned an invalid completion response."), error_type='invalid_response') from error
    if not message['content']:
        raise UserErrorFromProvider(_lt("The AI model returned no content. Check its output and reasoning limits."), error_type='empty_response')
    return message

# Return the provider error text.
def _extract_error_message(response):
    try:
        return response.json().get('error', {}).get('message') or response.text[:500]
    except ValueError:
        return response.text[:500]

# Check the provider models endpoint.
def test_connection(provider_vals):
    try:
        response = requests.get(
            f"{provider_vals['base_url']}/models",
            headers={'Authorization': f"Bearer {provider_vals['api_key']}"},
            timeout=TEST_TIMEOUT,
        )
        if response.status_code == 200:
            count = len(response.json().get('data', []))
            return {'ok': True, 'message': _lt("Connection test succeeded (%(count)s models available).", count=count)}
        return {'ok': False, 'message': _lt("Error %(status)s: %(message)s", status=response.status_code, message=_extract_error_message(response))}
    except Exception as exception:  # noqa: BLE001
        return {'ok': False, 'message': str(exception)}
