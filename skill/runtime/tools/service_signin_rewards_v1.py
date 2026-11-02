"""Single sign-in module, no fights/base/daily tail/implicit emulator close."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--output')
    args=p.parse_args()
    if not args.execute:
        print('sign-in-only; game actions0; --execute and unique --output required');return 0
    if not args.output:raise ValueError('explicit output required')
    output=(ROOT/args.output).resolve();output.relative_to(ROOT/'outputs')
    if (output/'receipt.json').exists():raise ValueError('existing receipt preserved; no implicit replay')
    import arknights_daily_runtime_v12 as app
    from ark_host.environment import EnvironmentOwner,prepare
    from ark_host.runtime_services_v3 import boundary as services
    from daily_runtime_target_v1 import boundary as target
    from daily_game_update_v1 import boundary as update
    from event_signin_generic_v3 import boundary as generic
    from event_signin_preview_v7 import boundary as preview
    import event_signin_v5 as claims
    import event_signin_lifecycle_v1 as signin
    from ark_host.cooperation_v1 import atomic_json
    receipt=dict(status='preparing',started_at=datetime.now().astimezone().isoformat(),
        fights=0,refills=0,daily_invoked=False,cleanup_invoked=False,game_left_for_daily=True)
    prepare(app)
    owner=EnvironmentOwner(app,owner='signin-service',clock=time.time,deadline=time.time()+600)
    try:
        owner.acquire()
        with target(app),services(app),update(app),generic(),preview(), \
             patch.object(app,'_foreground_mumu_display',return_value=True):
            claims.install(app)
            if not owner.start():raise ValueError('signin-only startup not verified')
            receipt['status']='servicing';atomic_json(output/'receipt.json',receipt)
            receipt['signin']=signin.service(app)
            receipt['run_summary']=app._RUN_SUMMARY
            receipt['status']='completed' if receipt['signin'].get('home_verified') else 'needs_ai'
            receipt['finished_at']=datetime.now().astimezone().isoformat()
            atomic_json(output/'receipt.json',receipt)
            print(receipt['status'],str(output/'receipt.json'),flush=True)
            return 0 if receipt['status']=='completed' else 2
    except BaseException as exc:
        receipt.update(status='needs_ai',error=f'{type(exc).__name__}: {exc}',run_summary=app._RUN_SUMMARY)
        atomic_json(output/'receipt.json',receipt);raise
    finally:owner.release()

if __name__=='__main__':raise SystemExit(main())
