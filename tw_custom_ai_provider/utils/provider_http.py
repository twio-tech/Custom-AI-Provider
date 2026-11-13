from odoo.tools.translate import LazyTranslate
import logging
import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from odoo.exceptions import UserError

_lt = LazyTranslate(__name__)

_logger = logging.getLogger(__name__)
MAX_RETRIES = 2
MAX_RETRY_WAIT = 10
ERROR_MESSAGES = {
    400: _lt("The AI provider rejected the request. Check the model and supported parameters."),
    401: _lt("The AI API key is invalid or disabled. Check the provider credentials."),
    402: _lt("The AI account has insufficient credits or has reached a spending limit."),
    403: _lt("The AI request was blocked by permissions, a budget limit or content policy."),
    404: _lt("The AI model or endpoint was not found. Check the model identifier."),
    408: _lt("The AI provider timed out. Try again later."),
    413: _lt("The AI input is too large. Use a smaller file."),
    422: _lt("The AI provider rejected the model parameters. Check its capabilities."),
    429: _lt("The AI provider rate limit was reached. Try again later."),
    500: _lt("The AI provider encountered an internal error. Try again later."),
    502: _lt("The AI model returned an invalid response or is unavailable. Try again later."),
    503: _lt("No AI provider is currently available for this model. Try again later."),
}

class UserErrorFromProvider(UserError):

    # Store safe error details for the UI and transcription queue.
    def __init__(self, message, status=0, error_type='', retry_after=0, retryable=False):
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.retry_after = retry_after
        self.retryable = retryable

# Parse either Retry-After seconds or a standard HTTP date.
def _retry_after(response):
    value = response.headers.get('Retry-After')
    if not value:
        return 0
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0
    return max(0, math.ceil(seconds)) if math.isfinite(seconds) else 0

# Detect HTTP errors and errors embedded in otherwise successful JSON responses.
def _response_error(response, payload):
    # Step 1: extract an error without exposing the provider response to users.
    error = payload.get('error') if isinstance(payload, dict) else None
    if 200 <= response.status_code < 300 and not error:
        return None
    error = error if isinstance(error, dict) else {}
    metadata = error.get('metadata') or {}
    metadata = metadata if isinstance(metadata, dict) else {}
    try:
        status = int(error.get('code') or response.status_code)
    except (ValueError, TypeError):
        status = response.status_code
    # Step 2: classify retryable failures and build a safe message.
    delay = _retry_after(response)
    budget_wait = status == 402 and metadata.get('limit_source') == 'openrouter_in_flight_budget' and delay > 0
    retryable = status in (408, 429, 500, 502, 503, 504) or budget_wait
    message = ERROR_MESSAGES.get(status, _lt("The AI provider could not complete the request."))
    if budget_wait:
        message = _lt("The AI account has reached its concurrent spending budget. Try again later.")
    if delay:
        message = _lt("%(message)s Retry after %(delay)s seconds.", message=message, delay=delay)
    return UserErrorFromProvider(message, status, str(metadata.get('error_type') or ''), delay, retryable)

# Send non-streaming JSON with bounded retries for explicit temporary rejections.
def post_json(connection, endpoint, body, timeout=300, files=None):
    # Step 1: send the request without logging credentials or media content.
    for attempt in range(MAX_RETRIES + 1):
        try:
            headers = {'Authorization': f"Bearer {connection['api_key']}"}
            if files:
                response = requests.post(f"{connection['base_url'].rstrip('/')}/{endpoint}", data=body, files=files, headers=headers, timeout=timeout)
            else:
                headers['Content-Type'] = 'application/json'
                response = requests.post(f"{connection['base_url'].rstrip('/')}/{endpoint}", json=body, headers=headers, timeout=timeout)
        except requests.Timeout as error:
            raise UserErrorFromProvider(_lt("The AI request timed out. Its result is unknown; check provider activity before trying again."), status=408, error_type='timeout', retryable=True) from error
        except requests.RequestException as error:
            raise UserErrorFromProvider(_lt("Could not connect to the AI provider. Check its URL and availability."), error_type='connection', retryable=True) from error
        try:
            payload = response.json()
        except ValueError:
            payload = None
        failure = _response_error(response, payload)
        if not failure:
            if not isinstance(payload, dict):
                raise UserErrorFromProvider(_lt("The AI provider returned an invalid JSON response."), error_type='invalid_response')
            return payload
        # Step 2: honor Retry-After without retrying permanent or ambiguous failures.
        delay = failure.retry_after or 2 ** attempt
        retry_status = failure.status in (429, 503) or (failure.status == 402 and failure.retryable)
        if retry_status and attempt < MAX_RETRIES and delay <= MAX_RETRY_WAIT:
            _logger.info("AI provider temporary rejection: status=%s retry=%s delay=%s", failure.status, attempt + 1, delay)
            time.sleep(delay)
            continue
        _logger.warning("AI provider request failed: status=%s type=%s", failure.status, failure.error_type)
        raise failure
