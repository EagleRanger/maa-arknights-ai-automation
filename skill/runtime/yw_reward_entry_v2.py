"""YW mission metadata belongs to the reward boundary, not one discovery path."""
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from unittest.mock import patch


def reward_event(event):
    if not event or event.get('stage_prefix') != 'YW' or event.get('name') != '昨日海':
        return event
    result = deepcopy(event)
    # Exact label proved on the live YW lobby. Navigation still locates its
    # current OCR coordinates; this does not claim rewards or invent a click.
    result['task_keywords'] = ['打捞方案']
    return result


@contextmanager
def boundary(app):
    original = app.claim_event_task_rewards
    @wraps(original)
    def claim(event):
        return original(reward_event(event))
    claim._yw_entry_metadata_v2 = True
    with patch.object(app, 'claim_event_task_rewards', claim):
        yield


def run_composed(operation, app):
    import run_daily as base
    original = base.main
    def main(*args, **kwargs):
        with boundary(app):
            return original(*args, **kwargs)
    with patch.object(base, 'main', main):
        return operation()
