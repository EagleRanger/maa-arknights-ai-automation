"""A completed sign-in may expose the next known overlay, not home yet."""
from contextlib import contextmanager
from unittest.mock import patch
import event_daily_reward_claim_v2 as previous

ORIGINAL=previous.day_card_handler


def day_card_handler(*args,**kwargs):
    result=ORIGINAL(*args,**kwargs)
    if not result or result.get('ok') or result.get('reason') not in {
        'claimed_and_closed','current_day_already_claimed','same_run_same_card_already_verified'}:
        return result
    evidence=result.get('evidence') or []
    if not evidence:return result
    items=kwargs['read_items'](evidence[-1])
    if previous.wall.is_wall(' '.join(str(t) for t,x,y in items)):
        # Local claim/close succeeded. Do not invent home or wall completion.
        return dict(result,ok=True,home_verified=False,pending_attention=False,
                    next_overlay='wish_wall',next_overlay_evidence=evidence[-1])
    return result


@contextmanager
def boundary():
    with patch.object(previous,'day_card_handler',day_card_handler):yield
