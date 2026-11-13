import logging
from odoo import models
from odoo.exceptions import UserError
from odoo.addons.ai.models.mail_call_artifact import TRANSCRIPTION_MAX_FILE_SIZE
from ..utils import media_adapter

_logger = logging.getLogger(__name__)

class MailCallArtifact(models.Model):
    _inherit = 'mail.call.artifact'

    # Keep the Odoo lease and queue while replacing the transcription request.
    def _transcribe_claimed_record(self, lease_until):
        # Step 1: preserve the queue lease and validate recorded media.
        self.ensure_one()
        if not self._is_lease_valid(lease_until):
            return {'status': 'skip'}
        parameters = self.env['ir.config_parameter'].sudo()
        if not parameters.get_int('tw_custom_ai_provider.transcription_model_id') and not parameters.get_bool('tw_custom_ai_provider.use_global_model'):
            return super()._transcribe_claimed_record(lease_until)
        if self.media_id.file_size > TRANSCRIPTION_MAX_FILE_SIZE:
            return {'status': 'file_too_large'}
        if not self.media_id.raw:
            return {'status': 'no_media'}
        # Step 2: send the transcription without modifying database state.
        try:
            model = self.env['ai.model']._get_media_model('transcription', required=True)
            transcript = media_adapter.transcribe_audio(model.provider_id._get_api_connection_vals(), model.technical_name, self.media_id.raw, self.media_id.mimetype)
            return {'status': 'ok', 'transcript': transcript}
        except (UserError, ValueError) as error:
            _logger.warning("Custom transcription failed for artifact %s", self.id)
            return {'status': 'err', 'custom_provider_error': str(error), 'custom_provider_retryable': getattr(error, 'retryable', False)}

    # Save readable failures and stop retrying permanent errors.
    def _finalize_transcription(self, lease_until, result, max_retries=5):
        if result and result.get('custom_provider_error') and not result.get('custom_provider_retryable'):
            max_retries = 1
        finalized = super()._finalize_transcription(lease_until, result, max_retries=max_retries)
        if finalized and result.get('custom_provider_error'):
            self.sudo().transcription_error_msg = result['custom_provider_error']
        return finalized

    # Preserve failed custom recordings for a retry after configuration is fixed.
    def _after_transcription_error(self):
        parameters = self.env['ir.config_parameter'].sudo()
        if not parameters.get_int('tw_custom_ai_provider.transcription_model_id') and not parameters.get_bool('tw_custom_ai_provider.use_global_model'):
            return super()._after_transcription_error()
        for artifact in self:
            call = artifact._get_related_call()
            if call:
                call.sudo()._after_artifact_transcription_error(artifact)
