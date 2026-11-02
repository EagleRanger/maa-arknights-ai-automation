"""Revalidate asynchronous MAA import at Start, with three preparation rounds.

A preview may load and then be invalidated before Start. This is not a battle
failure. Retry only while no Core start exists; ambiguous starts never replay.
"""
from contextlib import contextmanager
from unittest.mock import patch
import re
import time

from copilot_start_receipt_v1 import (
    Proxy, core_started, cursor, empty_if_unchanged, fresh_text, job_identity,
)

MAX_PREPARATION_ROUNDS = 3


def latest_import_status(text, identity):
    lines = [s for s in text.splitlines() if '[CopilotViewModel]' in s]
    # Only a complete preview AFTER the last invalidation can supersede it.
    invalid = [i for i, s in enumerate(lines) if any(x in s for x in
               ('解析作业文件错误', '读取作业文件错误', '未选择作业'))]
    last = invalid[-1] if invalid else -1
    rows = lines[last + 1:]
    title_positions = [i for i, s in enumerate(rows) if identity['title'] and
                       s.rstrip().endswith(identity['title'])]
    if title_positions:
        for s in rows[title_positions[-1] + 1:]:
            count = re.search(r'共\s*(\d+)\s*名干员', s)
            if count and int(count[1]) == identity['operators']:
                return 'loaded'
    return 'rejected' if invalid else 'pending'


def rejected_and_idle(text):
    return ('未选择作业' in text and
            ('Idle: false to true' in text or '已停止' in text))


class ImportSession:
    def __init__(self, app, edit, start, state, active):
        self.app, self.edit, self.start = app, edit, start
        self.state, self.active = state, active
        self.path = self.identity = self.mark = None
        self.rounds = 0

    def current(self):
        if self.mark is None:
            return 'pending'
        if str(self.edit.Value or '') != str(self.path):
            return 'path_changed'
        return latest_import_status(fresh_text(self.app.MAA_GUI_LOG, self.mark), self.identity)

    def load(self, value):
        self.path, self.identity = job_identity(value)
        self.state.update(job=str(self.path), identity=self.identity)
        return self.ensure_loaded(force=True)

    def ensure_loaded(self, force=False):
        if not force and self.current() == 'loaded':
            return
        outcome = self.current()
        while self.rounds < MAX_PREPARATION_ROUNDS:
            self.rounds += 1
            if self.rounds > 1:
                self.edit.SetValue('')
                time.sleep(.25)
            self.mark = cursor(self.app.MAA_GUI_LOG)
            self.edit.SetValue(str(self.path))
            deadline = time.monotonic() + 8
            stable_since, last_text = None, None
            outcome = 'pending'
            while time.monotonic() < deadline:
                text = fresh_text(self.app.MAA_GUI_LOG, self.mark)
                outcome = self.current()
                if outcome in ('rejected', 'path_changed'):
                    break
                if outcome == 'loaded':
                    if text != last_text:
                        stable_since = time.monotonic()
                    elif stable_since is not None and time.monotonic() - stable_since >= 1:
                        self.state.update(import_attempt=self.rounds, import_status='loaded')
                        self.app.log(f'  [MAA作业] 第{self.rounds}/3轮导入稳定，启动前仍会重新核验')
                        return
                last_text = text
                time.sleep(.25)
            self.state.setdefault('import_recoveries', []).append(
                dict(round=self.rounds, result=outcome, battle_retry=False))
        self.state.update(status='import_unverified', import_attempt=self.rounds,
                          import_status=outcome)
        raise RuntimeError('MAA import not stable after 3 preparation rounds; Start not invoked')

    def invoke(self):
        while True:
            # Includes GUI changes caused after SetValue (settling / checkbox).
            self.ensure_loaded()
            mark, gui_mark = cursor(self.app.MAA_LOG), cursor(self.app.MAA_GUI_LOG)
            with open(self.app.MAA_LOG, encoding='utf-8', errors='replace') as fp:
                line = sum(1 for _ in fp)
            # One last read immediately before effect, not the earlier preview.
            if self.current() != 'loaded':
                self.ensure_loaded(force=True)
                continue
            self.start.Invoke()
            self.state['start_invocations'] = self.state.get('start_invocations', 0) + 1
            deadline = time.monotonic() + 20
            rejected = False
            while time.monotonic() < deadline:
                if core_started(fresh_text(self.app.MAA_LOG, mark)):
                    self.active.update(core_path=str(self.app.MAA_LOG), line=line, started=True)
                    self.state.update(status='core_started', battle_started=True,
                                      core_start_line=line, core_start_verified=True)
                    return
                rejected = rejected_and_idle(fresh_text(self.app.MAA_GUI_LOG, gui_mark))
                if rejected:
                    break
                time.sleep(.25)
            # Settle asynchronous Core delivery without another action.
            if rejected:
                time.sleep(.5)
                if core_started(fresh_text(self.app.MAA_LOG, mark)):
                    self.active.update(core_path=str(self.app.MAA_LOG), line=line, started=True)
                    self.state.update(status='core_started', battle_started=True,
                                      core_start_line=line, core_start_verified=True)
                    return
            if rejected and self.rounds < MAX_PREPARATION_ROUNDS:
                self.state.setdefault('import_recoveries', []).append(
                    dict(round=self.rounds, result='start_rejected_idle', battle_retry=False))
                self.ensure_loaded(force=True)
                continue
            self.state['status'] = 'core_start_unverified'
            raise RuntimeError('MAA no fresh Core start; ambiguous start is not retried')


@contextmanager
def boundary(app):
    original_run, original_prepare = app.run_maa_copilot, app._prepare_maa_copilot_page
    original_read, original_check, original_status = (
        app._read_bounded_maa_log, app.check_maa_errors, app.read_maa_copilot_status)
    active = {}

    def scoped(after_line):
        if active.get('core_path') == str(app.MAA_LOG) and active.get('started'):
            return min(int(after_line or 0), active['line'])
        return after_line

    def run(path, allow_sss_deploy=False):
        if allow_sss_deploy:
            return original_run(path, allow_sss_deploy=True)
        path, _ = job_identity(path)
        state = dict(status='preparing', source=str(path), battle_started=False,
                     max_preparation_rounds=MAX_PREPARATION_ROUNDS)
        app._RUN_SUMMARY.setdefault('copilot_start_receipts', []).append(state)
        active.clear()

        def prepare(*args, **kw):
            window, controls = original_prepare(*args, **kw)
            if not controls:
                return window, controls
            edit, formation, start = controls
            raw_edit, raw_start = edit.GetValuePattern(), start.GetInvokePattern()
            session = ImportSession(app, raw_edit, raw_start, state, active)

            class Value(Proxy):
                def SetValue(self, value):
                    session.load(value)

            class Edit(Proxy):
                def GetValuePattern(self):
                    return Value(raw_edit)

            class Invoke(Proxy):
                def Invoke(self):
                    session.invoke()

            class Start(Proxy):
                def GetInvokePattern(self):
                    return Invoke(raw_start)

            return window, (Edit(edit), formation, Start(start))

        with patch.object(app, '_prepare_maa_copilot_page', prepare):
            return original_run(str(path))

    with patch.object(app, 'run_maa_copilot', run), \
         patch.object(app, '_read_bounded_maa_log', lambda after_line=0, path=None:
                      empty_if_unchanged(original_read(after_line, path), int(after_line or 0))), \
         patch.object(app, 'check_maa_errors', lambda after_line=0: original_check(scoped(after_line))), \
         patch.object(app, 'read_maa_copilot_status', lambda after_line=0: original_status(scoped(after_line))):
        yield
