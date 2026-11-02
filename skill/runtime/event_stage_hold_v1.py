"""Apply explicit per-account upstream holds without replaying battle budgets.

Reuse the existing deferred-job branch: eligible activity farming/rewards keep
their real navigation and completion gates. This is not a stage-clear result.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json


def read_holds(root):
    path=Path(root)/'.project-reasoning/AUTOMATION_HANDOFF.json'
    packet=json.loads(path.read_text('utf-8-sig'))
    return (packet.get('daily_runtime') or {}).get('event_stage_holds') or []


@contextmanager
def boundary(app, holds):
    old_clear,old_record=app.clear_event_stage,app._record_deferred_event_job
    def match(event,stage,mode):
        return next((h for h in holds if h.get('status')=='awaiting_upstream_fix'
            and h.get('event_name')==event.get('name') and h.get('stage')==stage.get('display')
            and h.get('mode','normal')==mode),None)
    def clear(event,stage,mode='normal',*args,**kwargs):
        hold=match(event,stage,mode)
        if hold is None:
            return old_clear(event,stage,mode,*args,**kwargs)
        progress=(app._load_event_progress().get('events') or {}).get(event['name']) or {}
        previous=(progress.get('stages') or {}).get(stage['display'])
        run=app._RUN_SUMMARY.setdefault('event',{'name':event['name'],'stages':{}})
        if previous:
            run.setdefault('stages',{})[stage['display']]=deepcopy(previous)
            row=(run['stages'][stage['display']].get('modes') or {}).get(mode) or {}
            audited=hold.get('verified_failed_jobs') or []
            if (hold.get('review_reference') and row.get('status')=='failed' and audited
                    and set(audited)==set(row.get('attempted_jobs') or [])):
                row['verified_failed_jobs']=list(audited)
                row['failure_review_reference']=hold['review_reference']
        run.setdefault('upstream_holds',[]).append(deepcopy(hold))
        app.log(f"[上游待修] {stage['display']}：{hold.get('reason','等待官方修复')}；不新增战斗或重置次数")
        return 'no_job'  # Existing caller's compatible deferred-result protocol.
    def record(event,stage,mode):
        row=old_record(event,stage,mode)
        hold=match(event,stage,mode)
        if hold:
            row.update(reason=hold.get('reason','等待官方修复'),retry='after_verified_upstream_fix',
                       user_deferred=True)
            app._RUN_SUMMARY['event']['detail']=f"{stage['display']} 等待官方修复；仍未完成，已通过关卡不重放"
        return row
    with patch.object(app,'clear_event_stage',clear),patch.object(app,'_record_deferred_event_job',record):
        yield
