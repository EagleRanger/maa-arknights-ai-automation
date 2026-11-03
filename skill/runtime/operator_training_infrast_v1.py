"""Consume this daily Infrast's training observation before a separate check.

Already-busy rooms need no character-page detour. Completed/idle/uncertain
rooms still use the ordered native mastery service; no blanket continue flag.
"""
from contextlib import contextmanager
from datetime import datetime,timedelta
import json
from pathlib import Path
import re
from unittest.mock import patch
import operator_training_v1 as native
import operator_training_v2 as fallback

KEY='training_room_from_current_daily_infrast'

def current_time():return datetime.now().astimezone()


def observation(text,*,now=None):
    now=now or current_time()
    identity=None;complete=False;result=None
    for line in text.splitlines():
        marker='Assistant::append_callback | '
        if marker not in line:continue
        event,_,raw=line.split(marker,1)[1].partition(' ')
        try:row=json.loads(raw)
        except ValueError:continue
        if row.get('taskchain')!='Infrast':continue
        key=(row.get('uuid'),row.get('taskid'))
        if event=='TaskChainStart':identity=key;complete=False;result=None
        elif identity and key==identity:
            if event=='TaskChainCompleted':complete=True
            elif event in {'TaskChainError','TaskChainStopped'}:complete=False;result=None
            elif event=='SubTaskExtraInfo' and row.get('what') in {
                'InfrastTrainingTimeLeft','InfrastTrainingCompleted','InfrastTrainingIdle'}:
                result=dict(status=row['what'],details=row.get('details') or {},task_identity=list(identity))
                match=re.match(r'\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)\]',line)
                if match:result['observed_at']=datetime.fromisoformat(match[1]).astimezone().isoformat()
    if not complete or not identity or not identity[0] or result is None:
        return dict(status='unverified')
    result['infrast_chain_verified']=True
    detail=result['details']
    if result['status']=='InfrastTrainingTimeLeft':
        parts=[p.strip() for p in str(detail.get('time','')).strip().split(':')]
        if (len(parts)!=3 or any(not p.isdigit() for p in parts) or not result.get('observed_at')
                or not detail.get('operator') or not detail.get('skill') or detail.get('level') not in (1,2,3)):
            return dict(result,status='training_timer_unverified')
        duration=int(parts[0])*3600+int(parts[1])*60+int(parts[2])
        finish=datetime.fromisoformat(result['observed_at'])+timedelta(seconds=duration)
        result.update(status='processing' if finish>now else 'timer_elapsed_recheck',estimated_finish=finish.isoformat())
    return result


def service(app,**kwargs):
    root=Path(kwargs.get('root') or app.BASE);packet=kwargs.get('packet')
    if packet is None and (root/native.PLAN).exists():packet=json.loads((root/native.PLAN).read_text('utf-8'))
    room=app._RUN_SUMMARY.get(KEY) or {}
    finish=room.get('estimated_finish')
    active=(room.get('status')=='processing' and isinstance(finish,str)
            and datetime.fromisoformat(finish)>current_time())
    if packet and packet.get('enabled') is True and native.goals(packet) and active:
        # A room in use blocks any new trainee, even if it is not our priority
        # target. Preserve the user's occupant and do not claim a target grade.
        return dict(status='waiting_training',source='current_daily_infrast',
            training_room=room,targets=[dict(native.goals(packet)[0],status='training_room_busy',
                observed_completed_level=None,started_level=None)],
            extra_operator_navigation_skipped=True,configuration_changed=False)
    return fallback.service(app,**kwargs)


@contextmanager
def boundary(app):
    old_daily=app.mode_daily
    def daily(enabled_tasks=None):
        app._RUN_SUMMARY.pop(KEY,None)
        ok=old_daily(enabled_tasks=enabled_tasks)
        full=enabled_tasks is None or set(enabled_tasks)=={'StartUp','Infrast','Recruit','Mall','Award'}
        if ok is True and full:
            app._RUN_SUMMARY[KEY]=observation(app._get_current_maa_run_log())
        return ok
    with patch.object(app,'mode_daily',daily),patch.object(native,'service',service),native.boundary(app):yield
