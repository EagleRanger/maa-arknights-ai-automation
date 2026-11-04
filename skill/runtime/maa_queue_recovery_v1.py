"""A failed queue submission waits in its original owner, not default cleanup."""
from contextlib import contextmanager
from unittest.mock import patch
import maa_queue_process_v3 as previous

BASE = previous.boundary


def readiness(app):
    import uiautomation as ua
    from maa_window_handle_v2 import find
    root = find(ua, app.MAA_PATH)
    if root is None:
        return dict(ok=False, read_only=True, state='maa_window_missing', evidence=[])
    nodes = app._uia_descendants(root)
    links = [n for n in nodes if getattr(n, 'ControlTypeName', '') == 'ButtonControl'
             and 'Link' in str(getattr(n, 'Name', '')) and 'Start' in str(getattr(n, 'Name', ''))
             and bool(getattr(n, 'IsEnabled', False)) and not bool(getattr(n, 'IsOffscreen', True))]
    path = app.shot('maa_queue_recheck_game')
    return dict(ok=len(links) == 1 and app._maa_task_queue_running() is False,
                read_only=True, state='maa_queue_ready' if len(links) == 1 else 'maa_queue_blocked',
                evidence=[str(path)], enabled_visible_start_count=len(links))


@contextmanager
def boundary(app, **kwargs):
    held = [False]
    with BASE(app, **kwargs):
        cleanup = getattr(app, 'cleanup_after_task', None)
        submit = app.run_maa_daily_tasks
        def start(enabled_tasks=None):
            settle = getattr(app, '_maa_daily_settle_initial_update', None)
            if callable(settle):
                # Parent has not started a queue: this is the initial update
                # window. Subsequent reloads never reopen that window.
                if not app._maa_process_exists():
                    app._launch_maa_for_background_control()
                    app.wait(3)
                settle()
            while True:
                result = submit(enabled_tasks=enabled_tasks)
                if result is True:
                    held[0] = False
                    return True
                held[0] = True
                app._RUN_SUMMARY['maa_queue_recovery'] = dict(status='waiting_for_ai',
                    requested_tasks=sorted(enabled_tasks or {'StartUp','Infrast','Recruit','Mall','Award'}),
                    retry_scope='same_unstarted_queue_only', automatic_cleanup=False)
                wait = getattr(app, '_startup_ai_wait', None)
                if not callable(wait):
                    # No invented success/cleanup in an unsupported host.
                    raise RuntimeError('MAA queue failed; preserve scene; AI seam unavailable')
                try:
                    wait('maa_queue_start_failed_preserve_scene', lambda: readiness(app))
                except BaseException as exc:
                    if 'startup_ai_explicit_stop' in str(exc):
                        held[0] = False
                    raise
                app._RUN_SUMMARY['maa_queue_recovery']['status'] = 'rechecked_retry_same_queue'
        def keep_scene(*a, **k):
            if held[0]:
                app.log('[MAA队列恢复] 保留原控制器、游戏、MAA及模拟器，等待AI接回')
                return False
            return cleanup(*a, **k) if cleanup else None
        with patch.object(app, 'run_maa_daily_tasks', start), \
             patch.object(app, 'cleanup_after_task', keep_scene, create=True):
            yield
