import copy
import logging
import threading
import uuid

from odoo import api, models, _
from odoo.exceptions import UserError
from odoo.modules.registry import Registry
from odoo.orm.utils import SUPERUSER_ID

from ..utils import openai_adapter, media_adapter

_logger = logging.getLogger(__name__)

class AiSession(models.Model):
    _inherit = 'ai.session'

    # Resolve the global model first, then the agent or root session model.
    def _resolve_custom_llm_model(self, agent=None):
        # Step 1: apply the database-wide selection before looking at agents.
        model = self.env['ai.model']._get_global_model()
        if model:
            return model
        # Step 2: inherit the root agent for auxiliary sessions.
        if agent is None:
            agent = self.sudo().agent_id if self else self.env['ai.agent']
            if not agent and self and self.parent_session_id:
                agent = self.sudo()._root_session().agent_id
        model = agent.sudo().custom_model_id if agent else self.env['ai.model']
        if model and (not model.active or not model.provider_id.active):
            raise UserError(_("The agent AI model or provider is archived."))
        return model

    # Return the effective model for an asynchronous session request.
    def _get_custom_llm_model(self):
        self.ensure_one()
        return self._resolve_custom_llm_model()

    # Return the effective model for a synchronous completion request.
    def _get_custom_llm_model_from_options(self, options):
        agent = self.env['ai.agent'].sudo().browse((options.get('agent_id') or self.env.context.get('custom_ai_agent_id'))).exists() if options.get('agent_id') or self.env.context.get('custom_ai_agent_id') else None
        return self._resolve_custom_llm_model(agent)

    # Send a synchronous completion through the effective provider.
    def _get_completions(self, messages, instructions, tools, **options):
        # Step 1: resolve specialized image requests before conversation routing.
        if options.get('image_generation'):
            parameters = self.env['ir.config_parameter'].sudo()
            if parameters.get_int('tw_custom_ai_provider.image_model_id'):
                image_model = self.env['ai.model']._get_media_model('image', required=True)
            else:
                image_model = self._get_custom_llm_model_from_options(options)
            if image_model:
                connection = image_model.provider_id.sudo()._get_api_connection_vals()
                return {'result': media_adapter.generate_images(connection, image_model._get_api_model_name(), messages, instructions, options.get('aspect_ratio'))}
            return super()._get_completions(messages, instructions, tools, **options)
        # Step 2: use the effective conversation model for text requests.
        llm_model = self._get_custom_llm_model_from_options(options)
        if llm_model:
            connection = llm_model.provider_id.sudo()._get_api_connection_vals()
            message = openai_adapter.get_completion(connection, llm_model._get_api_model_name(), {
                'messages': messages,
                'instructions': instructions,
                'tools': tools or [],
                **options,
            })
            return {'result': message}
        return super()._get_completions(messages, instructions, tools, **options)

    # Save the request and submit it through the effective provider.
    def _save_and_submit_request(
        self, payload, *, callback_type,
        request_round, request_round_limit,
        state,
    ) -> None:
        # Step 1: resolve the model before creating a waiting request.
        self.ensure_one()
        llm_model = self._get_custom_llm_model()
        if not (llm_model and llm_model.provider_id):
            return super()._save_and_submit_request(
                payload,
                callback_type=callback_type,
                request_round=request_round,
                request_round_limit=request_round_limit,
                state=state,
            )
        # Step 2: save the request state used by the continuation.
        guest = self.env.context.get("guest")
        vals = {
            "loop_state": "waiting_model",
            "request_uuid": str(uuid.uuid4()),
            "request_webhook_secret": uuid.uuid4().hex,
            "request_round": request_round,
            "request_round_limit": request_round_limit,
            "request_payload": payload,
            "request_user_id": self.env.uid,
            "request_guest_id": guest.id if guest else False,
            "request_context": self._get_request_context_snapshot(),
            "resume_token": False,
            "pending_tool_call": False,
        }
        state["callback_type"] = callback_type
        vals["state"] = state
        self.write(vals)
        self._publish_response_state()
        # Step 3: submit the provider request or schedule a failure.
        try:
            connection = llm_model.provider_id.sudo()._get_api_connection_vals()
        except ValueError:
            connection = None
        if not connection:
            self._submit_custom_provider_request_failure(vals)
            return
        self._submit_custom_provider_request(copy.deepcopy(payload), connection, llm_model._get_api_model_name(), vals)

    # Report a configuration failure after the transaction commits.
    def _submit_custom_provider_request_failure(self, vals):
        # Step 1: copy the request identity before the transaction closes.
        dbname = self.env.cr.dbname
        user_id = vals["request_user_id"]
        request_uuid = vals["request_uuid"]
        context = vals["request_context"]
        guest_id = vals["request_guest_id"]

        # Step 2: apply the failed request result after commit.
        @self.env.cr.postcommit.add
        def apply():
            self._apply_custom_provider_result(
                dbname, user_id, guest_id, context, request_uuid,
                {'kind': 'failure', 'code': 'request_failed'},
            )

    # Run the completion in a detached thread and apply its result.
    def _submit_custom_provider_request(self, params, connection, technical_name, vals):
        dbname = self.env.cr.dbname
        user_id = vals["request_user_id"]
        request_uuid = vals["request_uuid"]
        context = vals["request_context"]
        guest_id = vals["request_guest_id"]

        # Send the completion and resume or rescue the waiting session.
        def run_completion():
            # Step 1: collect the provider response or failure.
            try:
                message = openai_adapter.get_completion(connection, technical_name, params)
                completion_result = {'kind': 'success', 'message': message}
            except openai_adapter.UserErrorFromProvider as error:
                _logger.warning("Custom AI provider request %s failed: status=%s type=%s", request_uuid, error.status, error.error_type)
                completion_result = {'kind': 'failure', 'code': 'request_failed', 'custom_provider_error': str(error)}
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Custom AI provider request %s failed", request_uuid,
                )
                completion_result = {'kind': 'failure', 'code': 'request_failed'}
            # Step 2: resume the session or rescue a failed continuation.
            try:
                self._apply_custom_provider_result(
                    dbname, user_id, guest_id, context, request_uuid, completion_result,
                )
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Failed to process custom AI provider result %s", request_uuid,
                )
                self._rescue_custom_provider_session(dbname, request_uuid, completion_result)

        # Start only after the waiting session is visible to a separate cursor.
        @self.env.cr.postcommit.add
        def start_completion():
            threading.Thread(target=run_completion, daemon=True).start()

    # Finish a waiting session when continuation fails.
    def _rescue_custom_provider_session(self, dbname, request_uuid, completion_result):
        # Step 1: find the waiting request in a fresh transaction.
        try:
            with Registry(dbname).cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {'cron_id': True})
                session = env['ai.session'].sudo().search([
                    ('request_uuid', '=', request_uuid),
                    ('loop_state', '=', 'waiting_model'),
                ], limit=1)
                if session:
                    # Step 2: close the exchange without using the original cursor.
                    content = (
                        completion_result['message']['content'][0].get('text', '')
                        if completion_result.get('kind') == 'success' else ''
                    )
                    session._finish_exchange(
                        'failed',
                        content=env._("The AI could not complete the request.") if not content else content,
                    )
        except Exception:  # noqa: BLE001
            _logger.exception("Failed to rescue custom AI provider session %s", request_uuid)

    # Resume the session through the matching callback.
    def _apply_custom_provider_result(
        self, dbname, user_id, guest_id, context, request_uuid, completion_result,
    ):
        # Step 1: restore the user and guest context for the completed request.
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, user_id, dict(context))
            if guest_id:
                env = env(context={**dict(context), 'guest': env['mail.guest'].browse(guest_id)})
            session = env['ai.session'].sudo().search([
                ('request_uuid', '=', request_uuid),
                ('loop_state', '=', 'waiting_model'),
            ], limit=1)
            if not session:
                return
            # Step 2: restore the channel and run the saved callback.
            channel = env['discuss.channel'].search([
                ('id', '=', session.channel_id.id),
            ], limit=1) if session.channel_id else env['discuss.channel']
            if channel:
                env = env(context={**env.context, 'discuss_channel': channel})
            session = session.with_env(env).sudo()
            match session.state['callback_type']:
                case 'agent_loop':
                    session._continue_agent_loop(completion_result)
                case 'channel_name':
                    session._continue_channel_name(completion_result)

    # Show a safe provider error instead of the generic unreachable message.
    def _continue_agent_loop(self, completion_result):
        if completion_result.get('custom_provider_error'):
            self.ensure_one()
            self._finish_exchange('failed', content=completion_result['custom_provider_error'])
            return
        return super()._continue_agent_loop(completion_result)
