"""Actual named module requirements -> normal mission -> requirements recheck.

Keep the mature ordinary progression loop unchanged. Its already-perfect and
highest-difficulty policy must not short-circuit operator-specific missions.
"""
import json
from pathlib import Path
import re
from operator_optional_inspection_v1 import frame
from operator_module_missions_v1 import inspect,validate_job

def requirements(rows):
    upper=''.join(str(t) for t,x,y in rows if 250<x<1030 and 180<y<430)
    lower=''.join(str(t) for t,x,y in rows if 250<x<1030 and 450<y<780)
    damage_done='任务已完成' in upper and '怒潮凛冬' in upper and '伤害' in upper
    if '16-6' not in lower or '怒潮凛冬' not in lower or '常规作战' not in lower:
        return dict(status='requirements_unverified')
    if '任务已完成' in lower:stage=1
    else:
        match=re.search(r'([01])/1',lower)
        if not match:return dict(status='requirements_unverified')
        stage=int(match[1])
    return dict(status='missions_complete' if damage_done and stage==1 else 'missions_partial',
                damage_mission_complete=damage_done,stage_mission_progress=stage,stage_mission_total=1,
                mission_battle_required=stage==0,missions_complete=damage_done and stage==1)

def inspect_requirements(app,output):
    out=Path(output);row=inspect(app,out)
    if row['status']!='module_management_observed':return row
    pages=row['module_page']['items']
    names=[(x,y) for t,x,y in pages if str(t)=='迟到的勋章' and x>1200 and y>600]
    if len(names)!=1:return dict(row,status='module_card_unverified')
    app.tap(*names[0]);app.wait(1)
    selected=frame(app,out,'selected_module');row['selected_module']=selected
    unlocked=[(x,y) for t,x,y in selected['items'] if str(t)=='解锁' and 1100<x<1500 and 750<y<930]
    if len(unlocked)!=1:return dict(row,status='module_unlock_state_needs_ai')
    # This opens the requirement page. Never press its blue material confirm.
    app.tap(*unlocked[0]);app.wait(1)
    page=frame(app,out,'requirements');row['requirements_page']=page
    actual=requirements(page['items']);actual['evidence']=page['screenshot']
    row.update(actual_module_progress=actual,status=actual['status'],module_upgrade_requested=False)
    return row

def enter_normal(app,page,output):
    rows=page['items'];points=[(x,y) for t,x,y in rows if '前往' in str(t) and 750<x<1050 and 450<y<650]
    if len(points)!=1:raise ValueError('unique mission Go button required')
    app.tap(*points[0]);app.wait(3)
    current=frame(app,output,'stage_initial')
    for n in range(3):
        if current['items']:break
        app.wait(2);current=frame(app,output,'stage_loading_'+str(n))
    text=''.join(str(t) for t,x,y in current['items'])
    if '16-6' not in text:raise ValueError('mission did not reach 16-6')
    # This button names the SWITCH DESTINATION, not the current difficulty.
    # F's initial blue-three-badge normal page offered 险地作战. Clicking it
    # produced the red risk page/沙盘推演 and a 常规作战 return button.
    to_normal=[(x,y) for t,x,y in current['items'] if str(t)=='常规作战' and y>900]
    if len(to_normal)==1:
        app.tap(*to_normal[0]);app.wait(1);current=frame(app,output,'stage_normal')
    normal=(any(str(t)=='险地作战' and y>900 for t,x,y in current['items'])
            and not any('沙盘推演' in str(t) for t,x,y in current['items']))
    if not normal:raise ValueError('normal operation not verified; no Start')
    return current

def run(app,job_path,output):
    from ark_modules.core import ReceiptStore
    from operator_training_v1 import parent_receipts
    from copilot_start_receipt_v2 import boundary as copilot
    out=Path(output);out.mkdir(parents=True,exist_ok=True);sink=ReceiptStore(out/'receipt.json')
    root=Path(app.BASE);plan_path=root/'runtime_state/operator_module_plan.json'
    from recipient_beta_v1 import module_plan
    plan=module_plan(root,"mission_battle");module_plan(root,'inspect')
    from operator_home_labels_v1 import observe_account
    from account_progress_v1 import AccountProgress
    identity,identity_frames=observe_account(app)
    if not identity or (plan.get('account') and plan['account']!=identity):
        return dict(status='account_unverified_or_mismatch',battle_started=False)
    # Never auto-bind or overwrite a recipient account.
    store=AccountProgress(root/'runtime_state/accounts',identity)
    fact_key=dict(theme='OperatorModules',capability=plan['character_id']+':'+plan['module']+':missions',revision='module-missions-v1')
    cached=store.decision(**fact_key)
    if cached['action']=='skip_permanent_complete':
        return dict(status='verified_account_cache_no_battle',account_fact=cached,missions_complete=True)
    path=Path(job_path).resolve();path.relative_to(root/'copilot_jobs')
    job=json.loads(path.read_text('utf-8'))
    chars=json.loads((Path(app.MAA_ROOT)/'resource/battle_data.json').read_text('utf-8'))['chars']
    validate_job(job,plan['operator'],{c['name']:c.get('profession') for c in chars.values() if c.get('name')})
    if app._maa_task_queue_running() is not False:raise ValueError('queue owns device')
    before=inspect_requirements(app,out/'before');result=dict(status='requirements_unverified',before=before,stage='16-6',job=str(path))
    sink.save(result);actual=before.get('actual_module_progress') or {}
    def remember(value):
        if value.get('status') not in {'missions_partial','missions_complete'}:return
        count=int(value.get('damage_mission_complete') is True)+value['stage_mission_progress']
        result['account_fact']=store.remember_verified(**fact_key,progress=count,total=2,
            terminal_verified=count==2,run_id=str(out),evidence=[value['evidence']],identity_evidence=identity_frames)
    remember(actual)
    if actual.get('missions_complete') is True:
        result['status']='already_complete_no_battle';sink.save(result);return result
    if actual.get('mission_battle_required') is not True:return result
    result['stage_detail']=enter_normal(app,before['requirements_page'],out)
    with parent_receipts(app),copilot(app):
        entered=app._enter_formation(16,'16-6',allow_expiring_potion=False)
        if entered is not True:
            result.update(status='formation_unverified',entry_result=entered);sink.save(result);return result
        result['formation']=frame(app,out,'formation')
        if not app.run_maa_copilot(str(path)):
            result.update(status='native_start_unverified');sink.save(result);return result
        result['status']='battle_running';sink.save(result)
        outcome=app.verify_battle(timeout=600,stage_name='16-6')
        result.update(status='battle_finished_progress_pending',battle_result=outcome,game_after=frame(app,out,'battle_result'))
        sink.save(result)
        if app._maa_task_queue_running() is not False:return result
        if outcome in {'perfect','cleared'}:
            app.dismiss_reward();app.wait(2)
        app.goto_main_menu()
        result['after']=inspect_requirements(app,out/'after')
        after=result['after'].get('actual_module_progress') or {}
        remember(after)
        result['status']='missions_verified_complete' if after.get('missions_complete') is True else 'missions_still_partial'
        plan['actual_progress']=dict(after,source_run=str(out),module_unlocked=False)
        ReceiptStore(plan_path).save(plan);sink.save(result)
    return result
