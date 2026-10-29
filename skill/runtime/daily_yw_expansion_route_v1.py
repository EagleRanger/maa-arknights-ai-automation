"""Extend only the currently open YW event with its verified EX identities."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from run_daily_v100 import ROOT

MANIFEST=ROOT/'outputs/yw_ex_20261017/candidates_v3/candidate_manifest.json'
EX_OPENS=datetime(2026,10,16,16,tzinfo=timezone(timedelta(hours=8)))


def decorate(event,now=None):
    if not event or event.get('stage_prefix')!='YW' or event.get('_discovery_status')!='ready_for_visual_navigation':return event
    from vector_special_resources_v1 import verified_candidates
    result=deepcopy(event);result['story_stages']=list(dict.fromkeys([*result.get('story_stages',[]),'YW-ST-3']))
    result['section_keywords']=dict(normal=['雷亚-伊比利亚'],ex=['我们的伊比利亚'])
    now=now or datetime.now().astimezone()
    if now.tzinfo is None:now=now.replace(tzinfo=EX_OPENS.tzinfo)
    if now<EX_OPENS:return result
    rows=verified_candidates(ROOT,MANIFEST)
    names={s['display'] for s in result['stages']}
    for row,*_ in rows:
        if row['code'] not in names:
            result['stages'].append(dict(display=row['code'],internal=row['internal_stage'],
                ap_cost=row['ap_cost'],modes=['normal','challenge']))
    return result


@contextmanager
def boundary(app):
    import daily_mainline_completion_v1 as completion
    original_install=completion.install
    saved=[]
    def late(runtime,*args,**kwargs):
        value=original_install(runtime,*args,**kwargs)
        names=('discover_event','_select_event_stage_section','clear_event_stage')
        saved.extend((name,getattr(runtime,name)) for name in names)
        discover,select,clear=runtime.discover_event,runtime._select_event_stage_section,runtime.clear_event_stage
        def discovered(*a,**k):return decorate(discover(*a,**k),k.get('now'))
        def section(stage,event=None):
            if not stage.startswith('YW-EX-'):return select(stage,event)
            from daily_yw_ex_modules_v1 import select_ex
            from vector_special_resources_v1 import install
            frame=runtime.shot('yw_ex_scope_current');items=runtime.ocr(frame)
            if not any('-EX-' in code for code in runtime._visible_event_stages(items,event)):
                # No EX-date inference replaces the actual end-story badge.
                p,rows,pos=runtime._locate_event_stage('YW-ST-3',event=event)
                if not pos:return False
                if not runtime._story_node_map_marker_cleared(p,'YW-ST-3',rows):
                    if not runtime._clear_event_story_node(event,'YW-ST-3',pos):return False
                    p=runtime.shot('yw_ex_ending_verify');rows=runtime.ocr(p)
                    if not runtime._story_node_map_marker_cleared(p,'YW-ST-3',rows):return False
            installed=install(ROOT,runtime.MAA_ROOT,MANIFEST,queue_idle=lambda:runtime._maa_task_queue_running() is False)
            runtime._RUN_SUMMARY.setdefault('event',{})['ex_resources']=installed
            if installed.get('changed') and runtime._maa_process_exists():runtime.reload_maa_after_config_switch('YW EX地图空闲更新')
            return select_ex(runtime,select,stage,event)
        def cleared(event,stage,*a,**k):
            if not stage['display'].startswith('YW-EX-'):return clear(event,stage,*a,**k)
            from vector_special_resources_v1 import verified_candidates
            from run_yw_stage_v1 import candidate_jobs,yw_badge_ratio
            row=next(r for r,*_ in verified_candidates(ROOT,MANIFEST) if r['code']==stage['display'])
            with candidate_jobs(runtime,row),patch.object(runtime,'_event_normal_badges_ratio',yw_badge_ratio):
                return clear(event,stage,*a,**k)
        runtime.discover_event=discovered;runtime._select_event_stage_section=section;runtime.clear_event_stage=cleared
        return value
    with patch.object(completion,'install',late):
        try:yield
        finally:
            for name,value in reversed(saved):setattr(app,name,value)
