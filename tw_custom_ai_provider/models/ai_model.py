from odoo import api, fields, models, _
from odoo.exceptions import UserError

class AIModel(models.Model):
    _name = 'ai.model'
    _description = "AI Model (Custom Provider)"
    is_openrouter_default = fields.Boolean(copy=False, readonly=True)
    name = fields.Char(required=True, help="Display name shown to agents users.")
    technical_name = fields.Char(required=True, help="Model identifier sent to the provider API (e.g. 'gpt-4o-mini').")
    provider_id = fields.Many2one('ai.provider', required=True, ondelete='cascade')
    active = fields.Boolean(default=True)
    name_with_provider = fields.Char(compute='_compute_name_with_provider')
    is_api_ready = fields.Boolean(compute='_compute_is_api_ready')
    _unique_technical_name_per_provider = models.UniqueIndex(
        "(provider_id, technical_name) NULLS NOT DISTINCT",
        "A model with this name already exists for this provider.",
    )

    # Show the model name together with its provider.
    @api.depends('name', 'provider_id.name')
    def _compute_name_with_provider(self):
        for model in self:
            model.name_with_provider = f"{model.name} ({model.provider_id.name})" if model.provider_id else model.name

    # Check whether the model and provider can send requests.
    @api.depends('active', 'provider_id.api_key', 'provider_id.base_url', 'provider_id.active', 'provider_id.data_sharing_accepted')
    def _compute_is_api_ready(self):
        for model in self:
            provider = model.provider_id.sudo()
            model.is_api_ready = bool(model.active and provider.active and provider.api_key and provider.base_url and provider.data_sharing_accepted)

    # Prevent changes to the protected default model identity.
    def write(self, vals):
        for model in self.filtered('is_openrouter_default'):
            if any(key in vals and vals[key] != model[key] for key in ('technical_name', 'is_openrouter_default', 'active')):
                raise UserError(_("The OpenRouter default model cannot be archived or have its identity changed."))
            if 'provider_id' in vals and model.provider_id.id != vals['provider_id']:
                raise UserError(_("The OpenRouter default model provider cannot be changed."))
        return super().write(vals)

    # Keep the default model available while allowing module uninstall.
    @api.ondelete(at_uninstall=False)
    def _unlink_except_openrouter_default(self):
        if self.filtered('is_openrouter_default'):
            raise UserError(_("The OpenRouter default model cannot be deleted."))

    # Return the selected global model or report invalid configuration.
    @api.model
    def _get_global_model(self):
        parameters = self.env['ir.config_parameter'].sudo()
        if not parameters.get_bool('tw_custom_ai_provider.use_global_model'):
            return self.browse()
        model = self.sudo().browse(parameters.get_int('tw_custom_ai_provider.global_model_id')).exists()
        if not model or not model.active or not model.provider_id.active:
            raise UserError(_("Configure an active global AI model and provider in Settings."))
        if not model.provider_id.api_key or not model.provider_id.base_url:
            raise UserError(_("Configure the API key and URL for the global AI provider."))
        return model

    # Return no API identifier for the OpenRouter account default.
    def _get_api_model_name(self):
        self.ensure_one()
        return None if self.is_openrouter_default else self.technical_name

    # Resolve an explicit provider model for a specialized media task.
    @api.model
    def _get_media_model(self, task, required=False):
        parameters = self.env['ir.config_parameter'].sudo()
        model_id = parameters.get_int(f'tw_custom_ai_provider.{task}_model_id')
        if not model_id and not required and not parameters.get_bool('tw_custom_ai_provider.use_global_model'):
            return self.browse()
        model = self.sudo().browse(model_id).exists()
        if not model or not model.active or not model.provider_id.active:
            raise UserError(_("Select an active %(task)s model in Settings > AI.", task=task))
        if model.is_openrouter_default:
            raise UserError(_("Select an explicit model for %(task)s.", task=task))
        if not model.provider_id.api_key or not model.provider_id.base_url:
            raise UserError(_("Configure the API key and URL for the %(task)s provider.", task=task))
        return model
