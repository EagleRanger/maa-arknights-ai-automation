"""Outer host: shared bootstrap and explicit instance closeout.

No schedule, policy, activity choice, report or daily tail lives here. Callers
perform existing project admission first. Single workers never receive this
object, so only the outer caller can start or close the owned environment.
"""
import subprocess


BOOT_INTERFACES = ('_resolve_mumu_vm_index', 'detect_mumu_adb_port', '_run_mumu',
                   'ensure_env', '_runtime_dependencies_ready', '_maa_task_queue_running')
INSTANCE_IMAGES = ('MAA.exe', 'MuMuNxMain.exe', 'MuMuNxDevice.exe',
                   'MuMuVMMHeadless.exe', 'MuMuPlayer.exe', 'adb.exe')


def require_interfaces(app, extra=()):
    missing = [name for name in (*BOOT_INTERFACES, *extra) if not callable(getattr(app, name, None))]
    if missing:
        raise ValueError('prepared runtime interface missing: ' + ','.join(missing))


def prepare(app):
    # V12 and the old VEC facade have different instance-resolution interfaces.
    # Check before installing anything, not after trying to launch an emulator.
    require_interfaces(app)
    from maa_portable_runtime_v1 import bind
    from vector_environment_startup_v1 import install
    bind(app)
    install(app)
    app.SCRIPT_SCREENSHOT_BACKEND = 'adb'
    return app


class EnvironmentOwner:
    def __init__(self, app, *, owner, clock, deadline, prepare_runtime=prepare, process_run=subprocess.run,
                 before_close=None):
        self.app, self.owner, self.clock, self.deadline = app, owner, clock, deadline
        self.prepare_runtime, self.process_run = prepare_runtime, process_run
        self.acquired = False
        self.start_attempted = False
        self.ready = False
        self._close_receipt = None
        self.before_close, self._tail_receipt = before_close, None

    def owns(self, owner=None):
        return (self.acquired and bool(self.app._RUN_MUTEX_HANDLE)
                and (owner is None or owner == self.owner))

    def acquire(self):
        if self.acquired:
            return self.owns()
        if self.clock() >= self.deadline:
            raise RuntimeError('deadline reached before environment acquisition')
        self.acquired = self.app.acquire_single_instance() is True
        if not self.acquired:
            raise RuntimeError('another controller owns environment')
        return True

    def start(self):
        if self._close_receipt is not None:
            raise RuntimeError('environment already closed; no implicit reopen')
        if self.start_attempted:
            return self.ready  # No second boot after an uncertain first attempt.
        if not self.owns() or self.clock() >= self.deadline:
            raise RuntimeError('controller/deadline boundary reached')
        if self.app._maa_task_queue_running() is not False:
            raise RuntimeError('queue not idle before bootstrap')
        self.start_attempted = True
        self.prepare_runtime(self.app)
        self.ready = self.app._runtime_dependencies_ready() is True and self.app.ensure_env() is True
        return self.ready

    def close(self):
        if self._close_receipt is not None:
            return dict(self._close_receipt, reused=True)
        if not self.owns() or self.app._maa_task_queue_running() is not False:
            return {'verified': False, 'status': 'deferred', 'reason': 'queue or ownership changed; not stopped'}
        if self.ready and self.before_close is not None and self._tail_receipt is None:
            self._tail_receipt = {'status': 'running'}
            try:
                self._tail_receipt = self.before_close()
                if not isinstance(self._tail_receipt, dict):
                    raise TypeError('exit tail receipt required')
            except Exception as exc:
                self._tail_receipt = {'status': 'unknown', 'error': str(exc)}
        # The tail may have started a queue. Never kill it underneath the worker.
        if not self.owns() or self.app._maa_task_queue_running() is not False:
            return {'verified': False, 'status': 'deferred', 'exit_tail': self._tail_receipt,
                    'reason': 'exit tail still owns queue'}
        # An interrupted close cannot silently run badge collection or repeat
        # another full cleanup. The caller persists its own before/after state.
        self._close_receipt = {'verified': False, 'status': 'running', 'needs_reconciliation': True}
        try:
            self.app.cleanup_after_task(check_badges=False)
            stop = self.process_run([self.app.ADB, 'kill-server'], capture_output=True, text=True, timeout=15)
            remaining = self.app._running_process_images(INSTANCE_IMAGES)
            self._close_receipt = {'verified': remaining == [], 'status': 'returned',
                                   'remaining': remaining, 'adb_stop_returncode': stop.returncode}
        except Exception as exc:
            self._close_receipt = {'verified': False, 'status': 'unknown', 'error': str(exc),
                                   'needs_reconciliation': True}
        self._close_receipt['exit_tail'] = self._tail_receipt
        return dict(self._close_receipt)

    def finish_session(self, context, output, *, drone_policy=None, previous_collection=None):
        """Normal user-requested exit, distinct from emergency/restricted close.

        Run new pending collections once, then close. A completed single
        operation never calls this implicitly. Caller admission covers the
        exit policy; historical reward-only packets retain their old scope.
        """
        from .closeout import finish_session
        return finish_session(self, context, output, drone_policy=drone_policy,
                              previous_collection=previous_collection)

    def release(self):
        if not self.acquired:
            return True
        if self.app._maa_task_queue_running() is not False:
            return False  # Never advertise the device as free while its queue runs.
        self.app.release_single_instance()
        self.acquired = False
        return True
