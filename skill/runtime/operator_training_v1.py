"""Ordered, account-scoped mastery goals using MAA's native OperProgress.

No combat, scheduler, environment startup or cleanup. A successful native
training-start callback is deliberately NOT a completed mastery level.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
import shutil
from unittest.mock import patch
from uuid import uuid4

PLAN = Path('runtime_state/operator_training_plan.json')
ROLES = {'Unknown','Warrior','Pioneer','Medic','Tank','Sniper','Caster','Support','Special'}


def goals(packet):
    if packet.get('schema_version') != 1:
        raise ValueError('unsupported operator-training plan schema')
    result=[];seen=set()
    for row in packet.get('goals',[]):
        name=row.get('name');skill=row.get('skill');target=row.get('mastery')
        role=row.get('role','Unknown')
        if (not isinstance(name,str) or not name.strip() or type(skill) is not int
                or skill not in (1,2,3) or type(target) is not int or not 1<=target<=3
                or role not in ROLES or set(row)-{'name','role','skill','mastery'}):
            raise ValueError('explicit operator, skill 1..3 and mastery 1..3 required')
        key=(name,role,skill)
        if key in seen:raise ValueError('duplicate operator/skill goal')
        seen.add(key);result.append(dict(name=name,role=role,skill=skill,mastery=target))
    return result


def native_task(rows):
    plans=[]
    for row in rows:
        levels=[0,0,0];levels[row['skill']-1]=row['mastery']
        plans.append(dict(Name=row['name'],Role=row['role'],Elite=0,SkillLevel=0,
                          SkillMastery=levels,ShowRole=row['role']!='Unknown'))
    return {'$type':'OperProgressTask','TaskType':'OperProgress','Name':'指定干员技能专精',
            'IsEnable':True,'Plans':plans}


def queue_config(app,source,rows):
    result=deepcopy(source);queue=app._task_queue(result)
    if sum(r.get('TaskType')=='OperProgress' for r in queue)>1:
        raise ValueError('multiple OperProgress tasks; preserve user configuration for review')
    queue[:]=[r for r in queue if r.get('TaskType')!='OperProgress']+[native_task(rows)]
    app._set_enabled_tasks(result,{'OperProgress'})
    return result


def evaluate(rows,text):
    """Use current queue UUID/taskid; never borrow an earlier success token."""
    records=[];identity=None;complete=False;all_done=False
    for line in text.splitlines():
        if 'append_task OperProgress ' in line:
            records=[];identity=None;complete=False;all_done=False
        marker='Assistant::append_callback | '
        if marker not in line:continue
        event,_,raw=line.split(marker,1)[1].partition(' ')
        try:payload=json.loads(raw)
        except ValueError:continue
        if event=='AllTasksCompleted' and identity is not None:
            all_done=True;continue
        if payload.get('taskchain')!='OperProgress':continue
        key=(payload.get('uuid'),payload.get('taskid'))
        if event=='TaskChainStart':
            if key[0] and key[1] is not None:
                identity=key;records=[];complete=False;all_done=False
        elif identity is not None and key==identity:
            if event=='TaskChainCompleted':complete=True
            elif event in {'TaskChainError','TaskChainStopped'}:complete=False;all_done=False
            elif event=='SubTaskExtraInfo' and payload.get('what')=='OperProgressDetail':
                records.append(payload.get('details') or {})
    result=[]
    for row in rows:
        matches=[]
        for detail in records:
            if detail.get('name')!=row['name']:continue
            if row['role']!='Unknown' and detail.get('role')!=row['role']:continue
            levels=detail.get('skill_mastery')
            if isinstance(levels,list) and len(levels)==3:
                if any(v for i,v in enumerate(levels) if i!=row['skill']-1):continue
            elif detail.get('result_detail') not in {'TrainingRoomBusy','OperatorNotFound','RecognitionFailed','ResourceInsufficient','PrerequisiteNotMet','FormulaLocked','Interrupt'}:
                continue
            matches.append(detail)
        detail=matches[-1] if matches else {}
        reason=detail.get('result_detail');levels=detail.get('skill_mastery') or [0,0,0]
        actual=levels[row['skill']-1] if len(levels)==3 else None
        if reason=='AlreadySatisfied' and type(actual) is int and row['mastery']<=actual<=3:
            status='verified_complete'
        elif reason in {'Completed','PrerequisiteTraining'}:
            status='training_started'  # level here is the STARTED grade, not a finished grade.
        elif reason=='TrainingRoomBusy':status='training_room_busy'
        elif detail:status='needs_attention'
        else:status='not_started'
        result.append(dict(row,status=status,native_result=reason,
            observed_completed_level=actual if status=='verified_complete' else None,
            started_level=actual if status=='training_started' else None))
    verified=bool(identity and complete and all_done)
    if not verified:status='queue_unverified'
    elif result and all(r['status']=='verified_complete' for r in result):status='goals_complete'
    elif any(r['status']=='needs_attention' for r in result):status='needs_attention'
    elif any(r['status'] in {'training_started','training_room_busy'} for r in result):status='waiting_training'
    else:status='needs_attention'
    return dict(status=status,queue_verified=verified,targets=result,
                task_identity=list(identity) if identity else None)


def worker_command(path):
    # Reuse the accepted background-only UIA submitter in BOTH processes.
    code=('import sys;sys.path[:0]='+repr(sys.path)+';'
          'import maa_queue_process_v1 as q;q.ALLOWED=q.ALLOWED|{"OperProgress"};'
          'import maa_queue_process_v3 as w;w.worker('+repr(str(path))+')')
    return [getattr(sys,'_base_executable',sys.executable),'-X','utf8','-c',code]


@contextmanager
def native_queue():
    import maa_queue_process_v1 as queue
    import maa_queue_process_v2 as command_owner
    with patch.object(queue,'ALLOWED',queue.ALLOWED|{'OperProgress'}), \
         patch.object(command_owner,'worker_command',worker_command):
        yield


@contextmanager
def parent_receipts(app):
    # This auxiliary queue must not replace the already accepted daily/fight log.
    keys=[k for k in vars(app) if k.startswith('_LAST_MAA_') or k=='_base333_active_maa_scope']
    saved={k:deepcopy(getattr(app,k)) for k in keys}
    try:yield
    finally:
        for key,value in saved.items():setattr(app,key,value)


def _service_one(app,*,root=None,packet=None,observer=None):
    from account_progress_v1 import AccountProgress
    from sami_account_progress_v1 import observe_account
    from ark_modules.core import ReceiptStore
    root=Path(root or app.BASE)
    plan_path=root/PLAN
    if packet is None:
        if not plan_path.exists():return dict(status='not_configured',game_actions=0)
        packet=json.loads(plan_path.read_text('utf-8'))
    rows=goals(packet)
    if packet.get('enabled') is not True or not rows:
        return dict(status='disabled_or_empty',game_actions=0)
    if app._maa_task_queue_running() is not False:
        return dict(status='deferred_active_queue',game_actions=0)
    if app.goto_main_menu() is not True:
        return dict(status='home_unverified',game_actions=0)
    identity,identity_evidence=(observer or observe_account)(app)
    if not identity or (packet.get('account') and packet['account']!=identity):
        return dict(status='account_unverified_or_mismatch',game_actions=0)
    if packet.get('account') is None:
        packet=dict(packet,account=identity)
        app._atomic_write_json(str(plan_path),packet)
    store=AccountProgress(root/'runtime_state/accounts',identity)
    pending=[];cached=[]
    for row in rows:
        decision=store.decision(theme='Operators',capability=f"{row['name']}:skill{row['skill']}",revision='mastery-v1')
        fact=decision.get('fact') or {}
        # Mastery never regresses. A verified M1/M2 fact covers a lower goal,
        # but must not suppress a later request to train this skill further.
        valid=(decision['action']=='skip_permanent_complete' or
               decision.get('reason')=='verified_partial_requires_current_inspection')
        if valid and fact.get('total')==3 and fact.get('progress',0)>=row['mastery']:
            cached.append(dict(row,status='verified_complete',source='account_fact'))
        else:pending.append(row)
    if not pending:return dict(status='goals_complete',targets=cached,cached=True,game_actions=0)
    out=Path(app.OUTPUT_DIR)/'operator_training'/uuid4().hex
    out.mkdir(parents=True)
    path=str(Path(app.MAA_CONFIG)/'gui.new.json')
    original=app._read_json_file(path,{})
    # One skill per native task: a failure on priority S3 must never fall
    # through to S2/S1 inside MAA's own multi-plan loop.
    desired=queue_config(app,original,pending[:1])
    ReceiptStore(out/'configuration.before.json').save(original)
    result=dict(status='queue_unverified',targets=[],account_fact=str(store.path))
    changed=False
    try:
        if app._maa_task_queue_running() is not False:
            raise RuntimeError('queue ownership changed before training configuration')
        changed=True;app._atomic_write_json(path,desired)
        if app._read_json_file(path,{})!=desired:raise RuntimeError('training config readback mismatch')
        if app._maa_process_exists() is True:
            app.reload_maa_after_config_switch('独立干员培养队列，不重跑日常')
        with parent_receipts(app),native_queue():
            if app.run_maa_daily_tasks(enabled_tasks={'OperProgress'}) is not True:
                raise RuntimeError('training queue start unverified; do not resubmit')
            returned=app.wait_maa_complete(timeout=900,continue_after_chain_error=True,prestarted_boundary=True)
            text=app._get_current_maa_run_log()
            proof=out/'queue.log';proof.write_text(text,encoding='utf-8')
            result=evaluate(pending[:1],text)
            result.update(queue_returned_complete=returned is True,evidence=str(proof),preserved=cached,
                          account_fact=str(store.path),at=datetime.now().astimezone().isoformat())
            if returned is not True:result['status']='queue_unverified'
        if result['queue_verified'] and returned is True:
            for row in result['targets']:
                if row['status']=='verified_complete':
                    actual=row['observed_completed_level']
                    store.remember_verified(theme='Operators',capability=f"{row['name']}:skill{row['skill']}",
                        revision='mastery-v1',progress=actual,total=3,terminal_verified=actual==3,
                        run_id=out.name,evidence=[proof],identity_evidence=identity_evidence)
        if app._maa_task_queue_running() is False:
            if callable(getattr(app,'shot',None)):
                frame=Path(app.shot('operator_training_queue_return'))
                retained=out/'game_after_queue.png'
                shutil.copy2(frame,retained)
                result['game_screenshot']=str(retained)
            result['home_return_verified']=app.goto_main_menu() is True
    except Exception as exc:
        result.update(status='needs_attention',error=f'{type(exc).__name__}: {exc}')
    finally:
        if changed and app._maa_task_queue_running() is False:
            if app._maa_process_exists() is True:
                app.reload_maa_after_config_switch('恢复培养前任务配置，不启动后续业务')
            app._atomic_write_json(path,original)
            result['configuration_restored']=app._read_json_file(path,{})==original
        elif changed:result['configuration_restored']=False
        ReceiptStore(out/'receipt.json').save(result)
    if (result['status']=='goals_complete' and len(pending)>1):
        result.update(status='next_goal_ready',next_goal=pending[1])
    if result.get('configuration_restored') is not True:
        result['status']='configuration_restore_unverified'
    elif result.get('home_return_verified') is not True:
        result['status']='home_return_unverified'
    ReceiptStore(out/'receipt.json').save(result)
    return result


def service(app,*,root=None,packet=None,observer=None):
    root=Path(root or app.BASE)
    source=packet
    if source is None and (root/PLAN).exists():
        source=json.loads((root/PLAN).read_text('utf-8'))
    if source is None:return dict(status='not_configured',game_actions=0)
    records=[]
    # Only genuinely finished goals permit advancing; training-start/busy or
    # any error returns immediately. No timer polling or extra automation.
    for _ in range(max(1,len(goals(source)))):
        row=_service_one(app,root=root,packet=source,observer=observer)
        records.append(row)
        if source.get('account') is None and (root/PLAN).exists():
            source=json.loads((root/PLAN).read_text('utf-8'))
        if row.get('status')!='next_goal_ready':
            return dict(row,steps=records[:-1])
    return dict(status='needs_attention',reason='goal_advance_did_not_converge',steps=records)


@contextmanager
def boundary(app):
    import daily_post_run_review_v1 as review
    import daily_plain_popup_v3 as popup
    old_daily,old_findings,old_effects=app.mode_daily,review.findings,popup.effect_lines
    invoked=[False]
    def daily(enabled_tasks=None):
        ok=old_daily(enabled_tasks=enabled_tasks)
        full=enabled_tasks is None or set(enabled_tasks)=={'StartUp','Infrast','Recruit','Mall','Award'}
        if ok is True and full and not invoked[0]:
            invoked[0]=True
            try:row=service(app)
            except Exception as exc:row=dict(status='needs_attention',error=f'{type(exc).__name__}: {exc}')
            app._RUN_SUMMARY['operator_training']=row
        return ok
    def findings(report,manifest):
        rows=old_findings(report,manifest)
        row=(report.get('run_summary') or {}).get('operator_training') or {}
        if row.get('status') not in {'goals_complete','waiting_training','not_configured','disabled_or_empty',None}:
            rows.append(dict(kind='operator_training_attention',detail='干员培养未闭环；不重跑已完成日常',evidence=row))
        return rows
    def effects(report):
        lines=old_effects(report);row=(report.get('run_summary') or {}).get('operator_training') or {}
        if row.get('status')=='waiting_training':lines.append('技能培养：训练中或已开训，未冒记专三完成。')
        elif row.get('status')=='goals_complete':lines.append('技能培养：指定目标实际等级已核验完成。')
        elif row.get('status') not in {None,'not_configured','disabled_or_empty'}:lines.append('技能培养待核对，已保留证据。')
        return lines
    with patch.object(app,'mode_daily',daily),patch.object(review,'findings',findings), \
         patch.object(popup,'effect_lines',effects),patch.object(app,'run_operator_training',lambda:service(app),create=True):
        yield
