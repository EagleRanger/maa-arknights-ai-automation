"""Keep an active, bounded validation window separate from daily production.

This reads the existing handoff authority, never creates a scheduler or lease.
An expired/closed observation does not block the next scheduled daily run.
"""
from datetime import datetime


def require_daily_scope(handoff, at=None):
    context = handoff.get('current_validation') or {}
    if context.get('status') != 'active':
        return {'status': 'daily_scope_available', 'game_actions': 0}
    now = at or datetime.now().astimezone()
    try:
        start = datetime.fromisoformat(context['not_before'])
        end = datetime.fromisoformat(context['deadline'])
        if any(x.tzinfo is None for x in (now, start, end)) or end <= start:
            raise ValueError('invalid validation window')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('ACTIVE_VALIDATION_WINDOW_INVALID') from exc
    if start <= now < end:
        raise ValueError('DAILY_NOT_IN_CURRENT_VALIDATION_SCOPE:' + str(context.get('handoff')))
    return {'status': 'validation_window_not_active', 'game_actions': 0}
