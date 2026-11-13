from odoo import api, fields, models

class AIAgent(models.Model):
    _inherit = 'ai.agent'
    use_global_model = fields.Boolean(compute='_compute_global_model')
    global_model_display_name = fields.Char(compute='_compute_global_model')
    custom_model_id = fields.Many2one('ai.model', string="Model", ondelete='set null', index='btree_not_null', domain="[('active', '=', True), ('provider_id.active', '=', True)]", help="Model from a custom provider used to run this agent. Leave it empty to use Odoo AI (In-App Purchase credits).")
    custom_model_display_name = fields.Char(related='custom_model_id.name_with_provider')
    is_custom_model_enabled = fields.Boolean(compute='_compute_is_custom_model_enabled')

    # Check whether the agent model is ready for API calls.
    @api.depends('custom_model_id.is_api_ready')
    def _compute_is_custom_model_enabled(self):
        for agent in self:
            agent.is_custom_model_enabled = bool(agent.custom_model_id.is_api_ready)

    # Show the database-wide routing choice without changing agent selections.
    def _compute_global_model(self):
        parameters = self.env['ir.config_parameter'].sudo()
        enabled = parameters.get_bool('tw_custom_ai_provider.use_global_model')
        model = self.env['ai.model'].sudo().browse(parameters.get_int('tw_custom_ai_provider.global_model_id')).exists()
        for agent in self:
            agent.use_global_model = enabled
            agent.global_model_display_name = model.name_with_provider if enabled and model else False
