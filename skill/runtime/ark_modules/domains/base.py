"""Independent base operations. Return results; never advance or close a day."""
from copy import deepcopy
from pathlib import Path
import hashlib
from ..core import Result
from ..runtime_session import blocked


def prepare_base(session, inputs, context, previous, operation):
    raw = session.app.prepare_dynamic_333_base()
    row = deepcopy(session.app._RUN_SUMMARY.get('base_333') or {})
    session.base_ready = raw is True and base_config_current(row)
    return session.proof(session.base_ready, '基建方案准备完毕，实际产线与轮班由Infrast后验收', row, tag='base_plan')


def base_config_current(row):
    try:
        return (row.get('config_readback') is True and bool(row.get('config_sha256'))
                and hashlib.sha256(Path(row['config']).read_bytes()).hexdigest().lower()
                == row['config_sha256'].lower())
    except (OSError, KeyError, TypeError, ValueError):
        return False


def rooms(session, inputs, context, previous, operation):
    if session.room_service is None:
        return blocked('活动室完整服务尚未绑定；无人机仍全额预留，不影响其它日常')
    return session.room_service(session.app, session.output/'rooms', context)


def drones(session, inputs, context, previous, operation):
    from ..base import use_drones
    policy = dict(inputs)
    room_result = previous.get('rooms')
    if room_result and room_result.data.get('final'):
        # Prefer this run's full observation over the compiled snapshot.
        current = room_result.data['final']
        policy.update(rooms=current.get('rooms'), rooms_complete=current.get('complete', False))
    return use_drones(session.app, session.output/'drones', target=inputs.get('target'),
                      activity_rooms=policy.get('rooms'), rooms_complete=policy.get('rooms_complete', False), now=session.now())
