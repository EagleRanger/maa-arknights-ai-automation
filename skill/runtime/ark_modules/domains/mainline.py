"""Independent mainline operations. Return results; never advance or close a day."""
from copy import deepcopy
from ..core import Result
from ..runtime_session import blocked


def mainline(session, inputs, context, previous, operation):
    if not inputs.get('stage') or not inputs.get('max_attempts'):
        return blocked('只允许明确的新主线单关及原预算，不自动扫描旧章节')
    if inputs.get('layer') not in ('normal', 'hard'):
        return blocked('该主线特殊层尚未绑定独立验收适配，不以普通模式替代')
    raw = session.app.mode_mainline(target_stage=inputs['stage'], target_max_attempts=inputs['max_attempts'])
    row = deepcopy(session.app._RUN_SUMMARY.get('mainline') or {})
    # Exact-layer recognition is supplied by the admitted task-specific
    # worker. A truthy generic return is deliberately insufficient here.
    ok = (row.get('target') == inputs['stage'] and row.get('layer') == inputs.get('layer')
          and row.get('game_clear_verified') is True and bool(row.get('evidence')))
    return Result('succeeded' if ok else 'partial', '主线目标层已核验' if ok else '主线单关回执需补层次核验',
                  (str(row['evidence']),) if row.get('evidence') else (), dict(row, worker_return=raw))
