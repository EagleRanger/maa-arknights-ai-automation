"""Verify the first unfinished mode's map, not always normal YW-1."""
from copy import deepcopy
from contextlib import contextmanager
from unittest.mock import patch
import daily_yw_expansion_route_v2 as previous


def first_pending(app,event):
    for stage in app._event_execution_stages(event):
        for mode in app._event_stage_modes(event,stage):
            if not app._event_mode_has_trusted_clear_evidence(event['name'],stage['display'],mode):
                return stage,mode
    return None


@contextmanager
def boundary(app):
    import daily_mainline_completion_v1 as completion
    saved=[]
    with previous.boundary(app):
        original_install=completion.install
        def late(runtime,*args,**kwargs):
            result=original_install(runtime,*args,**kwargs)
            old=runtime.verify_event_navigation_ready;saved.append(old)
            def verify(event=None):
                event=event or runtime.get_active_event()
                if not event or event.get('stage_prefix')!='YW':return old(event)
                event=previous.remember(runtime,event)
                pending=first_pending(runtime,event)
                if not pending:return old(event)
                stage,mode=pending
                probe=deepcopy(event)
                probe['stages']=[deepcopy(stage),*[s for s in probe['stages'] if s['display']!=stage['display']]]
                runtime._RUN_SUMMARY.setdefault('event',{})['navigation_target']=dict(stage=stage['display'],mode=mode,
                    reason='first_unfinished_mode_not_first_configured_stage')
                return old(probe)
            runtime.verify_event_navigation_ready=verify
            return result
        with patch.object(completion,'install',late):
            try:yield
            finally:
                for old in reversed(saved):app.verify_event_navigation_ready=old
