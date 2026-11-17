import base64
from unittest.mock import Mock, patch
from odoo import fields
from odoo.tools import file_open
from datetime import timedelta
from odoo.tests import TransactionCase
from ..utils import media_adapter, provider_http

class MediaCase(TransactionCase):

    # Convert generated images and preserve instructions and reference inputs.
    def test_images(self):
        data = base64.b64encode(b'\x89PNGtest').decode()
        with patch.object(media_adapter, 'post_json', return_value={'data': [{'b64_json': data, 'media_type': 'image/png'}]}) as post:
            result = media_adapter.generate_images({}, 'image-model', [{'content': [{'type': 'text', 'text': 'draw'}, {'type': 'inline_data', 'data': data, 'mimetype': 'image/png'}]}], 'instructions', '16:9')
        self.assertEqual(result['content'][0]['data'], data)
        self.assertEqual(post.call_args.args[2]['aspect_ratio'], '16:9')
        self.assertIn('instructions', post.call_args.args[2]['prompt'])
        self.assertTrue(post.call_args.args[2]['input_references'])

    # Convert transcription timing to valid VTT and reject missing timing.
    def test_transcription(self):
        payload = {'segments': [{'start': 1.25, 'end': 3.5, 'text': 'Hello'}]}
        with patch.object(media_adapter, 'post_json', return_value=payload) as post:
            transcript = media_adapter.transcribe_audio({}, 'stt-model', b'audio', 'audio/webm')
        self.assertIn('00:00:01.250 --> 00:00:03.500', transcript)
        self.assertEqual(post.call_args.args[1], 'audio/transcriptions')
        self.assertEqual(post.call_args.args[2]['response_format'], 'verbose_json')
        with self.assertRaises(provider_http.UserErrorFromProvider):
            media_adapter.transcript_to_vtt({'text': 'Hello'})

    # Reject embedded errors and retry temporary rate limits with Retry-After.
    def test_errors(self):
        response = Mock(status_code=200, headers={})
        response.json.return_value = {'error': {'code': 401, 'message': 'private provider details'}}
        with patch.object(provider_http.requests, 'post', return_value=response):
            with self.assertRaises(provider_http.UserErrorFromProvider) as raised:
                provider_http.post_json({'base_url': 'https://example.invalid', 'api_key': 'test'}, 'images', {})
        self.assertEqual(raised.exception.status, 401)
        self.assertNotIn('private', str(raised.exception))
        limited = Mock(status_code=429, headers={'Retry-After': '2'})
        limited.json.return_value = {'error': {'code': 429}}
        success = Mock(status_code=200, headers={})
        success.json.return_value = {'ok': True}
        with patch.object(provider_http.requests, 'post', side_effect=[limited, success]) as post, patch.object(provider_http.time, 'sleep') as sleep:
            self.assertEqual(provider_http.post_json({'base_url': 'https://example.invalid', 'api_key': 'test'}, 'images', {}), {'ok': True})
        sleep.assert_called_once_with(2)
        self.assertEqual(post.call_count, 2)

    # Route image requests independently of the conversation default.
    def test_image_routing(self):
        parameters = self.env['ir.config_parameter'].sudo()
        parameters.set_bool('tw_custom_ai_provider.use_global_model', True)
        provider = self.env.ref('tw_custom_ai_provider.ai_provider_openrouter')
        provider.write({'api_key': 'test', 'data_sharing_accepted': True})
        model = self.env['ai.model'].create({'name': 'Images', 'technical_name': 'images/test', 'provider_id': provider.id})
        parameters.set_int('tw_custom_ai_provider.image_model_id', model.id)
        with patch.object(media_adapter, 'generate_images', return_value={}) as generate:
            self.env['ai.session']._get_completions([], 'prompt', [], image_generation=True)
        self.assertEqual(generate.call_args.args[1], 'images/test')
        parameters.set_int('tw_custom_ai_provider.image_model_id', 0)
        with patch.object(media_adapter, 'generate_images', return_value={}) as generate:
            self.env['ai.session']._get_completions([], '', [], image_generation=True)
        self.assertIsNone(generate.call_args.args[1])

    # Preserve queue leases and failed recordings when a permanent provider error occurs.
    def test_transcription_queue(self):
        parameters = self.env['ir.config_parameter'].sudo()
        parameters.set_bool('tw_custom_ai_provider.use_global_model', True)
        provider = self.env.ref('tw_custom_ai_provider.ai_provider_openrouter')
        provider.write({'api_key': 'test', 'data_sharing_accepted': True})
        model = self.env['ai.model'].create({'name': 'Transcription', 'technical_name': 'stt/test', 'provider_id': provider.id})
        parameters.set_int('tw_custom_ai_provider.transcription_model_id', model.id)
        channel = self.env['discuss.channel'].create({'name': 'Transcription Test'})
        call = self.env['discuss.call.history'].create({'channel_id': channel.id, 'start_dt': fields.Datetime.now()})
        lease = fields.Datetime.now() + timedelta(minutes=5)
        artifact = self.env['mail.call.artifact'].create({'discuss_call_history_id': call.id, 'start_ms': 0, 'end_ms': 1000, 'is_stt': True, 'transcription_state': 'pending', 'transcription_locked_until': lease})
        attachment = self.env['ir.attachment'].create({'name': 'recording.webm', 'raw': b'audio', 'mimetype': 'audio/webm', 'res_model': artifact._name, 'res_id': artifact.id})
        artifact.invalidate_recordset(['media_id'])
        with patch.object(media_adapter, 'transcribe_audio', return_value='WEBVTT\n\n') as transcribe:
            result = artifact._transcribe_claimed_record(lease)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(transcribe.call_args.args[1], 'stt/test')
        with patch.object(media_adapter, 'transcribe_audio', side_effect=provider_http.UserErrorFromProvider('Invalid credentials', status=401)):
            result = artifact._transcribe_claimed_record(lease)
        with patch.object(type(call), '_after_artifact_transcription_error'):
            self.assertTrue(artifact._finalize_transcription(lease, result))
        self.assertEqual(artifact.transcription_state, 'error')
        self.assertEqual(artifact.transcription_error_msg, 'Invalid credentials')
        self.assertTrue(attachment.exists())

    # Avoid repeated charges on timeouts and honor long provider retry delays.
    def test_retry_limits(self):
        connection = {'base_url': 'https://example.invalid', 'api_key': 'test'}
        for status, headers in ((402, {}), (403, {}), (429, {'Retry-After': '60'})):
            response = Mock(status_code=status, headers=headers)
            response.json.return_value = {'error': {'code': status}}
            with patch.object(provider_http.requests, 'post', return_value=response) as post, patch.object(provider_http.time, 'sleep') as sleep:
                with self.assertRaises(provider_http.UserErrorFromProvider):
                    provider_http.post_json(connection, 'images', {})
            post.assert_called_once()
            sleep.assert_not_called()
        with patch.object(provider_http.requests, 'post', side_effect=provider_http.requests.Timeout) as post:
            with self.assertRaises(provider_http.UserErrorFromProvider):
                provider_http.post_json(connection, 'images', {})
        post.assert_called_once()

    # Use standard image and multipart transcription endpoints for other providers.
    def test_other_provider_media(self):
        connection = {'provider_type': 'openai'}
        data = base64.b64encode(b'\x89PNGtest').decode()
        with patch.object(media_adapter, 'post_json', return_value={'data': [{'b64_json': data}]}) as post:
            media_adapter.generate_images(connection, 'gpt-image-1', [{'content': [{'type': 'text', 'text': 'draw'}]}])
        self.assertEqual(post.call_args.args[1], 'images/generations')
        with patch.object(media_adapter, 'post_json', return_value={'segments': [{'start': 0, 'end': 1, 'text': 'Hello'}]}) as post:
            media_adapter.transcribe_audio(connection, 'whisper-1', b'audio', 'audio/wav')
        self.assertIn('file', post.call_args.kwargs['files'])
        provider = self.env['ai.provider'].create({'name': 'Other', 'technical_name': 'openai', 'api_key': 'test'})
        model = self.env['ai.model'].create({'name': 'Other Model', 'technical_name': 'test', 'provider_id': provider.id})
        self.env['res.config.settings'].create({'ai_image_model_id': model.id, 'ai_transcription_model_id': model.id})
        self.env['ir.config_parameter'].sudo().set_int('tw_custom_ai_provider.image_model_id', model.id)
        self.assertEqual(self.env['ai.model']._get_media_model('image'), model)

    # Store generated images as decoded binaries through the actual Odoo image tool.
    def test_generated_image_attachment(self):
        parameters = self.env['ir.config_parameter'].sudo()
        parameters.set_bool('tw_custom_ai_provider.use_global_model', True)
        with file_open('ai/static/description/icon.png', 'rb') as image:
            data = base64.b64encode(image.read()).decode()
        parts = [{'type': 'inline_data', 'mimetype': 'image/png', 'data': data}]
        session = self.env['ai.session']
        with patch.object(type(session), '_get_direct_response', return_value=parts):
            result, attachments = self.env['ai.tool']._generate_image_attachments('draw', [], 'test')
        self.assertEqual(bytes(attachments.raw), base64.b64decode(data))
        self.assertEqual(result[0]['metadata']['attachment_id'], attachments.id)

    # Use the effective agent model when no dedicated image model is selected.
    def test_image_agent_fallback(self):
        parameters = self.env['ir.config_parameter'].sudo()
        parameters.set_bool('tw_custom_ai_provider.use_global_model', False)
        parameters.set_int('tw_custom_ai_provider.image_model_id', 0)
        provider = self.env.ref('tw_custom_ai_provider.ai_provider_openrouter')
        provider.write({'api_key': 'test', 'data_sharing_accepted': True})
        model = self.env['ai.model'].create({'name': 'Multimodal', 'technical_name': 'multimodal/test', 'provider_id': provider.id})
        agent = self.env['ai.agent'].create({'name': 'Fallback Test', 'custom_model_id': model.id})
        with patch.object(media_adapter, 'generate_images', return_value={}) as generate:
            self.env['ai.session'].with_context(custom_ai_agent_id=agent.id)._get_completions([], '', [], image_generation=True)
        self.assertEqual(generate.call_args.args[1], model.technical_name)

    # Omit model in default-account image chat requests and require an actual image.
    def test_image_default_fallback(self):
        data = base64.b64encode(b'\x89PNGtest').decode()
        payload = {'choices': [{'message': {'images': [{'image_url': {'url': 'data:image/png;base64,' + data}}]}}]}
        with patch.object(media_adapter, 'post_json', return_value=payload) as post:
            result = media_adapter.generate_images({'provider_type': 'openrouter'}, None, [{'role': 'user', 'content': [{'type': 'text', 'text': 'draw'}]}])
        self.assertEqual(post.call_args.args[1], 'chat/completions')
        self.assertNotIn('model', post.call_args.args[2])
        self.assertEqual(result['content'][0]['data'], data)
        with patch.object(media_adapter, 'post_json', return_value={'choices': [{'message': {'content': 'Text only'}}]}):
            with self.assertRaises(provider_http.UserErrorFromProvider):
                media_adapter.generate_images({'provider_type': 'openrouter'}, None, [])

    # Return plain voice transcription without requiring VTT timestamps.
    def test_chat_voice_transcription(self):
        from types import SimpleNamespace
        from ..controllers.ai import CustomAIController
        parameters = self.env['ir.config_parameter'].sudo()
        parameters.set_bool('tw_custom_ai_provider.use_global_model', True)
        provider = self.env.ref('tw_custom_ai_provider.ai_provider_openrouter')
        provider.write({'api_key': 'test', 'data_sharing_accepted': True})
        model = self.env['ai.model'].create({'name': 'Scribe', 'technical_name': 'scribe/test', 'provider_id': provider.id})
        parameters.set_int('tw_custom_ai_provider.transcription_model_id', model.id)
        with patch('odoo.addons.tw_custom_ai_provider.controllers.ai.request', SimpleNamespace(env=self.env)), patch.object(media_adapter, 'post_json', return_value={'text': 'Hello'}) as post:
            response = CustomAIController.transcribe.__wrapped__(CustomAIController(), base64.b64encode(b'audio').decode())
        self.assertEqual(response, {'status': 'success', 'text': 'Hello'})
        self.assertEqual(post.call_args.args[1], 'audio/transcriptions')
        self.assertEqual(post.call_args.args[2]['model'], 'scribe/test')
        self.assertEqual(post.call_args.args[2]['response_format'], 'json')

    # Surface empty recognition results instead of silently leaving the composer unchanged.
    def test_empty_voice_transcription(self):
        with patch.object(media_adapter, 'post_json', return_value={'text': '   '}):
            with self.assertRaises(provider_http.UserErrorFromProvider) as raised:
                media_adapter.transcribe_voice({'provider_type': 'openrouter'}, 'scribe/test', b'audio')
        self.assertEqual(raised.exception.error_type, 'empty_transcription')
