import base64
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user

from ..controllers.ai import CustomAIController

@tagged('post_install', '-at_install')
class ProviderPrivacyCase(TransactionCase):

    # Prepare an endpoint without granting data-sharing permission.
    def setUp(self):
        super().setUp()
        self.provider = self.env['ai.provider'].create({'name': 'Privacy test', 'technical_name': 'openai', 'base_url': 'https://example.invalid/v1', 'api_key': 'test-key'})
        self.model = self.env['ai.model'].create({'name': 'Privacy model', 'technical_name': 'test', 'provider_id': self.provider.id})
        self.agent = self.env['ai.agent'].create({'name': 'Privacy agent', 'custom_model_id': self.model.id})
        self.env['ir.config_parameter'].sudo().set_bool('tw_custom_ai_provider.use_global_model', False)

    # Block connection tests and conversation data before either adapter is called.
    def test_requests_require_authorization(self):
        with patch('odoo.addons.tw_custom_ai_provider.utils.openai_adapter.test_connection') as connection, patch('odoo.addons.tw_custom_ai_provider.utils.openai_adapter.get_completion') as completion:
            with self.assertRaises(UserError):
                self.provider.action_test_connection()
            with self.assertRaises(UserError):
                self.env['ai.session']._get_completions([], 'Private instructions', [], agent_id=self.agent.id)
            connection.assert_not_called()
            completion.assert_not_called()

    # Allow authorized requests and block them immediately after revocation.
    def test_authorization_and_revocation(self):
        self.assertFalse(self.model.is_api_ready)
        self.assertFalse(self.agent.is_custom_model_enabled)
        self.provider.data_sharing_accepted = True
        self.assertTrue(self.model.is_api_ready)
        self.assertTrue(self.agent.is_custom_model_enabled)
        self.assertEqual(self.provider._get_api_connection_vals()['api_key'], 'test-key')
        self.assertFalse(self.provider.copy({'name': 'Copy'}).data_sharing_accepted)
        self.provider.connection_status = 'success'
        self.provider.data_sharing_accepted = False
        self.assertFalse(self.model.is_api_ready)
        self.assertFalse(self.agent.is_custom_model_enabled)
        self.assertEqual(self.provider.connection_status, 'not_tested')
        with self.assertRaises(UserError):
            self.provider._get_api_connection_vals()

    # Block image and voice content before calling a media adapter.
    def test_media_requires_authorization(self):
        parameters = self.env['ir.config_parameter'].sudo()
        parameters.set_int('tw_custom_ai_provider.image_model_id', self.model.id)
        parameters.set_int('tw_custom_ai_provider.transcription_model_id', self.model.id)
        with patch('odoo.addons.tw_custom_ai_provider.utils.media_adapter.generate_images') as images, patch('odoo.addons.tw_custom_ai_provider.utils.media_adapter.transcribe_voice') as voice, patch('odoo.addons.tw_custom_ai_provider.controllers.ai.request', SimpleNamespace(env=self.env)):
            with self.assertRaises(UserError):
                self.env['ai.session']._get_completions([], 'Private image prompt', [], image_generation=True)
            with self.assertRaises(UserError):
                CustomAIController().transcribe(base64.b64encode(b'private audio').decode())
            images.assert_not_called()
            voice.assert_not_called()

    # Require a separate authorization after changing the destination.
    def test_endpoint_changes_clear_authorization(self):
        for values in [{'base_url': 'https://other.invalid/v1'}, {'technical_name': 'other'}]:
            self.provider.data_sharing_accepted = True
            self.provider.write({**values, 'data_sharing_accepted': True})
            self.assertFalse(self.provider.data_sharing_accepted)
            with self.assertRaises(UserError):
                self.provider._get_api_connection_vals()

    # Keep credentials and provider authorization restricted to administrators.
    def test_ordinary_user_cannot_read_keys_or_authorize(self):
        user = new_test_user(self.env, login='privacy_reader', groups='base.group_user')
        provider = self.provider.with_user(user)
        self.assertEqual(provider.name, self.provider.name)
        with self.assertRaises(AccessError):
            provider.read(['api_key'])
        with self.assertRaises(AccessError):
            provider.write({'data_sharing_accepted': True})
        with patch('odoo.addons.tw_custom_ai_provider.utils.openai_adapter.test_connection') as connection:
            with self.assertRaises(AccessError):
                provider.action_test_connection()
            connection.assert_not_called()

    # Stop asynchronous submission before saving a waiting request without consent.
    def test_async_requires_authorization(self):
        session = self.env['ai.session'].create({'agent_id': self.agent.id})
        with patch.object(type(session), '_submit_custom_provider_request') as submit, self.assertRaises(UserError), self.env.cr.savepoint():
            session._save_and_submit_request({'messages': []}, callback_type='agent_loop', request_round=1, request_round_limit=1, state={})
        submit.assert_not_called()
        self.assertNotEqual(session.loop_state, 'waiting_model')
