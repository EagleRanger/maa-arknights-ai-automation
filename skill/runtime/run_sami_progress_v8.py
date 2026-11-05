"""V7 plus reward reveals and the receiver's existing cooperation protocol."""
from unittest.mock import patch
import run_sami_progress_v7 as previous
import run_sami_progress_v1 as base
import sami_cooperation_v1 as cooperation
from reward_transition_v1 import boundary as rewards
from tools.ark_cooperation_control import process_alive
from pathlib import Path
import hashlib
import json

WORKFLOW='ARK-SAMI-PROGRESS-V8'
# A recipient may adapt event delivery at this seam. The public runtime emits
# the original outbox/recheck protocol without a machine-specific relay.
OwnerControl=cooperation.CooperativeControl


def main():
    import run_sami_until_deadline as sami
    old=sami.run
    old_admit=base.admit
    def admit(*args,**kwargs):
        packet,deadline=old_admit(*args,**kwargs)
        prior=packet.get('previous_reconciliation')
        if prior:
            path=(base.ROOT/prior['path']).resolve();path.relative_to(base.ROOT/'outputs')
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest().upper()!=prior['sha256']:
                raise ValueError('previous_reconciliation_changed')
            proof=json.loads(raw)
            source=(base.ROOT/proof['checkpoint']).resolve();source.relative_to(base.ROOT/'outputs')
            if (proof.get('status')!='controller_lost_reconciled' or proof.get('owner_cleanup_claim') is not False
                    or hashlib.sha256(source.read_bytes()).hexdigest().upper()!=proof['checkpoint_sha256']
                    or process_alive(proof['controller_pid']) is not False):
                raise ValueError('previous_controller_not_reconciled')
        return packet,deadline
    def run(*args,**kwargs):
        with rewards(sami,sami.ark):return old(*args,**kwargs)
    with patch.object(previous,'WORKFLOW',WORKFLOW),patch.object(sami,'run',run),patch.object(base,'admit',admit), \
         patch.object(cooperation,'CooperativeControl',OwnerControl):
        return previous.main()


if __name__=='__main__':raise SystemExit(main())
