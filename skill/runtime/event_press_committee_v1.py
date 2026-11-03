"""Current-event utility using existing navigation and native MAA Custom.

No combat, farming substitution or permanent default-chain change. Partial
native resources and queue completion never stand for all newspaper rewards.
"""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import shutil
from unittest.mock import patch
from uuid import uuid4


def service(app):
    from event_tl_route_v1 import active,profile
    if not active():return dict(status='inactive_event',game_actions=0)
    if app._maa_task_queue_running() is not False:return dict(status='deferred_active_queue',game_actions=0)
    from maa_utility_custom_v1 import run
    out=Path(app.OUTPUT_DIR)/'press_committee'/uuid4().hex;out.mkdir(parents=True)
    event=profile('时间啊，向前！',app.MAA_ROOT)
    if not event or not app.goto_event_map(event):return dict(status='entry_navigation_unverified',evidence=str(out))
    path=app.shot('press_committee_entry');rows=app.ocr(path)
    choices=[(x,y) for t,x,y in rows if '新闻委员会' in str(t).replace(' ','')]
    if len(choices)!=1:
        shutil.copy2(path,out/'entry.png')
        return dict(status='needs_ai_entry_location',evidence=str(out/'entry.png'))
    app.tap(*choices[0]);app.wait(2)
    before=app.shot('press_committee_before');rows=app.ocr(before)
    shutil.copy2(before,out/'before.png')
    papers=('圣骏堡公报','今日评论','基尔萨宁乡土报','乌萨斯军锋报','求真报')
    current=[paper for paper in papers if any(paper in str(t) for t,x,y in rows)]
    result=dict(status='page_unverified',evidence=str(out),current_papers=current)
    if current:
        result['native']=run(app,'committee',out/'native',timeout=180)
        after=app.shot('press_committee_after');shutil.copy2(after,out/'after.png')
        result.update(status='native_returned_effect_needs_verification',after=str(out/'after.png'))
    result['home_return_verified']=app.goto_main_menu() is True
    (out/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


@contextmanager
def boundary(app):
    import daily_plain_popup_v3 as popup
    old=app.mode_daily;invoked=[False]
    old_effects=popup.effect_lines
    def daily(enabled_tasks=None):
        ok=old(enabled_tasks=enabled_tasks)
        full=enabled_tasks is None or set(enabled_tasks)=={'StartUp','Infrast','Recruit','Mall','Award'}
        if ok is True and full and not invoked[0]:
            invoked[0]=True
            try:row=service(app)
            except Exception as exc:row=dict(status='needs_attention',error=str(exc))
            app._RUN_SUMMARY['press_committee']=row
            if row.get('status') not in {'inactive_event','verified_complete'}:
                app._RUN_SUMMARY.setdefault('optional_activity_attention',[]).append(dict(
                    reason='press_committee_unverified',affected_scope='current_event_utility',
                    blocks_daily=False,evidence=row))
        return ok
    def effects(report):
        lines=old_effects(report);row=(report.get('run_summary') or {}).get('press_committee') or {}
        if row.get('status') not in {None,'inactive_event','verified_complete'}:
            lines.append('战时新闻委员会：尚未核实完成，需继续处理。')
        return lines
    with patch.object(app,'mode_daily',daily),patch.object(popup,'effect_lines',effects):yield
