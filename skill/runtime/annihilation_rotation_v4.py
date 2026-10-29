"""V3 + actual save-selection variant + mandatory post-first-clear rewards."""
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch
import annihilation_rotation_v1 as v1
from annihilation_rotation_v3 import RuntimePort as PreviousPort
from annihilation_record_selection_v1 import verify
from annihilation_postclear_v2 import service


class RuntimePort(PreviousPort):
    def battle(self, job, stage):
        if self.consumed(stage,job):return 'reviewed_attempt_already_consumed'
        started=datetime.now().astimezone()
        if not self.app.run_maa_copilot(job['path']):return 'start_failed'
        return verify(self,stage,started)


@contextmanager
def boundary(app, port_factory=RuntimePort):
    original=v1.first_clear
    def first_clear(port, summary, **kwargs):
        if not original(port,summary,**kwargs):return False
        stage=summary.get('after',summary.get('before',{})).get('map')
        if not stage:return False
        proof=summary.get('battle_brief')
        claim=service(port,stage,clear_evidence=proof)
        app._RUN_SUMMARY['annihilation_first_clear_rewards']=claim
        if claim.get('status')!='completed':
            summary.update(status='first_clear_rewards_unverified',reason=claim.get('reason'))
            return False
        return True
    with patch.object(v1,'first_clear',first_clear),v1.boundary(app,port_factory):yield
