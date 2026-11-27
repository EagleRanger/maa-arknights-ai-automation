"""Share map navigation only when the current event supplies the evidence."""
from contextlib import ExitStack,contextmanager
from pathlib import Path
from datetime import datetime
import re
from unittest.mock import patch
from scan_retry_v1 import norm,recover


def family(event,stage):
    if not isinstance(event,dict):return set()
    if event.get('zero_sanity') or 'zero_sanity' in str(event.get('kind','')) or event.get('classification')=='zero_sanity_special_event':return set()
    code=norm(stage)
    if not re.fullmatch(r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+',code):return set()
    if code.split('-')[0]!=norm(event.get('stage_prefix','')):return set()
    entries=[norm(s.get('display','')) for s in event.get('stages',[]) if isinstance(s,dict)]
    if entries.count(code)!=1:return set()
    prefix=code.rsplit('-',1)[0]+'-'
    return {c for c in entries if c.startswith(prefix) and c[len(prefix):].isdigit()}


def nodes(rows,codes):
    found={}
    for s,x,y in rows:
        c=norm(s)
        if c in codes and 100<=x<=1905 and 180<=y<=930:
            if c in found:return {}  # ambiguous page, not a reusable board
            found[c]=(x,y)
    return found


def standard_frame(path):
    from PIL import Image
    try:
        with Image.open(path) as image:return image.size==(1920,1080)
    except (OSError,TypeError,ValueError):return False


def page_matches(rows,event,codes):
    words={norm(s) for s,x,y in rows}
    if any(any(k in w for k in ('开始行动','代理指挥','开始突袭','推荐平均等级','销量与影响等级',
            '确认','确定','取消','任务失败','行动结束','获得物资','理智恢复','附加条件','获得蚀刻章',
            '首次获得','愿望清单','WISHLIST','MISSIONRESULTS','MISSIONACCOMPLISHED','MISSIONFAILED'))
            for w in words):return False
    labels=[s for vs in (event.get('section_keywords') or {}).values() if isinstance(vs,list) for s in vs]
    labels.extend(event.get('combat_keywords') or [])
    return any(norm(s) in words for s in labels if isinstance(s,str) and s.strip()) and len(nodes(rows,codes))>=2


def refine(app,path,rows,stage,codes):
    if stage in nodes(rows,codes) or len(nodes(rows,codes))<2:return rows
    prefix=stage.rsplit('-',1)[0]
    if sum(norm(t).rstrip('-')==prefix and 100<x<1905 and 180<y<930 for t,x,y in rows)!=1:return rows
    return recover(app,path,rows,target=stage,roi=(100,140,1906,951),line_only=True)


class Located(Exception):pass
class StillMissing(Exception):pass
class TargetDetail(Exception):pass


def reuse_shortcut(app,open_detail,event,stage,**kw):
    """Map callers still get a map. Detail callers may keep a matching shortcut drawer."""
    shortcut=getattr(app,'_enter_event_map_from_terminal_last_battle',None)
    if not kw.get('ensure_map',True) or not callable(shortcut) or not family(event,stage):
        return open_detail(event,stage,**kw)
    def enter(ev,items):
        matched=app._terminal_last_battle_event_stage(items,ev)
        if (ev.get('name')!=event.get('name') or not matched or matched[0]!=stage):
            return shortcut(ev,items)
        read=app.ocr
        def current(path):
            rows=read(path)
            if (path and Path(path).name.startswith('event_last_battle_'+stage+'_') and
                    app._maa_task_queue_running() is False):
                from event_layout_profiles_v1 import inspect_frame
                if inspect_frame(path,rows,ev,stage)['profile']:
                    raise TargetDetail(path,rows,' '.join(str(t) for t,_,_ in rows))
            return rows
        with patch.object(app,'ocr',current):return shortcut(ev,items)
    try:
        with patch.object(app,'_enter_event_map_from_terminal_last_battle',enter):
            return open_detail(event,stage,**kw)
    except TargetDetail as found:
        app.log(f'[活动导航] 快捷卡已打开{stage}目标详情，直接沿用')
        return found.args


def remaining_progress(app,event):
    """Return pending (stage, mode) in execution order; None means no usable ledger."""
    if not isinstance(event,dict) or not event.get('name') or not event.get('start'):return None
    data=app._load_event_progress()
    state=(data.get('events') or {}).get(event['name']) or {}
    if event.get('kind')=='rerun':
        replay=state.get('task_replay') or {}
        if replay.get('event_start')!=event['start'] or not event.get('replay_stages'):return None
        rows=replay.get('stages') or {}
        targets=[(s,'normal') for s in event['replay_stages']]+[(s,'challenge') for s in event.get('required_challenge_replays',[])]
        def done(s,m):
            row=rows.get(s if m=='normal' else s+':challenge')
            return isinstance(row,dict) and row.get('status')=='completed' and type(row.get('actual_runs')) is int and row['actual_runs']>0
        return [(s,m) for s,m in targets if not done(s,m)]
    if not event.get('stages') or event.get('zero_sanity') or not state.get('stages'):return None
    # Use the same actual stages (including tutorials), modes and evidence rules
    # as the first-clear worker. A prior occurrence with the same name is not proof.
    def done(k,m):
        row=(((state['stages'].get(k) or {}).get('modes') or {}).get(m) or {})
        try:
            if not (datetime.fromisoformat(event['start'])<=datetime.fromisoformat(row['updated_at'])
                    <=datetime.fromisoformat(event['end'])):return False
        except (KeyError,ValueError,TypeError):return False
        return app._event_mode_has_trusted_clear_evidence(event['name'],k,m)
    # The legacy proof reader opens the entire file per mode. Reuse this read for
    # this decision only; release it before any game operation or progress write.
    with patch.object(app,'_load_event_progress',lambda:data):
        return [(s['display'],m) for s in app._event_execution_stages(event)
                for m in app._event_stage_modes(event,s) if not done(s['display'],m)]


@contextmanager
def boundary(app):
    old=getattr(app,'_locate_event_stage',None)
    if not callable(old):yield;return
    def locate(stage,*args,**kw):
        event=kw.get('event') or (args[0] if args else None)
        if not event and callable(getattr(app,'get_active_event',None)):event=app.get_active_event()
        codes=family(event,stage)
        if not codes:return old(stage,*args,**kw)
        recent=[];last=[];selecting=False
        read=app.ocr;select=getattr(app,'_select_event_stage_section',None)
        def ocr(path):
            rows=read(path)
            tag=Path(path).name
            if selecting:
                if any(tag.startswith(f'event_section_{p}{stage}_') for p in ('','map_','verify_')):
                    last[:]=[(path,rows)]
                else:last.clear()
                return rows
            if not tag.startswith(f'event_stage_{stage}_'):return rows
            if not page_matches(rows,event,codes) or not standard_frame(path):recent.clear();return rows
            fixed=refine(app,path,rows,stage,codes)
            siblings=nodes(fixed,codes)
            if (set(siblings)==codes-{stage} and
                    sum(norm(t).rstrip('-')==stage.rsplit('-',1)[0] and 100<x<1905 and 180<y<930 for t,x,y in fixed)==1):
                if recent and any(abs(a-b)>8 for k in siblings for a,b in zip(siblings[k],recent[-1][1][k])):
                    recent.clear()
                if not recent or recent[-1][0]!=str(path):recent.append((str(path),siblings))
                if len(recent)>=3:raise StillMissing(path,fixed)
            else:recent.clear()
            return fixed
        def section(*a,**k):
            nonlocal selecting
            selecting=True;last.clear()
            try:
                with ExitStack() as flow:
                    visible=getattr(app,'_visible_event_stages',None)
                    if callable(visible):
                        # The legacy first read omits event=, which otherwise
                        # lets a neighbouring activity vouch for this section.
                        def in_catalog(rows,event_arg=None,**kwargs):
                            return visible(rows,kwargs.get('event') or event_arg or event)
                        flow.enter_context(patch.object(app,'_visible_event_stages',in_catalog))
                    for name in ('tap','swipe','back'):
                        fn=getattr(app,name,None)
                        if callable(fn):
                            def input_(*args,_fn=fn,**kw):
                                last.clear();return _fn(*args,**kw)
                            flow.enter_context(patch.object(app,name,input_))
                    ok=select(*a,**k)
            finally:selecting=False
            if ok is True and last:
                path,rows=last[-1]
                if page_matches(rows,event,codes) and standard_frame(path):
                    fixed=refine(app,path,rows,stage,codes)
                    pt=nodes(fixed,codes).get(stage)
                    if pt and app._event_stage_marker_reliable(pt) and app._maa_task_queue_running() is False:
                        raise Located(path,fixed,pt)
            return ok
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(app,'ocr',ocr))
                if callable(select):stack.enter_context(patch.object(app,'_select_event_stage_section',section))
                return old(stage,*args,**kw)
        except Located as e:return e.args
        except StillMissing as e:
            path,rows=e.args
            app._RUN_SUMMARY.setdefault('event',{})['unresolved_map_card']=dict(stage=stage,
                evidence=str(path),reason='same_board_three_roi_reads_unverified')
            app.log(f'[活动地图] {stage} 三次复读同一完整分区仍不唯一，不再原地滑动','WARN')
            return path,rows,None
    with ExitStack() as stack:
        open_detail=getattr(app,'_open_event_stage_detail',None)
        if callable(open_detail):
            stack.enter_context(patch.object(app,'_open_event_stage_detail',
                lambda ev,stage,**kw:reuse_shortcut(app,open_detail,ev,stage,**kw)))
        nav=getattr(app,'verify_event_navigation_ready',None)
        if callable(nav):
            def preflight(event=None):
                ev=event or app.get_active_event()
                pending=remaining_progress(app,ev)
                if pending is None:return nav(ev)
                if pending:
                    stage,mode=pending[0]
                    order=app._event_execution_stages
                    stages=order(ev)
                    if not stages or stages[0]['display']==stage or not any(s['display']==stage for s in stages):return nav(ev)
                    app._RUN_SUMMARY.setdefault('event',{})['navigation_target']=dict(stage=stage,mode=mode)
                    # Point the original preflight at the first real pending node.
                    # Leave the catalog, chapter navigation and business order intact.
                    def probe_order(e):
                        return sorted(stages,key=lambda s:s['display']!=stage) if e is ev else order(e)
                    with patch.object(app,'_event_execution_stages',probe_order):return nav(ev)
                app._RUN_SUMMARY.setdefault('event',{})['progress_navigation']=dict(
                    status='skipped_verified_completion',event=ev['name'],event_start=ev['start'])
                app.log('[活动进度] 本期已配置关卡和模式均有完成记录，不再进地图查重')
                return True
            stack.enter_context(patch.object(app,'verify_event_navigation_ready',preflight))
        stack.enter_context(patch.object(app,'_locate_event_stage',locate))
        verify=getattr(app,'_event_stage_detail_confirmed',None)
        if callable(verify):
            from event_layout_profiles_v1 import detail_rows,CODE,ORDINARY,labels
            def detail(text,stage,items=None):
                if items is None:return verify(text,stage)
                rows=detail_rows(items)
                if rows!=list(items):
                    codes=[s for s in labels(rows,ORDINARY.panel.header) if CODE.fullmatch(s)]
                    if codes!=[norm(stage)]:return False
                    text=' '.join(str(t) for t,_,_ in rows)
                return verify(text,stage,rows)
            stack.enter_context(patch.object(app,'_event_stage_detail_confirmed',detail))
        yield
