"""Decide from this owner's persisted business plan, never from conversation text."""
from datetime import datetime,timezone

def decision(state,*,alive=True,now=None):
    results=state.get('results') or {};plan=state.get('requested_steps') or []
    done=[k for k,v in results.items() if v.get('status') in ('skipped','succeeded')]
    pending=[r for r in plan if r['key'] not in results]
    issues=[k for k,v in results.items() if k not in done]
    out=dict(run_id=state.get('run_id'),status=state.get('status'),done=done,
             pending=[r['key'] for r in pending],unresolved=issues,
             evidence='receipt.json',next=None,steps=[])
    if state.get('finished_at') or state.get('status') in ('closed','cleanup_partial'):
        return dict(out,next='terminal_no_replay')
    if not alive:return dict(out,next='owner_gone_reconcile')
    inflight=state.get('in_flight')
    if inflight or any(v.get('status') in ('unknown','interrupted') or
            v.get('status') in ('partial','failed') and not (v.get('data') or {}).get('before_action')
            for v in results.values()):
        return dict(out,next='reconcile_effect',in_flight=inflight)
    if not plan:return dict(out,next='read_legacy_receipt')
    end=(state.get('context') or {}).get('deadline')
    if end and datetime.fromisoformat(end)<=(now or datetime.now(timezone.utc)):
        return dict(out,next='expired_no_replay')
    if state.get('environment_ready') is not True:return dict(out,next='recover_current_page')
    ready=[r for r in pending if all((results.get(k) or {}).get('status')=='succeeded' for k in r.get('requires',[]))]
    if ready:return dict(out,next='continue_remaining',steps=[ready[0]])
    return dict(out,next='review_unfinished' if issues or pending else 'finish')
