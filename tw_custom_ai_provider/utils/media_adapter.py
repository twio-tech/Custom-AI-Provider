from odoo.tools.translate import LazyTranslate
import base64
import math
from .provider_http import UserErrorFromProvider, post_json

_lt = LazyTranslate(__name__)

# Generate images as inline Odoo media parts.
def generate_images(connection, model, messages, instructions='', aspect_ratio=None):
    # Step 1: collect the prompt and reference images.
    prompts = [instructions] if instructions else []
    references = []
    for message in messages:
        for part in message.get('content') or []:
            if part['type'] == 'text':
                prompts.append(part.get('text') or '')
            elif part['type'] == 'inline_data' and part.get('mimetype', '').startswith('image/'):
                data = part['data'].decode() if isinstance(part['data'], bytes) else part['data']
                references.append({'type': 'image_url', 'image_url': {'url': f"data:{part['mimetype']};base64,{data}"}})
    body = {'model': model, 'prompt': '\n\n'.join(prompts), 'n': 1}
    openrouter = connection.get('provider_type', 'openrouter') == 'openrouter'
    if openrouter and not model:
        from .openai_adapter import _convert_messages
        body = {'messages': _convert_messages(messages, instructions), 'modalities': ['image', 'text']}
        if aspect_ratio:
            body['image_config'] = {'aspect_ratio': aspect_ratio}
        response = post_json(connection, 'chat/completions', body)
        images = ((response.get('choices') or [{}])[0].get('message') or {}).get('images') or []
        converted = []
        for image in images:
            url = (image.get('image_url') or {}).get('url', '')
            if not url.startswith('data:image/') or ';base64,' not in url:
                raise UserErrorFromProvider(_lt("The conversation model returned unsupported image data. Configure an image generation model."))
            header, data = url.split(';base64,', 1)
            converted.append({'b64_json': data, 'media_type': header[5:]})
        payload = {'data': converted, 'usage': response.get('usage')}
    elif openrouter:
        if references:
            body['input_references'] = references
        if aspect_ratio:
            body['aspect_ratio'] = aspect_ratio
        payload = post_json(connection, 'images', body)
    else:
        body['size'] = '1536x1024' if aspect_ratio in ('16:9', '4:3', '3:2') else '1024x1536' if aspect_ratio in ('9:16', '3:4', '2:3') else '1024x1024'
        if references:
            files = [('image[]', (f'reference-{index}.png', base64.b64decode(reference['image_url']['url'].split(',', 1)[1]), reference['image_url']['url'].split(';', 1)[0][5:])) for index, reference in enumerate(references)]
            payload = post_json(connection, 'images/edits', body, files=files)
        else:
            payload = post_json(connection, 'images/generations', body)
    # Step 2: validate generated images before creating Odoo attachments.
    content = []
    for image in payload.get('data') or []:
        try:
            data = image['b64_json']
            raw = base64.b64decode(data, validate=True)
            mimetype = image.get('media_type') or ('image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg' if raw.startswith(b'\xff\xd8') else None)
            if not raw or not mimetype or not mimetype.startswith('image/'):
                raise ValueError('Invalid image')
        except (KeyError, TypeError, ValueError) as error:
            raise UserErrorFromProvider(_lt("The image provider returned invalid image data.")) from error
        content.append({'type': 'inline_data', 'mimetype': mimetype, 'data': data})
    if not content:
        raise UserErrorFromProvider(_lt("The image provider returned no images."))
    return {'role': 'assistant', 'content': content, 'provider_metadata': {'custom_model': model, 'usage': payload.get('usage')}}

# Format seconds as a WebVTT timestamp.
def _vtt_time(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"

# Convert real segment timestamps to VTT without inventing timing information.
def transcript_to_vtt(payload):
    # Step 1: require real timestamps from the transcription model.
    segments = payload.get('segments')
    if not isinstance(segments, list):
        raise UserErrorFromProvider(_lt("Select a transcription model supporting verbose JSON with segment timestamps."))
    # Step 2: format each timed segment as a VTT cue.
    cues = ['WEBVTT', '']
    for segment in segments:
        try:
            start, end = float(segment['start']), float(segment['end'])
            text = segment['text']
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or not isinstance(text, str):
                raise ValueError('Invalid segment')
        except (KeyError, TypeError, ValueError) as error:
            raise UserErrorFromProvider(_lt("The transcription provider returned invalid timestamps.")) from error
        if text.strip():
            cues.extend([f"{_vtt_time(start)} --> {_vtt_time(end)}", text.strip().replace('-->', '->'), ''])
    if len(cues) == 2 and payload.get('text', '').strip():
        raise UserErrorFromProvider(_lt("The transcription provider returned text without timestamps."))
    return '\n'.join(cues) + '\n'

# Transcribe audio through the dedicated OpenRouter endpoint.
def transcribe_audio(connection, model, data, mimetype):
    formats = {'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/mpeg': 'mp3', 'audio/mp3': 'mp3', 'audio/mp4': 'm4a', 'audio/x-m4a': 'm4a', 'audio/ogg': 'ogg', 'audio/webm': 'webm', 'video/webm': 'webm', 'audio/flac': 'flac', 'audio/aac': 'aac'}
    audio_format = formats.get((mimetype or '').split(';')[0])
    if not audio_format:
        raise UserErrorFromProvider(_lt("Unsupported recording format for transcription."))
    body = {'model': model, 'input_audio': {'data': base64.b64encode(bytes(data)).decode(), 'format': audio_format}, 'response_format': 'verbose_json', 'timestamp_granularities': ['segment']}
    if connection.get('provider_type', 'openrouter') != 'openrouter':
        body = {'model': model, 'response_format': 'verbose_json', 'timestamp_granularities[]': 'segment'}
        files = {'file': (f'recording.{audio_format}', data, mimetype)}
        return transcript_to_vtt(post_json(connection, 'audio/transcriptions', body, timeout=60, files=files))
    return transcript_to_vtt(post_json(connection, 'audio/transcriptions', body, timeout=60))

# Transcribe a voice message to plain text without requiring segment timestamps.
def transcribe_voice(connection, model, data):
    body = {'model': model, 'response_format': 'json'}
    if connection.get('provider_type') == 'openrouter':
        body['input_audio'] = {'data': base64.b64encode(bytes(data)).decode(), 'format': 'mp3'}
        payload = post_json(connection, 'audio/transcriptions', body, timeout=60)
    else:
        payload = post_json(connection, 'audio/transcriptions', body, timeout=60, files={'file': ('recording.mp3', bytes(data), 'audio/mpeg')})
    if not isinstance(payload.get('text'), str):
        raise UserErrorFromProvider(_lt("The transcription provider returned no text."))
    if not payload['text'].strip():
        raise UserErrorFromProvider(_lt("No speech was detected. Check your selected microphone, speak for a few seconds, and try again."), error_type='empty_transcription')
    return payload['text'].strip()
