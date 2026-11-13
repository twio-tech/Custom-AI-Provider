from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..utils import openai_adapter

class AIProvider(models.Model):
    _name = 'ai.provider'
    _description = "AI Provider"
    name = fields.Char(required=True)
    technical_name = fields.Char(required=True, help="Public identifier of the provider implementation (e.g. 'openai').")
    base_url = fields.Char('Base URL', required=True, default='https://api.openai.com/v1', help='Root URL of an OpenAI-compatible API. Change it to point to an Azure gateway, LiteLLM proxy or any OpenAI-compatible backend.')
    api_key = fields.Char(groups='base.group_system', help='API key sent as Bearer token with every completion request.')
    active = fields.Boolean(default=True)
    connection_status = fields.Selection([('not_tested', 'Not tested'), ('success', 'Connected'), ('error', 'Failed')], default='not_tested', readonly=True, copy=False)

    # Clear the previous connection result when its configuration changes.
    def write(self, vals):
        if {'api_key', 'base_url', 'technical_name', 'active'} & vals.keys():
            vals = {**vals, 'connection_status': 'not_tested'}
        return super().write(vals)

    # Return the active provider connection or report missing configuration.
    def _get_api_connection_vals(self):
        # Step 1: validate the provider without exposing its key to ordinary users.
        self.ensure_one()
        provider = self.sudo()
        if not provider.active:
            raise ValueError(f"AI provider {provider.name}: provider is archived")
        if not provider.base_url:
            raise ValueError(f"AI provider {provider.name}: missing base_url")
        if not provider.api_key:
            raise ValueError(f"AI provider {provider.name}: missing api_key")
        # Step 2: return the credentials only to server-side callers.
        return {
            'base_url': provider.base_url.rstrip('/'),
            'provider_type': provider.technical_name,
            'api_key': provider.api_key,
        }

    # Check the provider connection and show its result.
    def action_test_connection(self):
        # Step 1: restrict connection checks to users who may configure the provider.
        self.ensure_one()
        self.check_access('write')
        notification = openai_adapter.test_connection(self._get_api_connection_vals())
        # Step 2: show a stable result in the form and detailed notification feedback.
        self.connection_status = 'success' if notification['ok'] else 'error'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if notification['ok'] else 'danger',
                'className': 'tw_ai_connection_result',
                'sticky': True,
                'message': self.env._(notification['message']),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # Prevent cascade deletion of the protected OpenRouter model.
    @api.ondelete(at_uninstall=False)
    def _unlink_except_openrouter_default(self):
        if self.env['ai.model'].sudo().with_context(active_test=False).search_count([('provider_id', 'in', self.ids), ('is_openrouter_default', '=', True)]):
            raise UserError(_("The provider of the OpenRouter default model cannot be deleted."))
