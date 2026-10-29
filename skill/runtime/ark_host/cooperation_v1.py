"""Caller-owned pause/recheck protocol; no scheduler, game input or AI code execution.

The existing execution chat relays ARK_NEEDS_ATTENTION through native tools.
Writing an outbox is NOT proof that a chat received it. The host keeps its
deadline while waiting, even when delivery or the reply never arrives.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

from event_page_guard_v1 import publish_page_attention


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def read_message(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class ControlExit(RuntimeError):
    """The caller must execute its normal owned cleanup, not restart the task."""


class CooperativeControl:
    def __init__(self, *, run_id, output, event_output, deadline, queue_idle,
                 save, clock=time.time, sleep=time.sleep, emit=print,
                 cleanup_buffer=90, poll_seconds=2, observe=None):
        self.run_id, self.output = run_id, Path(output)
        self.event_output = Path(event_output)
        self.deadline = float(deadline)
        self.queue_idle, self.save = queue_idle, save
        self.clock, self.sleep, self.emit = clock, sleep, emit
        self.cleanup_buffer, self.poll_seconds = cleanup_buffer, poll_seconds
        self.state = {}
        self.sequence = 0
        self.used_requests = set()
        self.used_replies = set()
        self.exit_reason = None
        self.waiting = False
        self.stop_pending = False
        self.pause_pending = False
        self.observe = observe

    def check_deadline(self):
        if self.clock() >= self.deadline - self.cleanup_buffer:
            self.exit_reason = 'deadline_stopped'
            raise ControlExit('到达收尾时间；等待AI不能延长运行截止')

    def _idle(self):
        try:
            return self.queue_idle() is True
        except Exception:
            return False

    def _save(self):
        self.state['controller_pid'] = os.getpid()
        self.state['updated_at'] = datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()
        try:
            self.save(self.state)
        except Exception as exc:
            # Storage/feedback failure must not take the deadline owner down.
            self.state.setdefault('cooperation', {})['checkpoint_write_error'] = f'{type(exc).__name__}: {exc}'

    def _request(self):
        request = read_message(self.output / 'control_request.json')
        key = request.get('request_id')
        if (request.get('run_id') != self.run_id or not isinstance(key, str)
                or not key or key in self.used_requests):
            return None
        if request.get('action') not in {'pause_at_boundary', 'stop_at_boundary'}:
            return None
        self.used_requests.add(key)
        return request

    def before_next_round(self, verify):
        """Called by the single owner BEFORE starting Core, never racing its GUI."""
        self.check_deadline()
        request = self._request()
        if not request and not self.pause_pending:
            return
        if request and request['action'] == 'stop_at_boundary':
            self.exit_reason = 'requested_stop'
            raise ControlExit('按请求在整轮边界收口')
        self.pause_pending = False
        self.wait_for_repair('before_next_round', {'reason': 'pause_requested'}, verify)

    def wait_for_repair(self, phase, failure, verify):
        self.check_deadline()
        self.sequence += 1
        failure = dict(failure)
        if self.observe is not None and self._idle():
            try:
                failure['observation'] = self.observe()
            except Exception as exc:
                failure['observation_error'] = f'{type(exc).__name__}: {exc}'
        self.check_deadline()
        reason = str(failure.get('reason') or 'step_unverified')
        # A new failed attempt gets a new incident; an old reply cannot replay it.
        incident_reason = f'cooperation:{self.sequence}:{reason}'
        identity = json.dumps([self.run_id, phase, incident_reason], ensure_ascii=False)
        event_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]
        path = self.event_output / 'event_page_attention' / (event_id + '.json')
        event = dict(event_id=event_id, delivery_status='pending', needs_attention=True)
        storage_error = None
        try:
            path = Path(publish_page_attention(
                self.event_output, self.run_id, phase, incident_reason,
                [{'state': phase, 'failure': failure}]))
            event.update(read_message(path))
        except Exception as exc:
            storage_error = f'{type(exc).__name__}: {exc}'
        event.update(source='ark_host.cooperation_v1', run_id=self.run_id,
                     status='waiting_for_ai', phase=phase,
                     checkpoint=str(self.output / 'checkpoint.json'),
                     response_path=str(self.output / 'ai_response.json'),
                     deadline=self.deadline, cleanup_buffer=self.cleanup_buffer,
                     allowed_responses=['recheck', 'stop'],
                     controller_kept_alive=True, retry_battle_allowed=False)
        try:
            atomic_json(path, event)
        except Exception as exc:
            storage_error = f'{type(exc).__name__}: {exc}'
        old_status = self.state.get('status', 'preparing')
        self.state.update(status='waiting_for_ai', cooperation={
            'event_id': event['event_id'], 'event_path': str(path), 'phase': phase,
            'failure': failure, 'status': 'waiting_for_ai',
            'deadline_guard_active': True, 'cleanup_requested': False})
        if storage_error:
            self.state['cooperation']['outbox_write_error'] = storage_error
        self.waiting = True
        self._save()
        notice = dict(event_id=event['event_id'], run_id=self.run_id, phase=phase,
                      reason=reason, event_path=str(path), response_path=event['response_path'],
                      controller_pid=os.getpid(), checkpoint=str(self.output / 'checkpoint.json'))
        # Flushed now, not after cleanup; native exec wait can surface it promptly.
        try:
            self.emit('ARK_NEEDS_ATTENTION ' + json.dumps(notice, ensure_ascii=False), flush=True)
        except Exception as exc:
            self.state['cooperation']['notification_error'] = type(exc).__name__
        try:
            while True:
                self.check_deadline()
                request = self._request()
                if request and request['action'] == 'stop_at_boundary':
                    self.stop_pending = True
                elif request and request['action'] == 'pause_at_boundary':
                    # A pause arriving during another repair wait still applies
                    # to the NEXT round; consuming its id must not discard it.
                    self.pause_pending = True
                if self.stop_pending and self._idle():
                    self.exit_reason = 'requested_stop'
                    raise ControlExit('等待期间收到收口请求')
                reply = read_message(self.output / 'ai_response.json')
                key = reply.get('response_id')
                valid = (reply.get('run_id') == self.run_id
                         and reply.get('event_id') == event['event_id']
                         and isinstance(key, str) and bool(key)
                         and key not in self.used_replies
                         and reply.get('action') in {'recheck', 'stop'})
                if valid and self._idle():
                    self.used_replies.add(key)
                    self.state['cooperation']['last_response_id'] = key
                    if reply['action'] == 'stop':
                        self.exit_reason = 'requested_stop'
                        raise ControlExit('按本次问题回复收口；未完成业务仍保留')
                    try:
                        result = verify()  # Must be a fresh, read-only observation.
                    except Exception as exc:
                        result = {'ok': False, 'reason': f'{type(exc).__name__}: {exc}'}
                    self.check_deadline()
                    self.state['cooperation']['recheck'] = result
                    # Reply text/AI confidence alone never clears a failed step.
                    if (result.get('ok') is True and result.get('read_only') is True
                            and result.get('evidence') and self._idle()):
                        self.state['status'] = old_status
                        self.state['cooperation']['status'] = 'rechecked_resume_same_step'
                        self._save()
                        return result
                self._save()
                self.sleep(min(self.poll_seconds,
                               max(0, self.deadline - self.cleanup_buffer - self.clock())))
        finally:
            self.waiting = False

    def step(self, phase, operation, verify):
        """Retry ONLY this reconciled stage; successful previous stages stay done."""
        if self.waiting:
            raise RuntimeError('nested cooperation wait is not allowed')
        while True:
            self.check_deadline()
            try:
                result = operation()
            except ControlExit:
                raise
            except Exception as exc:
                result = {'ok': False, 'reason': f'{type(exc).__name__}: {exc}'}
            if isinstance(result, dict) and result.get('ok') is True:
                return result
            failure = result if isinstance(result, dict) else {'reason': 'invalid_step_result'}
            self.wait_for_repair(phase, failure, verify)


def write_reply(output, *, run_id, event_id, response_id, action):
    """Local command reply, never a shell command or arbitrary Python patch."""
    if action not in {'recheck', 'stop'} or not all((run_id, event_id, response_id)):
        raise ValueError('invalid cooperation reply')
    atomic_json(Path(output) / 'ai_response.json', dict(
        run_id=run_id, event_id=event_id, response_id=response_id, action=action))
