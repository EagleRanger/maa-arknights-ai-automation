"""Wait for explicit in-game resource progress within the existing startup.

Package upgrades are classified separately and surfaced with channel identity;
the verified package-maintenance helper owns signature/version readback.
"""
from contextlib import contextmanager
from time import monotonic
from unittest.mock import patch
from daily_startup_rewards_v1 import boundary as BASE
from daily_login_visual_v1 import StartupUnverified
from game_update_judgement_v1 import judge


@contextmanager
def boundary(app,clock=monotonic):
    with BASE(app):
        old_ocr,old_ensure=app.ocr,app.ensure_env
        active=False
        def ocr(path):
            items=old_ocr(path)
            decision=judge(items) if active else {'kind':'not_update'}
            if decision['kind']=='not_update':return items
            receipt=app._RUN_SUMMARY.setdefault('game_update',{'observations':[]})
            receipt.update(decision)
            receipt['observations'].append(dict(screenshot=str(path),decision=decision))
            if decision['kind']=='resource_download_prompt':
                buttons=[(round(x),round(y)) for t,x,y in items
                    if ''.join(str(t).split()) in ('确认下载','开始下载','立即下载','确认','确定')
                    and 500<=x<=1500 and 500<=y<=950]
                if len(buttons)!=1 or app._maa_task_queue_running():
                    raise StartupUnverified('resource_download_confirmation_unlocated')
                app.tap(*buttons[0]);app.wait(3)
                path=str(app.shot('game_resource_download_confirmed'))
                items=old_ocr(path);decision=judge(items)
                receipt.update(confirmation_point=buttons[0],confirmation_after=path)
            if decision['kind']!='resource_update_progress':return items
            # Stay inside one OCR/state call while genuine progress is present:
            # the legacy unknown-startup clock never mistakes it for a hang.
            started=last_change=clock();last=decision.get('percent')
            while decision['kind']=='resource_update_progress':
                if clock()-started>=1800 or clock()-last_change>=180:
                    receipt['status']='stalled_needs_ai'
                    raise StartupUnverified('resource_update_stalled')
                app.wait(5)
                current=str(app.shot('game_resource_update_progress'))
                items=old_ocr(current);decision=judge(items)
                percent=decision.get('percent')
                if percent is not None and (last is None or percent>last):
                    last_change=clock();last=percent
                if len(receipt['observations'])<120:
                    receipt['observations'].append(dict(screenshot=current,decision=decision))
            receipt.update(status='resource_progress_page_left',after=current)
            return items
        def ensure(*a,**k):
            nonlocal active
            active=True
            try:return old_ensure(*a,**k)
            finally:active=False
        with patch.object(app,'ocr',ocr),patch.object(app,'ensure_env',ensure):yield
