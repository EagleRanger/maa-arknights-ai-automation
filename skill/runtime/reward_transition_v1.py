"""Bounded reward reveal transitions, shared by theme-specific reward services."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import re


def outfit_layer(items, text):
    compact = re.sub(r'\s+', '', str(text)).upper()
    if any(word in compact for word in ('购买', '至纯源石', '时装商店', '服饰商店')):
        return None
    brand = any(word in compact for word in ('CORALCOAST', 'VITAFIELD', 'MARTHE'))
    reveal = 'FLOT' in compact or 'BRANDNEWOUTFIT' in compact
    if not (brand and reveal):
        return None
    skip = next(((int(x), int(y)) for label,x,y in items
        if re.sub(r'\s+','',str(label)).upper() in ('SKIP','SKIP>','跳过')
        and 1550 <= x < 1920 and 0 <= y <= 170), None)
    if skip or 'BRANDNEWOUTFIT' in compact:
        return dict(kind='outfit_reveal', position=skip or (1830,55))
    if '穿戴' in compact:
        return dict(kind='outfit_ready', position=None)
    return None


def advance(app, observe, first, *, limit=3):
    """Only confirmed free reward reveals; every input consumes a fresh frame."""
    current, actions = first, []
    for index in range(limit):
        path, items, text = current
        layer = outfit_layer(items,text)
        if layer is None:
            return current, dict(ok=True, actions=actions)
        if app._maa_task_queue_running() is not False:
            return current, dict(ok=False,reason='reward_queue_not_idle',actions=actions)
        from PIL import Image
        with Image.open(path) as image:
            if image.size != (1920,1080):
                return current, dict(ok=False,reason='reward_frame_size_unverified',actions=actions)
        position = layer['position'] or app.POS_DISMISS
        app.tap(*position)
        actions.append(dict(kind=layer['kind'],position=position,before=str(path)))
        app.wait(2)
        current = observe(index)
    return current, dict(ok=outfit_layer(current[1],current[2]) is None,
        reason='reward_transition_budget',actions=actions)


@contextmanager
def boundary(sami, app):
    original = sami.page
    def page(tag):
        first = original(tag)
        # A reveal is handled only inside the owner's reward transition chain.
        # Ordinary shops, battles, recruitment and manual pages remain untouched.
        if not str(tag).startswith(('sami_records_claim_','sami_records_before_back',
                                    'sami_records_home_after')):
            return first
        result, receipt = advance(app,lambda n:original(str(tag)+'_reveal_'+str(n)),first)
        if receipt['actions']:
            app._RUN_SUMMARY.setdefault('reward_transitions',[]).append(receipt)
        return result
    with patch.object(sami,'page',page):
        yield
