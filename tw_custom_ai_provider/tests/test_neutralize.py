from odoo.exceptions import UserError
from odoo.modules.neutralize import get_neutralization_queries
from odoo.tests import TransactionCase, tagged

@tagged('post_install', '-at_install')
class NeutralizationCase(TransactionCase):

    # Remove copied credentials and block external calls without changing model choices.
    def test_neutralization(self):
        # Step 1: cover the seeded provider, archived credentials and keyless endpoints.
        default_model = self.env.ref('tw_custom_ai_provider.ai_model_openrouter_default')
        default_provider = default_model.provider_id
        default_provider.write({'api_key': 'production-test-key', 'active': True})
        default_provider.connection_status = 'success'
        providers = default_provider | self.env['ai.provider'].create([
            {'name': 'Archived', 'technical_name': 'archived-test', 'api_key': 'archived-test-key', 'active': False, 'connection_status': 'error'},
            {'name': 'Keyless', 'technical_name': 'keyless-test', 'base_url': 'http://provider.test/v1', 'connection_status': 'success'},
        ])
        parameters = self.env['ir.config_parameter'].sudo()
        parameters.set_bool('tw_custom_ai_provider.use_global_model', True)
        parameters.set_int('tw_custom_ai_provider.global_model_id', default_model.id)
        before = providers.read(['name', 'technical_name', 'base_url'])
        # Step 2: discover the native script and prove repeated neutralization is safe.
        queries = list(get_neutralization_queries(['tw_custom_ai_provider']))
        self.assertEqual(len(queries), 1)
        for _iteration in range(2):
            self.env.flush_all()
            for query in queries:
                self.env.cr.execute(query)
            self.env.invalidate_all()
            self.assertFalse(any(providers.mapped('api_key')))
            self.assertFalse(any(providers.mapped('active')))
            self.assertEqual(set(providers.mapped('connection_status')), {'not_tested'})
            self.assertEqual(providers.read(['name', 'technical_name', 'base_url']), before)
        # Step 3: preserve the chosen model and fail rather than using Odoo credits.
        self.assertEqual(parameters.get_int('tw_custom_ai_provider.global_model_id'), default_model.id)
        self.assertTrue(parameters.get_bool('tw_custom_ai_provider.use_global_model'))
        self.assertTrue(default_model.active)
        with self.assertRaises(UserError):
            self.env['ai.model']._get_global_model()
        with self.assertRaises(ValueError):
            default_provider._get_api_connection_vals()
