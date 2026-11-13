from odoo import api, models

class AiTool(models.AbstractModel):
    _inherit = 'ai.tool'

    # Mark custom generated images so attachment creation decodes their API base64.
    @api.model
    def _generate_image_attachments(self, prompt, images_paths, image_title, aspect_ratio='1:1'):
        parameters = self.env['ir.config_parameter'].sudo()
        custom = parameters.get_int('tw_custom_ai_provider.image_model_id') or parameters.get_bool('tw_custom_ai_provider.use_global_model') or bool(self.env['ai.session']._get_custom_llm_model_from_options({}))
        tool = self.with_context(custom_ai_image_base64=True, image_no_postprocess=True) if custom else self
        return super(AiTool, tool)._generate_image_attachments(prompt, images_paths, image_title, aspect_ratio=aspect_ratio)

    # Pass the calling agent to image fallback resolution.
    @api.model
    def _ai_tool_generate_image(self, tool_context, prompt, images_paths, image_title, feedback, aspect_ratio='1:1'):
        tool = self.with_context(custom_ai_agent_id=tool_context.get('agent_id'))
        return super(AiTool, tool)._ai_tool_generate_image(tool_context, prompt, images_paths, image_title, feedback, aspect_ratio=aspect_ratio)
