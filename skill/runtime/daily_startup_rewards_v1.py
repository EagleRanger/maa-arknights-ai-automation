"""Drain an explicit free login-ticket overlay before home/sign-in routing."""
from contextlib import contextmanager
from unittest.mock import patch
from daily_client_update_gate_v1 import boundary as BASE
from daily_login_visual_v1 import StartupUnverified
from event_celebration_login_v1 import ticket_point


@contextmanager
def boundary(app):
    with BASE(app):
        old_ocr,old_state,old_ensure=app.ocr,app.get_state,app.ensure_env
        active=False;latest={};attempted=False
        def ocr(path):
            items=old_ocr(path)
            if active:latest.update(path=str(path),items=items)
            return items
        def state():
            nonlocal attempted
            value=old_state()
            point=ticket_point(latest.get('items',[])) if active else None
            if point is None:return value
            if attempted or app._maa_task_queue_running():
                raise StartupUnverified('free_login_ticket_not_idle_or_repeated')
            attempted=True
            receipt=dict(status='observed',before=latest['path'],point=point,claimed_count=0)
            app._RUN_SUMMARY['free_login_ticket']=receipt
            app.tap(*point);app.wait(3)
            p=str(app.shot('free_login_ticket_reward'));items=ocr(p)
            text=''.join(str(t) for t,x,y in items)
            receipt['reward']=p
            if '获得物资' not in text or '寻访' not in text:
                raise StartupUnverified('free_login_ticket_reward_unverified')
            receipt.update(status='reward_verified',claimed_count=1)
            app.tap(960,960);app.wait(2)
            result=old_state()
            receipt['after']=latest.get('path')
            if ticket_point(latest.get('items',[])) is not None:
                raise StartupUnverified('free_login_ticket_overlay_not_drained')
            receipt['status']='claimed_overlay_drained'
            return result
        def ensure(*a,**k):
            nonlocal active
            active=True
            try:return old_ensure(*a,**k)
            finally:active=False
        with patch.object(app,'ocr',ocr),patch.object(app,'get_state',state), \
             patch.object(app,'ensure_env',ensure):yield
