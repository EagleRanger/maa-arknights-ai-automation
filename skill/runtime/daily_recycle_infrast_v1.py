"""Enable the native recycling shift in the generated 333 MAA plan."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch


def plan(payload):
    result=deepcopy(payload)
    for row in result.get('plans',[]):
        rooms=row.setdefault('rooms',{})
        # Preserve real custom assignments; replace only missing/disabled drafts
        # under the user's explicit request to enable this facility.
        if not rooms.get('recycle'):
            rooms['recycle']=[{'autofill':True}]
    return result


def config(payload):
    result=deepcopy(payload)
    groups=(result.get('Configurations') or {}).values()
    for group in groups:
        for task in group.get('TaskQueue',[]):
            if task.get('TaskType')!='Infrast':continue
            facilities=task.setdefault('RoomList',[])
            if not any(row.get('Room')=='Recycle' for row in facilities):
                facilities.append({'Room':'Recycle'})
    return result


def apply(original,app,decision):
    if app._maa_task_queue_running() is not False:
        return False
    import daily_base_333_verified_execution_v1 as base
    gui=(Path(app.MAA_CONFIG)/'gui.new.json').resolve()
    active=base.ACTIVE_CONFIG.resolve()
    writer=app._atomic_write_json
    builder=base.build_single_plan_config
    def write(path,value):
        target=Path(path).resolve()
        if target==gui:value=config(value)
        return writer(path,value)
    with patch.object(app,'_atomic_write_json',write), \
         patch.object(base,'build_single_plan_config',lambda source,index:plan(builder(source,index))):
        ok=original(app,decision)
    if ok:
        stored=app._read_json_file(str(gui),{})
        task=next(t for t in app._task_queue(stored) if t.get('TaskType')=='Infrast')
        payload=app._read_json_file(str(active),{})
        enabled=any(r.get('Room')=='Recycle' for r in task.get('RoomList',[]))
        intent=bool((payload.get('plans') or [{}])[0].get('rooms',{}).get('recycle'))
        app._RUN_SUMMARY.setdefault('base_333',{})['recycle']=dict(
            configured=enabled and intent,facility_enabled=enabled,
            shift_intent_present=intent,mode='maa_native_autofill',
            actual_staffing_verified=False,reason='await_same_queue_evidence_or_game_readback')
        if not enabled or not intent:return False
        app.log('[基建排班] 回收站已纳入原生进驻/轮班；执行结果另验，不把收取产物当进驻成功')
    return ok


def receipt_from_window(receipt,text):
    import daily_base_333_verified_execution_v1 as base
    window=base._last_infrast_window(text)
    confirmed=any((e.get('details') or {}).get('facility')=='Recycle'
                  for _,e in base._callbacks(window,'InfrastConfirmButton'))
    shortage=any((e.get('details') or {}).get('facility')=='Recycle'
                 for _,e in base._callbacks(window,'NotEnoughStaff'))
    ok=bool(confirmed and not shortage and receipt.get('task_chain_completed'))
    result=dict(receipt,recycle=dict(actual_staffing_verified=ok,confirm_callback=confirmed,
        shortage=shortage,reason='same_queue_confirmed' if ok else 'staffing_not_verified'))
    if not ok:result.update(status='execution_unverified',recycle_pending=True,
                            reason='recycle_staffing_not_verified')
    return result


@contextmanager
def boundary():
    import daily_base_333_verified_execution_v1 as base
    import daily_base_333_verified_execution_v5 as final
    import daily_base_333_verified_execution_v4 as collector
    original=base.apply_single_plan_config
    old_verify=final.verify_from_files
    def verify(paths,not_before,expected,config):
        captured={};read=collector.collect_infrast
        def collect(*args,**kwargs):
            value=read(*args,**kwargs);captured['text']=value[0];return value
        with patch.object(collector,'collect_infrast',collect), \
             patch.object(collector,'WANTED',collector.WANTED|{'NotEnoughStaff'}):
            result=old_verify(paths,not_before,expected,config)
        try:
            payload=json.loads(Path(config).read_text('utf-8'))
        except (OSError,ValueError):return result
        if not (payload.get('plans') or [{}])[0].get('rooms',{}).get('recycle'):
            return result
        return receipt_from_window(result,captured.get('text',''))
    with patch.object(base,'apply_single_plan_config',lambda app,d:apply(original,app,d)), \
         patch.object(final,'verify_from_files',verify):
        yield
