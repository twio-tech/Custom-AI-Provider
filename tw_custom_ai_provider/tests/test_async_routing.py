import contextlib
from unittest.mock import patch
from odoo import api, sql_db
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import Callbacks

CANNED_MESSAGE = {
    'role': 'assistant',
    'content': [{'type': 'text', 'text': 'hello from openai'}],
    'provider_metadata': {'provider': 'openai'},
}

@tagged('post_install', '-at_install')
class CustomProviderAsyncCase(TransactionCase):

    # Prepare the provider and agent records for each test.
    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_bool('tw_custom_ai_provider.use_global_model', False)
        self.provider = self.env['ai.provider'].create({
            'name': 'OpenAI Async',
            'technical_name': 'openai',
            'base_url': 'https://example.invalid/v1',
            'api_key': 'sk-test',
        })
        self.model = self.env['ai.model'].create({
            'name': 'GPT Async',
            'technical_name': 'gpt-test',
            'provider_id': self.provider.id,
        })

    # Start a provider worker only when a real database transaction commits.
    def test_worker_starts_after_commit(self):
        vals = {'request_user_id': self.env.uid, 'request_uuid': 'commit-test', 'request_context': {}, 'request_guest_id': False}
        with sql_db.db_connect(self.env.cr.dbname).cursor() as cr, patch('odoo.addons.tw_custom_ai_provider.models.ai_session.threading.Thread') as thread:
            session = api.Environment(cr, self.env.uid, {})['ai.session']
            session._submit_custom_provider_request({}, {}, 'test-model', vals)
            thread.assert_not_called()
            cr.commit()
            thread.assert_called_once()
            thread.return_value.start.assert_called_once()

    # Discard provider work when the transaction is rolled back.
    def test_rollback_does_not_start_worker(self):
        vals = {'request_user_id': self.env.uid, 'request_uuid': 'rollback-test', 'request_context': {}, 'request_guest_id': False}
        with sql_db.db_connect(self.env.cr.dbname).cursor() as cr, patch('odoo.addons.tw_custom_ai_provider.models.ai_session.threading.Thread') as thread:
            session = api.Environment(cr, self.env.uid, {})['ai.session']
            session._submit_custom_provider_request({}, {}, 'test-model', vals)
            cr.rollback()
            cr.commit()
            thread.assert_not_called()

    # Run the asynchronous worker inline for the test.
    def _run_sync_thread(self, session):
        captured = {}

        class FakeThread:
            # Capture the worker without starting another thread.
            def __init__(self, target=None, **kwargs):
                captured['target'] = target

            # Run the captured worker.
            def start(self):
                captured['target']()
        with patch('odoo.addons.tw_custom_ai_provider.models.ai_session.threading.Thread', FakeThread), patch.object(self.env.cr, 'postcommit', Callbacks()) as after_commit:
            with patch(
                'odoo.addons.tw_custom_ai_provider.utils.openai_adapter.get_completion',
                return_value=CANNED_MESSAGE,
            ) as fake_completion:
                session._save_and_submit_request(
                    {
                        'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Hi'}]}],
                        'instructions': 'instructions',
                        'tools': [],
                    },
                    callback_type='agent_loop',
                    request_round=1,
                    request_round_limit=1,
                    state={},
                )
                fake_completion.assert_not_called()
                if session.agent_id.custom_model_id:
                    self.assertTrue(len(after_commit))
                    after_commit.run()
        return fake_completion, captured

    # Submit custom requests after commit and preserve standard routing.
    def test_async_completion_continues_loop(self):
        agent = self.env['ai.agent'].create({
            'name': 'Async Agent 2',
        })
        session = self.env['ai.session'].create({'agent_id': agent.id})
        fake_completion, _ = self._run_sync_thread(session)
        fake_completion.assert_not_called()  # agent without custom model keeps the IAP flow untouched
        agent.write({'custom_model_id': self.model.id})
        fake_completion, _ = self._run_sync_thread(session)
        self.assertTrue(fake_completion.called)
        connection = fake_completion.call_args[0][0]
        self.assertEqual(connection['api_key'], 'sk-test')
        self.assertEqual(fake_completion.call_args[0][1], 'gpt-test')

    # Finish the exchange and store the returned assistant message.
    def test_async_session_reaches_ready_without_tools(self):
        agent = self.env['ai.agent'].create({
            'name': 'Async Agent 3',
            'custom_model_id': self.model.id,
        })
        session = self.env['ai.session'].create({'agent_id': agent.id})
        # Use the test cursor to check continuation separately from transaction visibility.
        test_cr = self.env.cr

        class FakeRegistry:
            # Accept the database name without opening a new connection.
            def __init__(self, dbname):
                pass

            # Return the test cursor without committing.
            def cursor(self):
                return contextlib.nullcontext(test_cr)
        with patch(
            'odoo.addons.tw_custom_ai_provider.models.ai_session.Registry', FakeRegistry,
        ):
            with patch.object(
                type(session), '_post_ai_response', lambda self, content: None,
            ):
                self._run_sync_thread(session)
        self.assertEqual(session.loop_state, 'ready')
        assistant_events = [
            event for event in session.event_ids
            if event.metadata.get('role') == 'assistant'
        ]
        self.assertTrue(assistant_events)
        self.assertEqual(assistant_events[0].metadata['content'], CANNED_MESSAGE['content'])
