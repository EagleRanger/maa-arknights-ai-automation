"""Attach a bounded activity-layout review to the existing execution outbox."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
import json
from unittest.mock import patch
import event_layout_profiles_v1 as layout

ACTIVE = ContextVar('activity_layout_context', default=None)


def review(event, stage, phase, observation=None):
    event=event or {}
    return dict(schema='activity_layout_review_v1', activity=event.get('name'),
        stage_prefix=event.get('stage_prefix'), kind=event.get('kind'), target=stage, phase=phase,
        instance={k:str(event[k]) for k in ('event_id','start','end','_source') if event.get(k)},
        stage_ids=[str(r['internal']) for r in (event.get('stages') or [])
                   if r.get('display')==stage and r.get('internal')][:3],
        observations=observation or {}, requested_action='compare_layout_and_replay_before_next_version',
        guide='docs/visual_recognition_rnd_playbook_v1.md#活动版式适配',
        replay='tools/replay_event_layout_v1.py', resume='recheck_same_target_only',
        counts_as_battle_attempt=False)


def publish(app,event,stage,phase,frame,rows,observation):
    from event_page_guard_v1 import publish_page_attention
    summary=app._RUN_SUMMARY
    key=summary.setdefault('navigation_guard_run_key',datetime.now().astimezone().isoformat())
    reason='event_layout_review:'+str(event.get('name') or '')+':'+phase
    item=dict(layout_review=review(event,stage,phase,observation),
              ocr=' '.join(str(t) for t,x,y in rows)[:1800],
              anchors=[[str(t)[:64],int(x),int(y)] for t,x,y in rows if 1200<=x<=1920][:48])
    if frame:item['screenshot']=str(frame)
    try:
        path=publish_page_attention(app.OUTPUT_DIR,key,stage,reason,[item])
    except OSError as exc:
        summary.setdefault('event',{})['layout_feedback_error']=str(exc)
        app.log(f'{stage} 版式证据未能入队：{exc}；刷取保持未核验。','ERROR')
        return
    note=dict(reason=reason,path=str(path),affected_scope='event_farm',blocks_daily=False)
    if summary.setdefault('event',{}).get('layout_attention')!=note:
        summary['event']['layout_attention']=note
        print('[PROJECT_ATTENTION_NOW] '+json.dumps(note,ensure_ascii=False),flush=True)


class FarmPort:
    def __init__(self,app):
        self.app=app; self.frame=None; self.rows=[]; self.observation={}

    def __getattr__(self,name):return getattr(self.app,name)

    def _open_event_stage_detail(self,event,stage,**kw):
        # Keep the last actual navigator frame, including a failed locator's
        # own frame before it backs out. No second OCR/click to gather evidence.
        ocr=self.app.ocr
        def seen(path,*args,**kwargs):
            rows=ocr(path,*args,**kwargs)
            self.frame,self.rows=path,rows
            return rows
        with patch.object(self.app,'ocr',seen):
            opened=self.app._open_event_stage_detail(event,stage,**kw)
        if not opened:return None
        self.frame,self.rows,_=opened
        self.observation=layout.inspect_frame(self.frame,self.rows,event,stage)
        return opened if self.observation['profile'] else None

    def _event_normal_badges_ratio(self,path):
        return layout.PROFILES[self.observation['profile']].badges(path)


def configure(original,app,event):
    import stage_sanity_cost_v2 as costs
    port=FarmPort(app)
    before=app._RUN_SUMMARY.get('page_attention')
    def read(path,items,recognizer):
        return layout.price(port.observation,path,items,recognizer)
    token=ACTIVE.set(event)
    try:
        with patch.object(costs,'read_cost',read):
            ok=original(port,event)
    finally:
        ACTIVE.reset(token)
    gate=app._RUN_SUMMARY.get('event',{}).get('farm_gate') or {}
    if port.observation:gate['layout']=port.observation
    if ok or not gate.get('stage'):return ok
    # A failed navigator may have already raised a blocking navigation event;
    # never enqueue a duplicate or clear its real navigation safety flag.
    after=app._RUN_SUMMARY.get('page_attention')
    if after is not before and (after or {}).get('path'):return ok
    phase=gate['reason']
    if not port.frame and phase=='detail_unverified':
        try:
            port.frame=app.shot('event_layout_unverified')
            if port.frame:port.rows=app.ocr(port.frame)
        except (OSError,ValueError) as exc:
            port.observation['capture_error']=type(exc).__name__
    if not port.observation:
        port.observation=layout.identify(port.rows,expected=gate['stage'],event=event)
    if gate.get('three_stars') is not None:
        port.observation.update(three_stars=gate['three_stars'],unit_cost=gate['unit_cost'])
    publish(app,event,gate['stage'],phase,port.frame,port.rows,port.observation)
    return ok


def verify_normal(app,original,event,stage):
    # Only the MAA-discovered ordinary branch; older card-layout/EX/tutorial
    # adapters still own their modes. Reuse original navigation/back handling.
    if (event.get('_discovery_status')!='ready_for_visual_navigation'
            or not layout.NORMAL.fullmatch(stage)):
        return original(event,stage)
    opened=app._open_event_stage_detail
    old_ratio=app._event_normal_badges_ratio
    app._RUN_SUMMARY.setdefault('event',{}).pop('last_layout_miss',None)
    chosen={}
    def inspect(e,target,**kw):
        result=opened(e,target,**kw)
        if not result or target!=stage:return result
        path,rows,_=result
        obs=layout.inspect_frame(path,rows,e,target)
        if not obs['profile']:
            # Associate the original frame with the existing battle/navigation
            # feedback; an unrecognized page is unknown, NOT an unlit badge.
            app._RUN_SUMMARY.setdefault('event',{})['last_layout_miss']=dict(
                screenshot=str(path),stage=target,review=review(e,target,'stage_verification',obs))
            return None
        chosen[str(path)]=layout.PROFILES[obs['profile']]
        return result
    def ratio(path):
        selected=chosen.get(str(path))
        return selected.badges(path) if selected else old_ratio(path)
    with patch.object(app,'_open_event_stage_detail',inspect),patch.object(app,'_event_normal_badges_ratio',ratio):
        return original(event,stage)


@contextmanager
def boundary(app):
    import event_farm_evidence_v2 as farm
    import event_farm_detail_handoff_v1 as handoff
    import daily_policy_v23 as policy
    import stage_sanity_cost_router_v1 as router
    original, old_attention=farm.configure,app._event_page_attention
    old_metadata=policy._publish_attention
    old_install=policy.install
    old_verify=app.verify_event_stage_cleared
    def install(port):
        was_installed=getattr(port,'_daily_policy_v23_installed',False)
        result=old_install(port)
        if not was_installed:
            installed_steps=port._run_full_event_steps
            def steps(event):
                token=ACTIVE.set(event)
                try:return installed_steps(event)
                finally:ACTIVE.reset(token)
            port._run_full_event_steps=steps
        return result
    def metadata(runtime,reason,**kw):
        if reason!='event_unique_maa_route_missing':return old_metadata(runtime,reason,**kw)
        rows=kw.get('observations')
        if rows is None:
            p=runtime.shot(reason); rows=[dict(screenshot=str(p) if p else None,ocr=runtime.ocr_text(p) if p else '')]
        event=ACTIVE.get() or runtime._RUN_SUMMARY.get('event') or {}
        kw['observations']=[dict(row,layout_review=review(event,kw.get('stage',''),'activity_intake',
            {'metadata_reason':str(kw.get('battle_result') or '')[:400]})) for row in rows]
        return old_metadata(runtime,reason,**kw)
    def attention(reason,stage='',battle_result=None,observations=None):
        if reason in ('event_navigation_recovery_exhausted','post_battle_detail_unverified','formation_recovery_detail_unverified'):
            event=ACTIVE.get() or app._RUN_SUMMARY.get('event') or {}
            miss=(app._RUN_SUMMARY.get('event') or {}).get('last_layout_miss') or {}
            if not observations and stage==miss.get('stage'):
                observations=[dict(screenshot=miss['screenshot'],layout_review=miss['review'])]
            if not observations:
                path=app.shot('event_layout_navigation_probe')
                observations=[dict(screenshot=str(path) if path else None,ocr=app.ocr_text(path) if path else '')]
            observations=[{'layout_review':review(event,stage,'navigation',{'reason':reason}),**row} for row in observations]
        return old_attention(reason,stage=stage,battle_result=battle_result,observations=observations)
    old_ready=handoff.current_detail_ready
    def ready(port,stage):
        # Legacy special modes retain their own routine. The ordinary handoff
        # rechecks the actual target and proxy selection on ONE fresh frame.
        if not layout.NORMAL.fullmatch(stage):return old_ready(port,stage)
        frame=port.shot(f'event_farm_handoff_{stage}')
        if not frame:return False
        rows=port.ocr(frame)
        obs=layout.inspect_frame(frame,rows,ACTIVE.get(),stage)
        return bool(obs['profile'] and layout.PROFILES[obs['profile']].badges(frame)>=.08
                    and port._event_proxy_command_selected(frame))
    def route(original,path,rows,ocr):
        # No YW fallback with missing/conflicting identity. Preserve confirmed
        # non-normal/legacy consumers rather than imposing a farming contract.
        obs=layout.identify(rows)
        if len(obs['header_codes'])==1 and not layout.NORMAL.fullmatch(obs['header_codes'][0]):
            return router.normal_cost(path,rows,ocr)
        return layout.price(obs,path,rows,ocr)
    with patch.object(farm,'configure',lambda port,e:configure(original,port,e)), \
         patch.object(app,'verify_event_stage_cleared',lambda e,s:verify_normal(app,old_verify,e,s)), \
         patch.object(handoff,'current_detail_ready',ready),patch.object(router,'route',route), \
         patch.object(policy,'_publish_attention',metadata),patch.object(app,'_event_page_attention',attention), \
         patch.object(policy,'install',install):
        yield
