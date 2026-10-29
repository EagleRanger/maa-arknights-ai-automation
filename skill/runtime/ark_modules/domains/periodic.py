"""Independent periodic operations. Return results; never advance or close a day."""
from copy import deepcopy
from ..core import Result
from ..runtime_session import blocked


def sss(session, inputs, context, previous, operation):
    from sss_cycle_skip_v1 import _security_is_complete
    session.app.mode_security()
    row = deepcopy(session.app._RUN_SUMMARY.get('security') or {})
    ok = _security_is_complete(row)
    return session.proof(ok, '本周期保全各奖励域已核验' if ok else '本周期保全仍有未核验奖励域', row, tag='sss')
