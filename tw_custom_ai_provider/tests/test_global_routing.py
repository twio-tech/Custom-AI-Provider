from unittest.mock import patch
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError
from ..hooks import post_init_hook

@tagged('post_install', '-at_install')
class GlobalRoutingCase(TransactionCase):

    # Set a global OpenRouter model and an agent with a different model.
    def setUp(self):
        super().setUp()
        self.parameters = self.env['ir.config_parameter'].sudo()
        self.default_model = self.env.ref('tw_custom_ai_provider.ai_model_openrouter_default')
        self.default_model.provider_id.write({'api_key': 'test-key', 'data_sharing_accepted': True})
        self.parameters.set_bool('tw_custom_ai_provider.use_global_model', True)
        self.parameters.set_int('tw_custom_ai_provider.global_model_id', self.default_model.id)
        self.other_model = self.env['ai.model'].create({'name': 'Other', 'technical_name': 'other', 'provider_id': self.default_model.provider_id.id})
        self.agent = self.env['ai.agent'].create({'name': 'Global Test', 'custom_model_id': self.other_model.id})

    # Override every synchronous request including requests without an agent.
    def test_sync_global_model(self):
        for options in ({}, {'agent_id': self.agent.id}):
            with patch('odoo.addons.tw_custom_ai_provider.utils.openai_adapter.get_completion', return_value={}) as completion:
                self.env['ai.session']._get_completions([], '', [], **options)
            self.assertIsNone(completion.call_args.args[1])
            self.assertEqual(completion.call_args.args[0]['api_key'], 'test-key')
        self.assertEqual(self.agent.custom_model_id, self.other_model)
        self.assertTrue(self.agent.use_global_model)
        self.assertEqual(self.agent.global_model_display_name, self.default_model.name_with_provider)

    # Override root, child and auxiliary sessions with the global selection.
    def test_session_resolution(self):
        root = self.env['ai.session'].create({'agent_id': self.agent.id})
        child = self.env['ai.session'].create({'agent_id': self.agent.id, 'parent_session_id': root.id})
        auxiliary = self.env['ai.session'].create({'parent_session_id': root.id})
        for session in (root, child, auxiliary):
            self.assertEqual(session._get_custom_llm_model(), self.default_model)
        self.parameters.set_bool('tw_custom_ai_provider.use_global_model', False)
        for session in (root, child, auxiliary):
            self.assertEqual(session._get_custom_llm_model(), self.other_model)
        self.assertFalse(self.env['ai.session']._get_custom_llm_model_from_options({}))

    # Send asynchronous requests without an API model identifier.
    def test_async_global_model(self):
        session = self.env['ai.session'].create({'agent_id': self.agent.id})
        with patch.object(type(session), '_submit_custom_provider_request') as submit:
            session._save_and_submit_request({'messages': []}, callback_type='agent_loop', request_round=1, request_round_limit=1, state={})
        self.assertIsNone(submit.call_args.args[2])
        self.assertEqual(session.loop_state, 'waiting_model')

    # Reject invalid global settings without falling back to Odoo credits.
    def test_invalid_configuration(self):
        self.parameters.set_int('tw_custom_ai_provider.global_model_id', 0)
        with self.assertRaises(UserError):
            self.env['ai.session']._get_custom_llm_model_from_options({})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['res.config.settings'].create({'ai_use_global_model': True, 'ai_global_model_id': False})
        self.parameters.set_int('tw_custom_ai_provider.global_model_id', self.other_model.id)
        self.other_model.active = False
        with self.assertRaises(UserError):
            self.env['ai.session']._get_custom_llm_model_from_options({})
        self.parameters.set_int('tw_custom_ai_provider.global_model_id', self.default_model.id)
        self.default_model.provider_id.api_key = False
        with self.assertRaises(UserError):
            self.env['ai.session']._get_completions([], '', [])
        self.default_model.provider_id.active = False
        with self.assertRaises(UserError):
            self.env['ai.session']._get_completions([], '', [])

    # Keep the protected model and its provider intact.
    def test_default_model_protection(self):
        for vals in ({'active': False}, {'technical_name': 'changed'}, {'is_openrouter_default': False}):
            with self.assertRaises(UserError):
                self.default_model.write(vals)
        with self.assertRaises(UserError):
            self.default_model.unlink()
        with self.assertRaises(UserError):
            self.default_model.provider_id.unlink()
        provider = self.env['ai.provider'].create({'name': 'Other', 'technical_name': 'other'})
        with self.assertRaises(UserError):
            self.default_model.provider_id = provider

    # Initialize fresh installs and preserve already stored choices.
    def test_install_defaults(self):
        keys = ['tw_custom_ai_provider.use_global_model', 'tw_custom_ai_provider.global_model_id']
        self.parameters.search([('key', 'in', keys)]).unlink()
        self.assertFalse(self.env['ai.model']._get_global_model())
        post_init_hook(self.env)
        self.assertEqual(self.env['ai.model']._get_global_model(), self.default_model)
        self.parameters.set_bool(keys[0], False)
        self.parameters.set_int(keys[1], self.other_model.id)
        post_init_hook(self.env)
        self.assertFalse(self.parameters.get_bool(keys[0]))
        self.assertEqual(self.parameters.get_int(keys[1]), self.other_model.id)

    # Send explicit global model identifiers and allow an ordinary model to be removed.
    def test_explicit_global_model(self):
        self.parameters.set_int('tw_custom_ai_provider.global_model_id', self.other_model.id)
        with patch('odoo.addons.tw_custom_ai_provider.utils.openai_adapter.get_completion', return_value={}) as completion:
            self.env['ai.session']._get_completions([], '', [])
        self.assertEqual(completion.call_args.args[1], 'other')
        self.parameters.set_bool('tw_custom_ai_provider.use_global_model', False)
        self.other_model.unlink()

    # Reject incomplete global configuration before any asynchronous submission.
    def test_async_invalid_configuration(self):
        session = self.env['ai.session'].create({'agent_id': self.agent.id})
        self.default_model.provider_id.api_key = False
        with patch.object(type(session), '_submit_custom_provider_request') as submit:
            with self.assertRaises(UserError):
                session._save_and_submit_request({'messages': []}, callback_type='agent_loop', request_round=1, request_round_limit=1, state={})
        submit.assert_not_called()
        self.assertNotEqual(session.loop_state, 'waiting_model')

    # Keep seeded records stable during upgrades and initialize the OpenRouter endpoint.
    def test_seeded_records(self):
        provider = self.env.ref('tw_custom_ai_provider.ai_provider_openrouter')
        self.assertEqual(provider.base_url, 'https://openrouter.ai/api/v1')
        self.assertEqual(self.default_model.provider_id, provider)
        self.assertTrue(self.default_model.is_openrouter_default)
        data = self.env['ir.model.data'].search([('module', '=', 'tw_custom_ai_provider'), ('name', 'in', ['ai_provider_openrouter', 'ai_model_openrouter_default'])])
        self.assertEqual(len(data), 2)
        self.assertTrue(all(data.mapped('noupdate')))
