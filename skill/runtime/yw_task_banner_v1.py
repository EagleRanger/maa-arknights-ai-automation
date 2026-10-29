"""Observed YW claim-all banner OCR, shared by daily and standalone modules."""
from contextlib import contextmanager
from functools import wraps
from unittest.mock import patch


def task_page(items):
    names={str(t).strip() for t,x,y in items}
    return ('打捞方案' in names and any(str(t).startswith('通关') for t,x,y in items)
            and any('YW-' in str(t) for t,x,y in items))


def pending(items):
    return task_page(items) and any('已完成待领取的任务' in str(t) for t,x,y in items)


def claim_all_point(items):
    if not pending(items): return None
    points=[(x,y) for t,x,y in items if ''.join(str(t).split()) in ('一键领取','键领取')
            and 1500<=x<=1850 and 180<=y<=340]
    return points[0] if len(points)==1 else None


def normalize(items):
    point=claim_all_point(items)
    return [(('一键领取' if (x,y)==point and str(t).strip()=='键领取' else t),x,y)
            for t,x,y in items]


@contextmanager
def boundary(app):
    original=app.claim_event_task_rewards
    @wraps(original)
    def claim(event):
        if (event or {}).get('stage_prefix')!='YW': return original(event)
        old_ocr=app.ocr
        with patch.object(app,'ocr',lambda path:normalize(old_ocr(path))):
            # Existing reward evidence and no-claim semantics are preserved.
            # A click/boolean return is not re-labelled whole-event completion.
            return original(event)
    claim._yw_banner_adapter=True
    with patch.object(app,'claim_event_task_rewards',claim): yield
