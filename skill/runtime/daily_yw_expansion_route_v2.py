"""Reconcile cached YW plans too; normal clear never closes its EX challenge."""
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch
import daily_yw_expansion_route_v1 as previous

_decorate=previous.decorate


def decorate(event,now=None):
    result=_decorate(event,now)
    if result is event:return result
    now=now or datetime.now().astimezone()
    if now.tzinfo is None:now=now.replace(tzinfo=previous.EX_OPENS.tzinfo)
    if now<previous.EX_OPENS:return result
    from vector_special_resources_v1 import verified_candidates
    admitted={row['code']:row for row,*_ in verified_candidates(previous.ROOT,previous.MANIFEST)}
    for stage in result['stages']:
        row=admitted.get(stage['display'])
        if not row:continue
        if stage.get('internal')!=row['internal_stage']:
            raise ValueError('YW EX cached internal identity mismatch: '+stage['display'])
        stage['modes']=['normal','challenge']
        stage['ap_cost']=row['ap_cost']
    return result


def remember(app,event):
    revised=decorate(event)
    if revised is event:return event
    # Keep existing references valid: plans compiled earlier point at this
    # object, and _update_event_progress resolves the same current config.
    event.clear();event.update(revised)
    rows=getattr(app,'ACTIVE_EVENTS',None)
    if isinstance(rows,list):
        rows[:]=[event,*[r for r in rows if r is not event and r.get('name')!=event.get('name')]]
    return event


@contextmanager
def boundary(app):
    import daily_mainline_completion_v1 as completion
    saved=[]
    with patch.object(previous,'decorate',decorate),previous.boundary(app):
        original_install=completion.install
        def late(runtime,*args,**kwargs):
            result=original_install(runtime,*args,**kwargs)
            configured,first=runtime._configured_event_from_name,runtime.mode_event_first_clear
            saved.append((configured,first))
            def resolve(name):
                event=configured(name)
                return remember(runtime,event) if event else event
            def clear(event=None):
                event=event or runtime.get_active_event()
                if event:event=remember(runtime,event)
                if event and event.get('stage_prefix')=='YW':
                    runtime._RUN_SUMMARY['event_mode_schedule']=[
                        dict(stage=s['display'],mode=m) for s in runtime._event_execution_stages(event)
                        for m in runtime._event_stage_modes(event,s)]
                return first(event)
            runtime._configured_event_from_name=resolve
            runtime.mode_event_first_clear=clear
            return result
        with patch.object(completion,'install',late):
            try:yield
            finally:
                for configured,first in reversed(saved):
                    app._configured_event_from_name=configured;app.mode_event_first_clear=first
