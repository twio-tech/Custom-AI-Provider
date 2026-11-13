from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

@tagged('post_install', '-at_install')
class CustomProviderRoutingCase(TransactionCase):

    # Prepare the provider and agent records for each test.
    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_bool('tw_custom_ai_provider.use_global_model', False)
        self.provider = self.env['ai.provider'].create({
            'name': 'OpenAI Test',
            'technical_name': 'openai',
            'base_url': 'https://example.invalid/v1',
            'api_key': 'sk-test',
        })
        self.model = self.env['ai.model'].create({
            'name': 'GPT Test',
            'technical_name': 'gpt-test',
            'provider_id': self.provider.id,
        })
        self.agent = self.env['ai.agent'].create({'name': 'Widget'})

    # Route an agent request through its selected provider and model.
    def test_agent_routes_sync_completions_to_adapter(self):
        self.assertFalse(self.agent.custom_model_id)
        self.agent.write({'custom_model_id': self.model.id})
        from ..utils import openai_adapter
        captured = {}

        # Capture the completion arguments and return a test response.
        def fake_get_completion(connection, technical_name, params):
            captured['connection'] = connection
            captured['technical_name'] = technical_name
            captured['params'] = params
            return {'role': 'assistant', 'content': [{'type': 'text', 'text': 'from openai'}], 'provider_metadata': {}}
        with patch.object(openai_adapter, 'get_completion', side_effect=fake_get_completion):
            result = self.env['ai.session']._get_completions(
                [{'role': 'user', 'content': [{'type': 'text', 'text': 'Hi'}]}],
                'instructions text',
                [],
                agent_id=self.agent.id,
            )
        self.assertEqual(captured['connection']['api_key'], 'sk-test')
        self.assertEqual(captured['connection']['base_url'], 'https://example.invalid/v1')
        self.assertEqual(captured['technical_name'], 'gpt-test')
        self.assertEqual(captured['params']['instructions'], 'instructions text')
        self.assertEqual(result, {'result': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'from openai'}], 'provider_metadata': {}}})

    # Preserve Odoo AI routing for agents without a custom model.
    def test_agent_without_model_keeps_super(self):
        self.agent.write({})  # no custom model
        from ..utils import openai_adapter
        with patch.object(openai_adapter, 'get_completion') as fake:
            with patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai',
                return_value={'result': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'iap'}]}},
            ) as fake_iap:
                result = self.env['ai.session']._get_completions(
                    [{'role': 'user', 'content': [{'type': 'text', 'text': 'Hi'}]}],
                    'instructions',
                    [],
                    agent_id=self.agent.id,
                )
        fake.assert_not_called()
        self.assertTrue(fake_iap.called)
        self.assertEqual(result, {'result': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'iap'}]}})
