from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    ai_use_global_model = fields.Boolean(string="Use a global model for agents", config_parameter='tw_custom_ai_provider.use_global_model')
    ai_global_model_id = fields.Many2one('ai.model', string="Global AI Model", config_parameter='tw_custom_ai_provider.global_model_id', domain="[('active', '=', True), ('provider_id.active', '=', True)]")
    ai_image_model_id = fields.Many2one('ai.model', string="Image Generation Model", config_parameter='tw_custom_ai_provider.image_model_id', domain="[('active', '=', True), ('provider_id.active', '=', True), ('is_openrouter_default', '=', False)]")
    ai_transcription_model_id = fields.Many2one('ai.model', string="Audio Transcription Model", config_parameter='tw_custom_ai_provider.transcription_model_id', domain="[('active', '=', True), ('provider_id.active', '=', True), ('is_openrouter_default', '=', False)]")

    # Reject account defaults and unsupported providers for media tasks.
    @api.constrains('ai_image_model_id', 'ai_transcription_model_id')
    def _check_media_models(self):
        for settings in self:
            for model in settings.ai_image_model_id | settings.ai_transcription_model_id:
                if model.is_openrouter_default:
                    raise ValidationError(_("Select an explicit model for images and transcription."))

    # Require a model when global routing is enabled.
    @api.constrains('ai_use_global_model', 'ai_global_model_id')
    def _check_global_model(self):
        for settings in self:
            if settings.ai_use_global_model and not settings.ai_global_model_id:
                raise ValidationError(_("Select a global AI model before enabling global routing."))
