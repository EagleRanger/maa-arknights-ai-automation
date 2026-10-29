"""Independent weekly operations. Return results; never advance or close a day."""
from ..core import Result
from ..runtime_session import blocked


def weekly(session, inputs, context, previous, operation):
    session.app._run_full_annihilation_step()
    if not session.queue_idle(): return Result('unknown', '剿灭队列未结束，未接管')
    progress = session.app._read_terminal_annihilation_weekly_progress()
    ok = (isinstance(progress, tuple) and len(progress) == 2
          and progress[1] > 0 and progress[0] >= progress[1])
    return session.proof(ok, '剿灭周上限实读完成' if ok else '剿灭周上限尚未核验',
                      {'weekly_progress': progress}, tag='weekly')
