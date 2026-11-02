"""Verify import and fresh Core start; an Invoke is not a launched battle.

Keep the existing background UIA route and frozen runtime unchanged. Only
ordinary Copilot starts are wrapped; SSS retains its separately accepted path.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import json
import re
import time


def cursor(path):
    path = Path(path)
    try:
        return {'size': path.stat().st_size, 'at': datetime.now()}
    except FileNotFoundError:
        return {'size': 0, 'at': datetime.now()}


def fresh_text(path, mark):
    """Read only post-cursor records; actual truncation additionally uses time."""
    path = Path(path)
    if not path.exists():
        return ''
    rotated = path.stat().st_size < mark['size']
    with path.open('rb') as fp:
        fp.seek(0 if rotated else mark['size'])
        value = fp.read().decode('utf-8', errors='replace')
    if not rotated:
        return value
    kept = []
    for line in value.splitlines():
        match = re.match(r'\[([0-9T :.-]+)\]', line)
        if match:
            try:
                if datetime.fromisoformat(match[1]) >= mark['at']:
                    kept.append(line)
            except ValueError:
                pass
    return '\n'.join(kept)


def job_identity(path):
    path = Path(path).resolve(strict=True)
    job = json.loads(path.read_text('utf-8-sig'))
    if (not isinstance(job, dict) or not job.get('stage_name')
            or not isinstance(job.get('actions'), list) or not job['actions']):
        raise ValueError('Copilot job identity/actions missing')
    title = str((job.get('doc') or {}).get('title') or '').strip()
    return path, {'stage': job['stage_name'], 'title': title,
                  'operators': len(job.get('opers') or []) + len(job.get('groups') or [])}


def import_status(text, identity):
    lines = [line for line in text.splitlines() if '[CopilotViewModel]' in line]
    value = '\n'.join(lines)
    if any(s in value for s in ('解析作业文件错误', '读取作业文件错误', '未选择作业')):
        return 'rejected'
    # MAA's current parser emits the selected job's title and full roster
    # after it has cached the JSON. The path text alone is not that proof.
    title = identity['title']
    count = re.search(r'共\s*(\d+)\s*名干员', value)
    if (title and any(line.rstrip().endswith(title) for line in lines)
            and count and int(count[1]) == identity['operators']):
        return 'loaded'
    return 'pending'


def core_started(text):
    return any('TaskChainStart ' in line and
               re.search(r'"taskchain"\s*:\s*"Copilot"', line)
               for line in text.splitlines())


def empty_if_unchanged(snapshot, after_line):
    if after_line > 0 and snapshot.get('line_count') == after_line:
        result = deepcopy(snapshot)
        result.update(evidence_text='', structured_text='', tail_text='',
                      activity_chars=0, rotated=False)
        return result
    return snapshot


class Proxy:
    def __init__(self, target):
        self.target = target

    def __getattr__(self, name):
        return getattr(self.target, name)


@contextmanager
def boundary(app):
    original_run = app.run_maa_copilot
    original_prepare = app._prepare_maa_copilot_page
    original_read = app._read_bounded_maa_log
    original_check = app.check_maa_errors
    original_status = app.read_maa_copilot_status
    active = {}

    def bounded(after_line=0, path=None):
        return empty_if_unchanged(original_read(after_line, path), int(after_line or 0))

    def scoped_start_line(after_line):
        if active.get('core_path') == str(app.MAA_LOG) and active.get('started'):
            return min(int(after_line or 0), active['line'])
        return after_line

    def check(after_line=0):
        return original_check(scoped_start_line(after_line))

    def status(after_line=0):
        return original_status(scoped_start_line(after_line))

    def run(path, allow_sss_deploy=False):
        if allow_sss_deploy:
            return original_run(path, allow_sss_deploy=True)
        path, _ = job_identity(path)
        state = {'status': 'preparing', 'source': str(path), 'battle_started': False}
        app._RUN_SUMMARY.setdefault('copilot_start_receipts', []).append(state)
        active.clear()

        class Edit(Proxy):
            def GetValuePattern(self):
                raw = self.target.GetValuePattern()

                class Value(Proxy):
                    def SetValue(self, value):
                        final, identity = job_identity(value)
                        state.update(job=str(final), identity=identity)
                        # One local import recovery is safe: neither attempt
                        # invokes Start or consumes a battle retry.
                        for attempt in (1, 2):
                            if attempt == 2:
                                raw.SetValue('')
                                time.sleep(.25)
                            mark = cursor(app.MAA_GUI_LOG)
                            raw.SetValue(str(final))
                            if str(raw.Value) != str(final):
                                raise RuntimeError('Copilot full-path readback mismatch')
                            deadline = time.monotonic() + 8
                            current = 'pending'
                            while time.monotonic() < deadline:
                                current = import_status(fresh_text(app.MAA_GUI_LOG, mark), identity)
                                if current != 'pending':
                                    break
                                time.sleep(.25)
                            state.update(import_attempt=attempt, import_status=current)
                            if current == 'loaded':
                                app.log('  [MAA作业] 本次标题与干员数已读回，文件解析完成')
                                return
                        state['status'] = 'import_unverified'
                        raise RuntimeError('MAA did not prove selected job parsed; Start not invoked')
                return Value(raw)

        class Start(Proxy):
            def GetInvokePattern(self):
                raw = self.target.GetInvokePattern()

                class Invoke(Proxy):
                    def Invoke(self):
                        if state.get('import_status') != 'loaded':
                            raise RuntimeError('Copilot import not confirmed')
                        mark = cursor(app.MAA_LOG)
                        gui_mark = cursor(app.MAA_GUI_LOG)
                        with open(app.MAA_LOG, encoding='utf-8', errors='replace') as fp:
                            line = sum(1 for _ in fp)
                        raw.Invoke()
                        deadline = time.monotonic() + 20
                        while time.monotonic() < deadline:
                            if core_started(fresh_text(app.MAA_LOG, mark)):
                                active.update(core_path=str(app.MAA_LOG), line=line, started=True)
                                state.update(status='core_started', core_start_line=line,
                                             core_start_verified=True)
                                return
                            gui = fresh_text(app.MAA_GUI_LOG, gui_mark)
                            if any(s in gui for s in ('未选择作业', '解析作业文件错误')):
                                break
                            time.sleep(.25)
                        state['status'] = 'core_start_unverified'
                        raise RuntimeError('MAA button invoked but no fresh TaskChainStart(Copilot)')
                return Invoke(raw)

        def prepare(*args, **kw):
            window, controls = original_prepare(*args, **kw)
            if not controls:
                return window, controls
            edit, formation, start = controls
            return window, (Edit(edit), formation, Start(start))

        with patch.object(app, '_prepare_maa_copilot_page', prepare):
            return original_run(str(path))

    with patch.object(app, 'run_maa_copilot', run), \
         patch.object(app, '_read_bounded_maa_log', bounded), \
         patch.object(app, 'check_maa_errors', check), \
         patch.object(app, 'read_maa_copilot_status', status):
        yield
