"""Caller-owned, read-only battle evidence and optional proposal interface.

Uses the existing cross-theme parser/ranking. Never injects input, loads a
second MaaCore controller, stops a queue, or applies a strategy proposal.
"""
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch
import json
import os
import re
import subprocess
import time

import phantom_collapse_tracking as parser
import roguelike_collapse_tracking as tracking
from ark_host.cooperation_v1 import atomic_json
from event_page_guard_v1 import publish_page_attention

SCHEMA = 'roguelike-battle-review-v1'
SIGNALS = ('Assistant::append_callback |', 'best oper is ', 'best deploy is ',
           'Swipe with scaled coordinates', 'Kills:', 'The best match is { name:',
           'use_air_defense ', 'BattleHelper::deploy_oper | enter',
           ' is not in ALL deploy plan.')


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest().upper()


def open_shared(path):
    if os.name != 'nt':
        return Path(path).open('rb')
    # Python's ordinary open denies deletion on Windows; holding that handle
    # would prevent MaaCore from renaming asst.log during its normal rotation.
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW(str(Path(path).resolve()), 0x80000000, 7, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    return os.fdopen(descriptor, 'rb')


class LogCursor:
    """Incremental complete lines, including unread bytes of a renamed log."""
    def __init__(self, path):
        self.path = Path(path)
        self.stream = open_shared(self.path) if self.path.exists() else None
        self.offset = self.stream.seek(0, 2) if self.stream else 0
        self.pending = b''

    def read(self):
        data = b''
        if self.stream:
            data = self.stream.read()
            current = self.path.stat() if self.path.exists() else None
            opened = os.fstat(self.stream.fileno())
            changed = current and (current.st_ino != opened.st_ino or current.st_size < self.stream.tell())
            if changed:
                self.stream.close()
                self.stream = open_shared(self.path)
                data += self.stream.read()
        elif self.path.exists():
            self.stream = open_shared(self.path)
            data = self.stream.read()
        data = self.pending + data
        lines = data.split(b'\n')
        self.pending = lines.pop()
        return [line.decode('utf-8', errors='replace') for line in lines]

    def close(self):
        if self.stream:
            self.stream.close()


def capture_adb(app, target):
    """Screencap only; app.shot may open another Core bridge and is not used."""
    result = subprocess.run([app.ADB, '-s', app.DEVICE, 'exec-out', 'screencap', '-p'],
        capture_output=True, timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('adb_capture_not_png')
    from PIL import Image
    import io
    with Image.open(io.BytesIO(result.stdout)) as image:
        image.verify()
    Path(target).write_bytes(result.stdout)
    return str(target)


def proposal_check(proposal, evidence):
    """A proposal is data, not executable Python/shell or permission to apply."""
    required = ('schema', 'theme', 'difficulty_bucket', 'stage', 'account_key', 'baseline_sha256')
    errors = [key for key in required if proposal.get(key) != evidence.get(key)]
    if not isinstance(proposal.get('changes'), list) or not proposal['changes']:
        errors.append('changes')
    if not proposal.get('rationale') or not proposal.get('validation_plan') or not proposal.get('rollback'):
        errors.append('review_fields')
    if any(key in proposal for key in ('command', 'shell', 'python', 'exec')):
        errors.append('executable_payload')
    return dict(ok=not errors, errors=errors, applied=False, status='review_required')


class BattleWatch:
    def __init__(self, *, app, root, output, run_id, theme, params, account_key,
                 pid=None, clock=time.monotonic, capture=capture_adb, proposal_hook=None):
        self.app, self.root, self.output = app, Path(root), Path(output)
        self.run_id, self.theme, self.params = run_id, tracking.normalize_theme(theme), dict(params)
        self.account_key = str(account_key)
        self.pid, self.clock, self.capture = pid or os.getpid(), clock, capture
        self.proposal_hook = proposal_hook
        # Account-scoped facts never borrow another account's historical risk.
        key = sha256(self.account_key.encode()).hexdigest()[:24]
        self.ledger_path = self.root / 'runtime_state/accounts' / key / (
            'roguelike_collapse_' + self.theme.lower() + '_mode_' + str(params.get('mode', 'unknown')) + '.json')
        self.folder = self.output / 'battle_watch' / ('core_' + str(time.time_ns()))
        self.folder.mkdir(parents=True, exist_ok=True)
        self.evidence = self.folder / ('core_' + str(time.time_ns()) + '.log')
        self.lines, self.started, self.captures = [], False, []
        self.focus, self.active, self.last_capture, self.capture_counts = {}, None, {}, {}
        self.last_signature = None
        self.warnings = []
        self.summary = tracking.build_summary([])
        if self.ledger_path.exists():
            self.summary = tracking._load(self.ledger_path, self.theme).get('summary') or self.summary
        self._focus()

    def _focus(self):
        self.focus = {row['stage']: row for row in self.summary['optimization_candidates']}

    def feed(self, lines, *, allow_capture=True):
        """PID + real TaskChainStart bind this stream; pre-run saves stay out."""
        changed = False
        for line in lines:
            if f'[Px{self.pid}]' not in line:
                continue
            if 'TaskChainStart' in line and '"taskchain":"Roguelike"' in line:
                self.started = True
            if not self.started or not any(signal in line for signal in SIGNALS):
                continue
            self.lines.append(line)
            callback = parser._callback(line) or {}
            what = callback.get('what')
            if what == 'StageInfo':
                details = callback.get('details') or {}
                self.active = dict(name=details.get('name'), seen_at=parser._timestamp(line))
            if what in ('RoguelikeCombatEnd', 'RoguelikeSettlement') or any(
                    marker in line for marker in ('TaskChainError', 'TaskChainStopped', 'TaskChainCompleted', 'AllTasksCompleted')):
                self.active = None
            changed = True
        if changed:
            self.evidence.write_text('\n'.join(self.lines) + '\n', encoding='utf-8')
            self._record()
        if allow_capture:
            self.maybe_capture()

    def _record(self):
        parsed = parser.parse_run_log('\n'.join(self.lines), source=str(self.evidence), run_context=dict(
            theme=self.theme, run_id=self.run_id, account_key=self.account_key,
            mode=self.params.get('mode'), maa_params=self.params))
        ledger = tracking._load(self.ledger_path, self.theme)
        known = {tracking._outcome_key(row) for row in ledger['outcomes']}
        for row in parsed['outcomes']:
            stages = row.get('stage_sequence') or []
            if any((s.get('behavior_signals') or {}).get('task_chain_error_seen') for s in stages):
                continue
            if tracking._is_reviewable(row) and tracking._outcome_key(row) not in known:
                frozen = self.folder / ('settlement_' + row['event_id'] + '.log')
                frozen.write_text('\n'.join(self.lines) + '\n', encoding='utf-8')
                row['source_evidence'] = dict(path=str(frozen), sha256=digest(frozen))
                ledger['outcomes'].append(row)
                known.add(tracking._outcome_key(row))
        self.summary = ledger['summary'] = tracking.build_summary(ledger['outcomes'])
        ledger.update(account_key=self.account_key, updated_at=datetime.now().astimezone().isoformat())
        signature = sha256(json.dumps(ledger['outcomes'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if signature != self.last_signature:
            tracking._write(self.ledger_path, ledger)
            self.last_signature = signature
        self._focus()
        self._save()

    def maybe_capture(self):
        if not self.active or self.active['name'] not in self.focus:
            return
        row = self.focus[self.active['name']]
        # Current difficulty may not be known until settlement: only capture,
        # never attribute an outcome to that inferred bucket.
        key = (self.active['name'], self.active['seen_at'])
        now = self.clock()
        if self.capture_counts.get(key, 0) >= 6 or now - self.last_capture.get(key, -1e9) < 30:
            return
        self.last_capture[key] = now
        try:
            safe = re.sub(r'[^\w-]', '_', self.active['name'])[:60]
            target = self.folder / f'{safe}_{time.time_ns()}.png'
            path = self.capture(self.app, target)
            self.captures.append(dict(stage=key[0], stage_seen_at=key[1], screenshot=str(path),
                sha256=digest(path), captured_at=datetime.now().astimezone().isoformat(),
                risk_bucket=row['difficulty_bucket'], difficulty_at_capture='not_inferred'))
            self.capture_counts[key] = self.capture_counts.get(key, 0) + 1
            ledger = tracking._load(self.ledger_path, self.theme)
            ledger.setdefault('focus_stage_captures', []).append(self.captures[-1])
            tracking._write(self.ledger_path, ledger)
            self._save()
        except Exception as exc:
            self.warnings.append('capture:' + str(exc))

    def _save(self):
        atomic_json(self.folder / 'status.json', dict(schema=SCHEMA, run_id=self.run_id,
            theme=self.theme, account_key=self.account_key, enabled=True, read_only=True,
            strategy_apply_enabled=False, started=self.started, active_stage=self.active,
            ledger=str(self.ledger_path), summary=self.summary, captures=self.captures,
            evidence=str(self.evidence), warnings=self.warnings[-8:]))

    def finish(self):
        """Called only after Core returns; publish reviews without pausing EXP."""
        if self.lines:
            self._record()
        baseline = sha256(json.dumps(self.params, sort_keys=True, ensure_ascii=False).encode()).hexdigest().upper()
        reviews = []
        for row in self.summary['optimization_candidates']:
            key = sha256((self.theme + '|' + row['difficulty_bucket'] + '|' + row['stage']).encode()).hexdigest()[:20]
            ledger = tracking._load(self.ledger_path, self.theme)
            captures = [p for p in ledger.get('focus_stage_captures', [])
                        if p['stage'] == row['stage'] and Path(p['screenshot']).exists()][-18:]
            review = dict(schema=SCHEMA, theme=self.theme, difficulty_bucket=row['difficulty_bucket'],
                stage=row['stage'], account_key=self.account_key, run_id=self.run_id,
                baseline_sha256=baseline, current_maa_parameters=self.params,
                statistics=row, captures=captures, evidence=dict(path=str(self.evidence), sha256=digest(self.evidence)),
                hook='post_settlement_strategy_proposal', apply_enabled=False,
                allowed_output='reviewable_proposal_only', blocks_experience=False)
            path = self.folder / ('review_' + key + '.json')
            atomic_json(path, review)
            current = self.ledger_path.parent / 'battle_reviews' / ('review_' + key + '.json')
            atomic_json(current, review)
            # The original outbox deduplicates one account/theme/bucket/stage.
            event = publish_page_attention(self.root/'outputs', 'roguelike-review:' + self.account_key + ':' + baseline,
                self.theme + '/' + row['difficulty_bucket'] + '/' + row['stage'],
                'repeated_battle_failure_review', [dict(review=str(current))], battle_result='failed')
            reviews.append(dict(path=str(path), event=event))
            if self.proposal_hook:
                try:
                    proposal = self.proposal_hook(review)
                    atomic_json(path.with_suffix('.proposal.json'), dict(proposal=proposal, validation=proposal_check(proposal, review)))
                except Exception as exc:
                    self.warnings.append('proposal:' + str(exc))
        self._save()
        return dict(enabled=True, read_only=True, ledger=str(self.ledger_path),
                    summary=self.summary, captures=self.captures, reviews=reviews,
                    strategy_apply_enabled=False, warnings=self.warnings[-8:])


@contextmanager
def boundary(app, *, root, output, run_id, poll_seconds=2, proposal_hook=None):
    """Install at the final Core consumer; one reader thread, zero inputs."""
    original = app._run_maa_core_roguelike_once
    def core(params, timeout=3600):
        try:
            identity = app._RUN_SUMMARY.get('account_identity') or {}
            # No verified identity: isolate this run, never borrow global history.
            account_key = json.dumps(identity.get('account'), sort_keys=True) if identity.get('verified') else 'unverified:' + run_id
            watch = BattleWatch(app=app, root=root, output=output, run_id=run_id,
                theme=params.get('theme', 'Sami'), params=params, account_key=account_key,
                proposal_hook=proposal_hook)
            cursor = LogCursor(Path(app.OUTPUT_DIR)/'maa_core_roguelike/user/debug/asst.log')
        except Exception as exc:
            app._RUN_SUMMARY['roguelike_battle_watch_warning'] = 'prepare:' + str(exc)
            return original(params, timeout=timeout)
        stop = Event()
        def poll():
            while not stop.is_set():
                try:
                    watch.feed(cursor.read())
                except Exception as exc:
                    watch.warnings.append('observe:' + str(exc))
                stop.wait(poll_seconds)
        worker = Thread(target=poll, name='roguelike-readonly-evidence', daemon=True)
        worker.start()
        try:
            return original(params, timeout=timeout)
        finally:
            stop.set()
            worker.join(10)
            try:
                if worker.is_alive():
                    raise RuntimeError('evidence_reader_not_joined')
                watch.feed(cursor.read(), allow_capture=False)
                # Repair a missing/unparseable callback only with parseable
                # fresh evidence. The observer cannot erase a valid result.
                text = '\n'.join(watch.lines) + '\n'
                parse = getattr(app, '_roguelike_settlement_details', None)
                if (callable(parse) and not parse(getattr(app, '_LAST_MAA_RUN_LOG', ''))
                        and parse(text)):
                    app._LAST_MAA_RUN_LOG = text
                result = watch.finish()
                app._RUN_SUMMARY['roguelike_battle_watch'] = result
                app._RUN_SUMMARY.setdefault('roguelike', {})['battle_watch'] = result
            except Exception as exc:
                app._RUN_SUMMARY['roguelike_battle_watch_warning'] = str(exc)
            finally:
                if not worker.is_alive():
                    cursor.close()
    with patch.object(app, '_run_maa_core_roguelike_once', core):
        yield
