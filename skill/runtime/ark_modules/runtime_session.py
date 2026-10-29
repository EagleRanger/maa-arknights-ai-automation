"""One prepared device session: observation, ownership and per-operation audit.

Not a bootstrap or business dispatcher. Original controller lease and manifest
remain the only ownership sources. This module never starts/stops an app.
"""
from collections import deque
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from .core import Result, ReceiptStore


def blocked(reason, **data):
    return Result('blocked', reason, data=dict(data, before_action=True))


class ScopeViolation(RuntimeError):
    pass


@contextmanager
def operation_boundary(app, spec):
    """Limit legacy control flow, never replace native permissions/admission."""
    forbidden = {'main', 'mode_full', 'mode_daily', 'cleanup_after_task',
                 'mode_event', 'mode_resource', 'mode_mainline', 'mode_security'} - set(spec.legacy_modes)
    if spec.read_only:
        forbidden |= {'tap', 'swipe', 'run_maa', 'run_maa_copilot', 'run_maa_daily_tasks'}
    def deny(name):
        def refused(*args, **kwargs):
            raise ScopeViolation(f'{spec.name} cannot call {name}')
        return refused
    with ExitStack() as stack:
        if spec.name == 'daily.exit_tail':
            # Keep the already-admitted queue API, but prevent legacy hooks
            # from appending a Fight/Mall/new daily chain to exit collections.
            forbidden |= {'run_maa_copilot', 'run_maa'}
            original_queue = app.run_maa_daily_tasks
            def collections_only(*args, **kwargs):
                selected = kwargs.get('enabled_tasks')
                if args or not selected or not set(selected) <= {'Infrast', 'Recruit', 'Award'}:
                    raise ScopeViolation('exit tail queue must name collection chains only')
                return original_queue(**kwargs)
            stack.enter_context(patch.object(app, 'run_maa_daily_tasks', collections_only))
        for name in sorted(forbidden):
            if callable(getattr(app, name, None)):
                stack.enter_context(patch.object(app, name, deny(name)))
        yield


class RuntimeSession:
    def __init__(self, runtime, output, *, owns_control, events=(), daily_receipts=None,
                 room_service=None, long_services=None):
        self.app, self.output, self._owns = runtime, Path(output), owns_control
        self.events = {e['name']: deepcopy(e) for e in events}
        self.daily_receipts = daily_receipts if daily_receipts is not None else {}
        self.room_service = room_service
        self.long_services = long_services or {}
        self.base_ready = False
        self.sequence = 0

    def now(self): return datetime.now(timezone.utc)
    def owns_control(self, owner): return self._owns(owner)
    def queue_idle(self): return self.app._maa_task_queue_running() is False
    def event(self, inputs): return self.events.get(inputs.get('event'))

    def proof(self, ok, detail, data, *, tag):
        evidence = (str(self.app.shot('module_' + tag)),) if self.queue_idle() else ()
        return Result('succeeded' if ok and evidence else 'partial', detail, evidence, data)

    def invoke(self, spec, handler, inputs, context, previous):
        required = ('shot', '_maa_task_queue_running', *spec.required)
        missing = [name for name in required if not callable(getattr(self.app, name, None))]
        if missing:
            return blocked('本模块接口尚未接齐，未开始操作', missing_interfaces=missing, operation=spec.name)
        if not self.owns_control(context.owner) or not self.queue_idle():
            return blocked('当前队列/控制权不允许本模块接管')
        self.sequence += 1
        # Multiple assemblies may use one directory. A restarted sequence must
        # never overwrite the old 001-operation evidence.
        target = self.output / f'{self.sequence:03d}_{spec.name.replace(".", "_")}_{uuid4().hex}.json'
        audit = dict(run_id=context.run_id, workflow=context.workflow, operation=spec.name,
                     domain=spec.domain, started_at=self.now().isoformat(), status='running', inputs=deepcopy(inputs))
        ReceiptStore(target).save(audit)
        frames = deque(maxlen=32)
        old_shot = self.app.shot
        def traced_shot(*args, **kwargs):
            path = old_shot(*args, **kwargs)
            frames.append(str(path))
            return path
        try:
            with patch.object(self.app, 'shot', traced_shot), operation_boundary(self.app, spec):
                result = handler(self, deepcopy(inputs), context, dict(previous), spec.name)
            if not isinstance(result, Result): raise TypeError('typed module result required')
        except (KeyboardInterrupt, SystemExit):
            audit.update(status='interrupted', finished_at=self.now().isoformat(), needs_reconciliation=True,
                         evidence=list(frames))
            ReceiptStore(target).save(audit)
            raise
        except Exception as exc:
            # It may have failed after a legitimate effect: never allow replay.
            result = Result('unknown', f'{type(exc).__name__}: {exc}',
                            data={'reconciliation_required': True, 'scope_violation': isinstance(exc, ScopeViolation)})
        result = Result(result.status, result.detail, tuple(dict.fromkeys([*result.evidence, *frames])), result.data)
        audit.update(finished_at=self.now().isoformat(), result=asdict(result), status=result.status)
        ReceiptStore(target).save(audit)
        return Result(result.status, result.detail, result.evidence,
                      dict(result.data, audit=str(target), run_id=context.run_id))
