"""Current YW EX stages use the accepted detail/formation/Copilot loop."""
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from run_daily_v100 import ROOT,read


def select_ex(app,original,stage,event=None):
    if '-EX-' not in stage:return original(stage,event)
    frame=app.shot('yw_ex_live_section');items=app.ocr(frame)
    if any('-EX-' in code for code in app._visible_event_stages(items,event)):return True
    # Details must be closed by their owner before switching the map section.
    text=''.join(str(t) for t,_,_ in items)
    if '开始行动' in text or '开始突袭' in text:
        app.back();app.wait(2);frame=app.shot('yw_ex_live_map');items=app.ocr(frame)
        if any('-EX-' in code for code in app._visible_event_stages(items,event)):return True
    label=app.find_text(items,'我们的伊比利亚')
    if not label or label[0]<1450 or label[1]<900:return False
    app.tap(int(label[0]+155),int(label[1]-15));app.wait(3)
    frame=app.shot('yw_ex_live_section_verified');items=app.ocr(frame)
    return any('-EX-' in code for code in app._visible_event_stages(items,event))


def run_scope(app,packet):
    from vector_special_resources_v1 import install,verified_candidates
    from run_yw_stage_v1 import candidate_jobs,yw_badge_ratio
    app._DAILY_EXISTING_SANITY_ONLY=True
    app._DAILY_COMPLETION_NOT_BEFORE=datetime.now()
    result=app._RUN_SUMMARY.setdefault('ex_continuation',dict(stages=[],preserved=packet['preserve']))
    if app._ensure_execution_plan('full') is None or app._maa_task_queue_running() is not False:return False
    if not app.goto_main_menu():return False
    from sss_delegate_result_v1 import post_service
    result['sss_settlement']=post_service(app,packet)
    if not result['sss_settlement'].get('home_verified'):return False
    pending=result['sss_settlement'].get('rewards') or {}
    if pending.get('complete') is not True:
        counts=pending.get('counts') or {}
        packet['pending']=[t for t in packet['pending'] if not t.startswith('保全：')]
        packet['pending'].append(f"保全：当前数据增补条{counts.get('strip','未确认')}/60、增补仪{counts.get('device','未确认')}/24；保留周一5张卡，不再重复旧卡死作业")
    app._capture_stamina_observation('start',navigate=True)
    tip=app.save_maa_daily_stage_tip();event=app.discover_event('昨日海',tip.get('active_side_stories'),app.MAA_ROOT)
    if not event or event.get('_discovery_status')!='ready_for_visual_navigation':return False
    manifest=ROOT/packet['candidate_manifest']
    rows=verified_candidates(ROOT,manifest)
    event['story_stages']=['YW-ST-3']
    event['section_keywords']=dict(normal=['雷亚-伊比利亚'],ex=['我们的伊比利亚'])
    event['stages'] += [dict(display=row['code'],internal=row['internal_stage'],
        modes=['normal','challenge'],ap_cost=row['ap_cost']) for row,*_ in rows]
    app.ACTIVE_EVENTS.insert(0,event)
    app._RUN_SUMMARY['flow_target']=dict(type='event',name=event['name'])
    app._RUN_SUMMARY.setdefault('event',dict(name=event['name'],stages={}))
    result['resource_install']=install(ROOT,app.MAA_ROOT,manifest,queue_idle=lambda:app._maa_task_queue_running() is False)
    if result['resource_install'].get('changed') and app._maa_process_exists():
        app.reload_maa_after_config_switch('YW EX已核验地图资源，空闲重载')
    original=app._select_event_stage_section
    stop=False
    with patch.object(app,'_select_event_stage_section',lambda stage,event=None:select_ex(app,original,stage,event)), \
         patch.object(app,'_event_normal_badges_ratio',yw_badge_ratio):
        for row,*_ in rows:
            if row['code'] not in packet['allowed_stages']:continue
            stage=next(s for s in event['stages'] if s['display']==row['code'])
            for mode in ('normal','challenge'):
                if datetime.now().astimezone()>=datetime.fromisoformat(packet['battle_not_after']):
                    result['stop_reason']='battle_window_closed';stop=True;break
                with candidate_jobs(app,row,packet['battle_not_after']):
                    outcome=app.clear_event_stage(event,stage,mode=mode,max_attempts=5)
                result['stages'].append(dict(stage=row['code'],mode=mode,outcome=str(outcome),verified=outcome is True))
                # Actual live badge acceptance belongs to clear_event_stage. No
                # farm fallback after EX failure and no refill/old-job replay.
                if outcome is not True:
                    result['stop_reason']=str(outcome);stop=True;break
            if stop:break
    result['rewards_verified']=app.claim_event_task_rewards(event) is True if not app._RUN_SUMMARY.get('page_attention') else False
    app._RUN_SUMMARY['final_daily_requested']=True
    daily=app._run_full_final_daily_step() is True
    app._RUN_SUMMARY['final_daily_completed']=daily
    result['final_daily_completed']=daily
    complete=len(result['stages'])==2*len(packet['allowed_stages']) and all(r['verified'] for r in result['stages'])
    packet['pending']=[t for t in packet['pending'] if not t.startswith('EX：')]
    if not complete:packet['pending'].append('EX：仍有未完成普通/突袭，停止原因为'+result.get('stop_reason','unknown')+'；未用药石，未转刷普通')
    return bool(daily and result['rewards_verified'] and (complete or result.get('stop_reason')=='stamina'))
