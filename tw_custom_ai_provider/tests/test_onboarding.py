from unittest.mock import patch

from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tests.common import new_test_user

@tagged('post_install', '-at_install')
class OpenRouterOnboardingCase(TransactionCase):

    # Offer setup to administrators and hide it from ordinary users.
    def test_tour_access(self):
        tour = self.env.ref('tw_custom_ai_provider.openrouter_setup_tour')
        self.assertIn(tour, self.env['web_tour.tour'].search([]))
        user = new_test_user(self.env, login='openrouter_reader', groups='base.group_user')
        self.assertNotIn(tour, self.env['web_tour.tour'].with_user(user).search([]))
        admin = self.env.ref('base.user_admin')
        admin.tour_enabled = True
        tours = self.env['web_tour.tour'].with_user(admin)
        current = tours.get_current_tour()
        self.assertEqual(current['name'], tour.name)
        tours.consume(tour.name)
        self.assertIn(admin, tour.user_consumed_ids)

@tagged('post_install', '-at_install')
class OpenRouterTourCase(HttpCase):

    # Check the setup screens using the automatic tour runner.
    def test_openrouter_setup(self):
        self._run_setup_tour()

    # Check the actual onboarding tooltips and user interaction sequence.
    def test_openrouter_interactive_setup(self):
        self._run_setup_tour(code="odoo.startTour('tw_custom_ai_provider_openrouter', {mode: 'manual', robot: true})")

    # Mock the provider while exercising credential entry and connection feedback.
    def _run_setup_tour(self, **options):
        admin = self.env.ref('base.user_admin')
        admin.tour_enabled = False
        with patch('odoo.addons.tw_custom_ai_provider.utils.openai_adapter.test_connection', return_value={'ok': True, 'message': 'Connection test succeeded (test).'}) as connection:
            self.start_tour('/odoo', 'tw_custom_ai_provider_openrouter', login='admin', **options)
        connection.assert_called_once()
        provider = self.env.ref('tw_custom_ai_provider.ai_provider_openrouter')
        provider.invalidate_recordset(['api_key'])
        self.assertEqual(provider.api_key, 'tour-test-key')
        self.assertEqual(provider.connection_status, 'success')
