"""Classifies Claude Code CLI stream-json output into the failures that should send work to Copilot.

Only budget/usage limits and authentication problems count: they will not go away by retrying the
same call, so main-kibana-agent routes to Copilot and remembers the outage until `resets_at`.
"""

import time

OK = 'ok'
BUDGET = 'budget'
AUTH = 'auth'
OTHER = 'other'

# Without a reset time from Claude, retry auth after an hour and short rate limits after 15 minutes.
AUTH_RETRY_SECONDS = 3600
RATE_LIMIT_RETRY_SECONDS = 900

_BUDGET_ERRORS = {'usage_limit_reached', 'rate_limit', 'rate_limit_error', 'billing_error', 'overloaded_budget'}
_AUTH_ERRORS = {'authentication_failed', 'authentication_error', 'permission_error', 'invalid_api_key', 'oauth_token_expired'}
_AUTH_TEXT = (
    'not logged in',
    'please run /login',
    'failed to authenticate',
    'invalid api key',
    'oauth token has expired',
    'oauth access token',
    'credit balance is too low',
)
_BUDGET_TEXT = (
    'spend limit',
    'usage limit',
    'hit your limit',
    'rate limit',
)


class ClaudeUnavailable(RuntimeError):
    """Claude cannot do the job right now (budget or auth); the workflow falls back to Copilot."""

    def __init__(self, reason, message, resets_at=None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.resets_at = resets_at

    def to_output(self):
        return {
            'claude_unavailable': True,
            'reason': self.reason,
            'message': self.message,
            'resets_at': self.resets_at,
            'until_epoch': retry_after_epoch(self.reason, self.resets_at),
        }


def retry_after_epoch(reason, resets_at=None, now=None):
    now = int(time.time() if now is None else now)
    if isinstance(resets_at, (int, float)) and resets_at > now:
        return int(resets_at)
    return now + (AUTH_RETRY_SECONDS if reason == AUTH else RATE_LIMIT_RETRY_SECONDS)


def _text_of_assistant(event):
    message = event.get('message') or {}
    return ' '.join(
        block.get('text', '') for block in message.get('content') or [] if isinstance(block, dict)
    )


def classify_event(event):
    """Returns (reason, message, resets_at) for an event that signals budget/auth trouble, else None."""
    if not isinstance(event, dict):
        return None
    kind = event.get('type')

    if kind == 'rate_limit_event':
        info = event.get('rate_limit_info') or {}
        if info.get('status') == 'rejected':
            resets_at = info.get('overageResetsAt') or info.get('resetsAt')
            return BUDGET, 'Claude rate limit rejected (' + str(info.get('rateLimitType', 'unknown')) + ')', resets_at
        return None

    if kind == 'system' and event.get('subtype') == 'api_retry':
        # The CLI retries a bad token ~10 times with backoff; a 401 never recovers, so stop early.
        if event.get('error_status') in (401, 403) or event.get('error') in _AUTH_ERRORS:
            return AUTH, 'Claude authentication failed (HTTP ' + str(event.get('error_status')) + ')', None
        return None

    if kind not in ('assistant', 'result'):
        return None

    status = event.get('api_error_status')
    error = event.get('api_error') or event.get('error') or ''
    text = event.get('result') if kind == 'result' else _text_of_assistant(event)
    text = text if isinstance(text, str) else ''
    is_error = kind == 'assistant' and event.get('is_api_error_message') or kind == 'result' and event.get('is_error')
    if not is_error and not status and not error:
        return None

    resets_at = None
    params = event.get('api_error_params') or {}
    info = params.get('rate_limit_info') if isinstance(params, dict) else None
    if isinstance(info, dict):
        resets_at = info.get('overageResetsAt') or info.get('resetsAt')

    lowered = text.lower()
    if status in (401, 403) or error in _AUTH_ERRORS or any(marker in lowered for marker in _AUTH_TEXT):
        return AUTH, text or 'Claude authentication failed', None
    if status == 429 or error in _BUDGET_ERRORS or any(marker in lowered for marker in _BUDGET_TEXT):
        return BUDGET, text or 'Claude usage limit reached', resets_at
    return None


def classify_plain_text(lines):
    """Fallback for non-JSON CLI output (startup errors print plain text)."""
    lowered = '\n'.join(lines).lower()
    if any(marker in lowered for marker in _AUTH_TEXT):
        return AUTH, '\n'.join(lines)[-500:], None
    if any(marker in lowered for marker in ('spend limit', 'usage limit')):
        return BUDGET, '\n'.join(lines)[-500:], None
    return None
