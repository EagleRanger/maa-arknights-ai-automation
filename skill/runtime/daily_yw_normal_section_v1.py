"""YW's normal entrance is a graphic beside a separate bilingual label."""
from contextlib import contextmanager
from unittest.mock import patch
import re


def normal_point(items):
    for text,x,y in items:
        if 1000<x<1450 and 900<y<1020 and str(text).strip()=='REAL-IBERIA':
            return (int(x+155),int(y-15),'REAL-IBERIA')
    for text,x,y in items:
        if 1000<x<1450 and 900<y<1020 and str(text).strip() in ('雷亚-伊比利亚','雷亚-伊比利位'):
            return (int(x+125),int(y+15),str(text))
    return None


def select_normal(app,original,stage,event=None):
    if not re.fullmatch(r'YW-[1-8]',str(stage)) or (event or {}).get('stage_prefix')!='YW':return original(stage,event)
    path=app.shot('yw_normal_section_before');items=app.ocr(path)
    if any(str(t) in ('开始行动','开始突袭') for t,x,y in items):
        app.back();app.wait(2);path=app.shot('yw_normal_section_map');items=app.ocr(path)
    visible=app._visible_event_stages(items,event)
    if any(re.fullmatch(r'YW-[1-8]',code) for code in visible):return True
    if len({c for c in visible if re.fullmatch(r'YW-EX-[1-8]',c)})<2:return original(stage,event)
    point=normal_point(items)
    if point is None:return original(stage,event)
    app.tap(*point[:2]);app.wait(3)
    after=app.shot('yw_normal_section_after');rows=app.ocr(after)
    found=app._visible_event_stages(rows,event)
    ok=any(re.fullmatch(r'YW-[1-8]',code) for code in found)
    app._RUN_SUMMARY.setdefault('event',{})['normal_navigation']=dict(verified=ok,before=str(path),after=str(after),
        anchor=point[2],target=list(point[:2]),visible=list(found),method='exact_bilingual_normal_label_plus_current_EX_map')
    app.log('✅ EX地图已切回普通活动区' if ok else '❌ 普通区切换后未识别普通关卡节点')
    return ok


@contextmanager
def boundary(app):
    import daily_mainline_completion_v1 as completion
    install=completion.install;saved=[]
    def late(runtime,*args,**kwargs):
        result=install(runtime,*args,**kwargs)
        select=runtime._select_event_stage_section;event_steps=runtime._run_full_event_steps
        saved.append((select,event_steps))
        runtime._select_event_stage_section=lambda stage,event=None:select_normal(runtime,select,stage,event)
        def steps(event):
            value=event_steps(event)
            row=runtime._RUN_SUMMARY.get('event') or {}
            if event.get('stage_prefix')=='YW' and row.get('status')=='first_clear_done_farm_target_pending' and not row.get('task_rewards'):
                # A failed farming locator must not skip an independent,
                # already-authorized zero-sanity reward service.
                if runtime._maa_task_queue_running() is False and not runtime._RUN_SUMMARY.get('page_attention'):
                    runtime.claim_event_task_rewards(event)
            return value
        runtime._run_full_event_steps=steps
        return result
    with patch.object(completion,'install',late):
        try:yield
        finally:
            for select,steps in reversed(saved):app._select_event_stage_section=select;app._run_full_event_steps=steps
