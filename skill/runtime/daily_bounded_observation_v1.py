"""Bound memory in completion evidence and retry transient capture failures.

MAA OutOfMemory is a real queue failure, never a successful daily receipt.
This layer does not restart MAA, click the game, or suppress incomplete chains.
"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import subprocess
import traceback
from unittest.mock import patch

import daily_completed_goal_freeze_v24 as old
from daily_fight_boundary_v2 import ACTION

MAX_LINE = 64 * 1024


def scan(path, now, day):
    """Constant-space scan; never allocate the whole log or queue segment."""
    candidate = None
    count = 0
    digest = None
    done = set()
    fighting = spent = False
    latest_fight = None
    malformed = False
    with path.open(encoding='utf-8', errors='replace') as stream:
        while True:
            line = stream.readline(MAX_LINE + 1)
            if not line:
                break
            if len(line) > MAX_LINE:
                # A split/huge line may contain a missing Fight or boundary.
                # Fail closed for this file instead of trusting a partial tail.
                malformed = True
                while line and not line.endswith('\n'):
                    line = stream.readline(MAX_LINE + 1)
                continue
            stamp = old.STAMP_RE.search(line)
            at = None
            if stamp:
                try:
                    at = datetime.fromisoformat(stamp[1])
                except ValueError:
                    pass
            if '开始任务: 理智作战' in line or 'Start Task Chain: Fight' in line:
                if not fighting:
                    fighting, spent = True, False
            if fighting:
                action = ACTION.search(line)
                if action:
                    first, last, cost = int(action[1]), int(action[2] or action[1]), int(action[3])
                    spent |= 0 < first <= last and cost > 0
                if '完成任务: 理智作战' in line or 'Completed Task Chain: Fight' in line:
                    if spent and at and at <= now and day(at) == day(now):
                        latest_fight = max(latest_fight, at) if latest_fight else at
                    fighting = spent = False
            start = old.START_RE.search(line)
            if start:
                digest, done = hashlib.sha256(), set()
                line = line[start.start():]
            if digest is not None:
                digest.update(line.encode('utf-8'))
                done.update(k for k, pattern in old.CHAIN_DONE_RE.items() if pattern.search(line))
                if old.QUEUE_END_RE.search(line):
                    if len(done) == len(old.DAILY_CHAINS) and at and at <= now and day(at) == day(now):
                        count += 1
                        row = dict(completed_at=at, source=str(path), segment_sha256=digest.hexdigest().upper())
                        if candidate is None or at > candidate['completed_at']:
                            candidate = row
                    digest = None
    return candidate, count, latest_fight, malformed


def find_same_day_completed_goal(runtime, *, now=None):
    now = now or datetime.now()
    day = getattr(runtime, '_game_day_key', old._default_game_day)
    latest = getattr(runtime, '_CURRENT_RUN_LAST_STAMINA_BATTLE_AT', None)
    best, count, inspected, uncertain = None, 0, [], []
    for path in old._gui_log_paths(runtime):
        try:
            row, n, fight, malformed = scan(path, now, day)
        except FileNotFoundError:
            continue
        except (OSError, MemoryError) as exc:
            uncertain.append(dict(path=str(path), reason=type(exc).__name__))
            continue
        inspected.append(str(path))
        if malformed:
            uncertain.append(dict(path=str(path), reason='oversize_line'))
        count += n
        if fight:
            latest = max(latest, fight) if latest else fight
        if row and (best is None or row['completed_at'] > best['completed_at']):
            best = row
    result = dict(status='not_frozen', reason='no_same_day_complete_after_latest_fight',
                  inspected_logs=inspected, candidate_count=count, bounded_reader=True,
                  latest_fight_at=latest.isoformat(timespec='seconds') if latest else None)
    if uncertain:
        result.update(reason='log_evidence_incomplete', read_errors=uncertain)
    elif best and (latest is None or best['completed_at'] > latest):
        result.update(best, status='frozen_same_day_complete', game_day=day(now),
                      completed_at=best['completed_at'].isoformat(timespec='seconds'),
                      chains=list(old.DAILY_CHAINS), reentry_prevented=True)
        result.pop('reason', None)
    return result


@contextmanager
def boundary(app):
    import daily_frozen_cleanup_v25 as cleanup
    capture = app.shot
    print_exception = traceback.print_exc
    broken_device = None
    broken_error = None

    def persist_exception(*args, **kwargs):
        # The legacy entry catches exceptions and only prints to stderr.
        # Keep a bounded real stack in its existing manifest summary as well.
        evidence = traceback.format_exc(limit=30)
        if evidence.strip() != 'NoneType: None':
            app._RUN_SUMMARY['exception_traceback'] = evidence[-32768:]
        return print_exception(*args, **kwargs)

    def shot(name='s'):
        nonlocal broken_device, broken_error
        device = getattr(app, 'DEVICE', '<current>')
        if broken_error is not None and device == broken_device:
            # One broken transport episode has one retry budget. Final sanity,
            # badges and reporting must not each add another 30-second stall.
            raise broken_error
        for attempt in range(1, 4):
            try:
                result = capture(name)
                # Legacy capture returns a valid 1x1 PNG after device failure.
                # Valid file syntax is not a usable game observation: never let
                # that placeholder reach OCR/navigation and loop indefinitely.
                from PIL import Image
                with Image.open(result) as frame:
                    if frame.width < 320 or frame.height < 180:
                        raise OSError(f'invalid_game_capture: {frame.width}x{frame.height}; {result}')
                    frame.verify()
                broken_device = broken_error = None
                return result
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as exc:
                rows = app._RUN_SUMMARY.setdefault('capture_transport_retries', [])
                rows.append(dict(name=name, attempt=attempt, error=type(exc).__name__))
                # Preserve at most recent 20 attempts, not an unbounded log.
                del rows[:-20]
                if attempt == 3:
                    broken_device, broken_error = device, exc
                    app._RUN_SUMMARY['capture_transport_exhausted'] = dict(
                        device=device, attempts=3, first_failed_phase=name,
                        rule='no_repeated_capture_until_new_runtime_or_device')
                    raise
                app.log(f'[截图恢复] {name} 连接暂时失败，第{attempt}/3次；只重截，不点击或重启')
                app.wait(attempt)

    with patch.object(old, 'find_same_day_completed_goal', find_same_day_completed_goal), \
         patch.object(cleanup, 'find_same_day_completed_goal', find_same_day_completed_goal), \
         patch.object(app, 'shot', shot), patch.object(traceback, 'print_exc', persist_exception):
        yield
