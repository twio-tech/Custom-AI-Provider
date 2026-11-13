import base64
from odoo import models

class AiAttachmentVacuum(models.Model):
    _inherit = 'ai.attachment.vacuum'

    # Decode custom image API output before storing raw binary attachment data.
    def _create_attachments_and_mark_unused(self, attachment_vals):
        if self.env.context.get('custom_ai_image_base64'):
            attachment_vals = [{**vals, 'raw': base64.b64decode(vals['raw'])} if vals.get('raw') else vals for vals in attachment_vals]
        return super()._create_attachments_and_mark_unused(attachment_vals)
