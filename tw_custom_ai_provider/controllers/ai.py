import base64
import binascii
import logging
from werkzeug.exceptions import BadRequest

from odoo import http
from odoo.http import request
from odoo.addons.ai.controllers.ai import AIController
from ..utils import media_adapter

_logger = logging.getLogger(__name__)

class CustomAIController(AIController):

    # Send chat microphone recordings to the configured transcription provider.
    @http.route()
    def transcribe(self, audio_base64):
        # Step 1: preserve standard routing and validate the recording size and format.
        parameters = request.env['ir.config_parameter'].sudo()
        if not parameters.get_int('tw_custom_ai_provider.transcription_model_id') and not parameters.get_bool('tw_custom_ai_provider.use_global_model'):
            return super().transcribe(audio_base64)
        if not audio_base64 or len(audio_base64) > 35 * 1024 * 1024:
            raise BadRequest("Audio is empty or exceeds the transcription size limit")
        try:
            data = base64.b64decode(audio_base64, validate=True)
        except (ValueError, TypeError, binascii.Error) as error:
            raise BadRequest("Invalid base64 audio") from error
        if len(data) > 25 * 1024 * 1024:
            raise BadRequest("Audio exceeds the transcription size limit")
        # Step 2: transcribe the recording through the configured provider.
        model = request.env['ai.model']._get_media_model('transcription', required=True)
        _logger.info("Chat voice transcription: model=%s input_bytes=%s", model.technical_name, len(data))
        try:
            text = media_adapter.transcribe_voice(model.provider_id._get_api_connection_vals(), model.technical_name, data)
        except media_adapter.UserErrorFromProvider as error:
            _logger.warning("Chat voice transcription failed: type=%s status=%s", error.error_type, error.status)
            raise
        _logger.info("Chat voice transcription completed: output_characters=%s", len(text))
        return {'status': 'success', 'text': text}
