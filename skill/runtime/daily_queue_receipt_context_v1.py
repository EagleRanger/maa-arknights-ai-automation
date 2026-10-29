"""Keep parent acceptance context when queue start is isolated in a worker."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


@contextmanager
def boundary(app):
    import daily_base_333_verified_execution_v1 as legacy
    import daily_base_333_verified_execution_v4 as stream
    queue=app.run_maa_daily_tasks;fallback=legacy.verify_infrast_execution
    state={}
    def start(enabled_tasks=None):
        tasks=set(enabled_tasks or {'StartUp','Infrast','Recruit','Mall','Award'})
        app._base333_active_maa_scope=tasks
        state.update(not_before=datetime.now(),tasks=tasks)
        return queue(enabled_tasks=tasks)
    def verify(text,expected,config=legacy.ACTIVE_CONFIG):
        if 'Infrast' not in state.get('tasks',set()):return fallback(text,expected,config)
        path=Path(app.MAA_LOG)
        return stream.verify_from_files([path.with_name('asst.bak.log'),path],state['not_before'],expected,config)
    with patch.object(app,'run_maa_daily_tasks',start),patch.object(legacy,'verify_infrast_execution',verify):
        yield
