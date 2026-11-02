"""Existing single reward service + V143/V144 actual claim boundaries.

No daily/fight/base/cleanup delegation. Leave the game at home for its owner.
"""
from pathlib import Path
from datetime import datetime
from contextlib import ExitStack
import argparse
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def settled(result, summary):
    if not result.get('home_verified') or result.get('status')!='checked':return False
    rows=result.get('entries') or []
    labels={r.get('label') for r in rows if r.get('status') in ('claimed','already_claimed')}
    return {'限时签到','许愿墙'}<=labels and not any(r.get('status')=='pending' for r in rows)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');parser.add_argument('--output')
    args=parser.parse_args()
    if not args.execute:
        print('sign-in-only; no game actions; --execute --output <new outputs path>');return 0
    if not args.output:raise ValueError('explicit output required')
    output=(ROOT/args.output).resolve();output.relative_to(ROOT/'outputs')
    receipt_path=output/'receipt.json'
    import arknights_daily_runtime_v12 as app
    import event_signin_lifecycle_v1 as lifecycle
    import event_signin_v5 as claims
    from ark_host.environment import EnvironmentOwner,prepare
    from ark_host.cooperation_v1 import atomic_json
    from ark_host.runtime_services_v3 import boundary as services
    from daily_runtime_target_v1 import boundary as target
    from daily_game_update_v1 import boundary as update
    from event_signin_generic_v3 import boundary as generic
    from event_signin_preview_v7 import boundary as preview
    from event_daily_reward_entry_v1 import boundary as entries, popup_adapter
    from event_daily_reward_claim_v2 import boundary as effects
    from event_wish_wall_v1 import boundary as wall
    owner=EnvironmentOwner(app,owner='signin-service',clock=time.time,deadline=time.time()+600)
    owner.acquire()
    try:
        if receipt_path.exists():raise ValueError('existing receipt preserved; no implicit replay')
        receipt=dict(status='preparing',started_at=datetime.now().astimezone().isoformat(),
                     fights=0,refills=0,daily_invoked=False,cleanup_invoked=False)
        atomic_json(receipt_path,receipt)
        try:
            prepare(app)
            with ExitStack() as stack:
                for ctx in (target(app),services(app),update(app),entries(app),effects(),generic(),wall(app),preview()):
                    stack.enter_context(ctx)
                stack.enter_context(patch.object(app,'_foreground_mumu_display',return_value=True))
                claims.install(app)
                stack.enter_context(patch.object(app,'handle_popups',popup_adapter(app,app.handle_popups)))
                if not owner.start():raise ValueError('signin-only startup not verified')
                receipt['signin']=lifecycle.service(app)
                receipt['status']='completed' if settled(receipt['signin'],app._RUN_SUMMARY) else 'needs_ai'
        except Exception as exc:
            receipt.update(status='needs_ai',error=f'{type(exc).__name__}: {exc}')
        receipt.update(run_summary=app._RUN_SUMMARY,finished_at=datetime.now().astimezone().isoformat())
        atomic_json(receipt_path,receipt)
        print(receipt['status'],str(receipt_path),flush=True)
        return 0 if receipt['status']=='completed' else 2
    finally:owner.release()

if __name__=='__main__':raise SystemExit(main())
