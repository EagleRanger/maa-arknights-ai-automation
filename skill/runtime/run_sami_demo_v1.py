"""Bounded real single-run host. Reuses bootstrap, Sami services and OBS.

Not a daily launcher or a replacement long-running supervisor.
"""
import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
WORKFLOW = 'ARK-SAMI-DEMO-ONCE-V1'


def needs_exploration(rows):
    """Read this run's services, then fulfil the still-unshown exploration goal.

    Zero pending rewards does not mean exploration is complete. If all culture
    is already researched, one explicitly requested demonstration still remains;
    never run again merely to manufacture another reward/upgrade.
    """
    current = {r['kind']: r['result'] for r in rows if r['phase'] == 'startup'}
    if set(current) != {'rewards', 'culture'}:
        return None
    if not all(v.get('home_confirmed_after') is True for v in current.values()):
        return None
    if current['rewards'].get('ok') is not True:
        return None
    culture = current['culture']
    deferred = (culture.get('deferred_until_settlement') is True and
                culture.get('reason') == 'culture_locked_by_active_exploration')
    if culture.get('ok') is not True and not deferred:
        return None
    if type(culture.get('progress')) is not int or type(culture.get('points_remaining')) is not int:
        return None
    if not 0 <= culture['progress'] <= 43 or culture['points_remaining'] < 0:
        return None
    return True  # Current single-exploration demonstration goal, not a grind loop.


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def effective_deadline(packet_deadline, started_at):
    return min(packet_deadline, started_at + timedelta(minutes=90))


def require_settled_source(prior):
    execution = prior.get('session', {}).get('execution', {})
    if (prior.get('cleanup', {}).get('verified') is not True
            or execution.get('settlement', {}).get('ok') is not True
            or execution.get('roguelike', {}).get('status') not in
               {'exploration_failed', 'game_pass_confirmed'}):
        raise RuntimeError('previous_natural_settlement_unverified')


@contextmanager
def input_deadline(app, deadline, clock):
    """Existing page services must observe the same deadline at each input."""
    def remaining():
        value = (deadline-clock()).total_seconds()
        if value <= 0:
            raise RuntimeError('global_deadline_before_game_input')
        return value
    def guard(method):
        def call(*args, **kwargs):
            remaining()
            return method(*args, **kwargs)
        return call
    old_wait = app.wait
    def wait(seconds, *args, **kwargs):
        result = old_wait(min(seconds, remaining()), *args, **kwargs)
        remaining()
        return result
    with ExitStack() as stack:
        for name in ('tap', 'swipe'):
            stack.enter_context(patch.object(app, name, guard(getattr(app, name))))
        stack.enter_context(patch.object(app, 'wait', wait))
        yield


def wait_for_frame_review(signal, healthy, deadline, clock, *,
                          monotonic=time.monotonic, sleep=time.sleep, timeout=900):
    """QA waiting is not a game failure; allow a normal model/tool round-trip.

    Keep the recording and global ownership boundary checked while idle. Never
    use a late signal to revive a closed run or issue input after the deadline.
    """
    until = monotonic() + timeout
    while True:
        if clock() >= deadline:
            raise RuntimeError('global_deadline_before_frame_review')
        if not healthy():
            raise RuntimeError('recording_unhealthy_before_frame_review')
        if signal.exists():
            return
        if monotonic() >= until:
            raise RuntimeError('encoded_frame_review_timeout_no_game_input')
        sleep(1)


def admit(path):
    path = Path(path).resolve()
    path.relative_to(ROOT/'outputs/continuations')
    packet = read(path)
    validation = read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')['current_validation']
    if (validation.get('status') != 'active' or validation.get('workflow') != WORKFLOW
        or packet.get('workflow') != WORKFLOW
        or (ROOT/validation['handoff']).resolve() != path
        or hashlib.sha256(path.read_bytes()).hexdigest().upper() != validation['handoff_sha256']
        or not datetime.fromisoformat(packet['not_before']) <= datetime.now().astimezone()
               < datetime.fromisoformat(packet['deadline'])
        or packet['max_explorations'] != 1 or packet['daily_replay'] is not False):
        raise RuntimeError('current_single_run_packet_mismatch')
    for name, digest in packet['artifacts'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest().upper() != digest:
            raise RuntimeError('candidate_or_dependency_changed: '+name)
    if packet.get('services_only_after_settlement'):
        source = ROOT/packet['settled_source']
        if hashlib.sha256(source.read_bytes()).hexdigest().upper() != packet['settled_source_sha256']:
            raise RuntimeError('settled_source_changed')
        require_settled_source(read(source))
    return packet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--handoff', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    packet = admit(args.handoff)
    import arknights_daily_runtime_v12 as app
    from ark_host.environment import require_interfaces
    require_interfaces(app)
    if args.check_only:
        print('single_run_packet_verified_no_game_actions')
        return 0
    import run_sami_until_deadline as sami
    from ark_host.environment import EnvironmentOwner, prepare
    from ark_host.runtime_services_v3 import boundary
    from sami_culture_complete_v1 import boundary as culture_terminal_boundary
    from sami_demo_session_v1 import run_session, _write
    sys.path.insert(0, str(ROOT/'tools/recording'))
    from sami_session_recorder_v1 import Recorder
    output = ROOT/packet['output']
    output.mkdir(parents=True, exist_ok=True)
    # Entire host including bootstrap is one non-replayable invocation.
    with (output/'host.claim').open('x', encoding='utf-8') as f:
        f.write('Do not replay. Reconcile receipt and live state.\n')
    clock = lambda: datetime.now().astimezone()
    started_at = clock()
    deadline = effective_deadline(datetime.fromisoformat(packet['deadline']), started_at)
    host = EnvironmentOwner(app, owner=packet['owner'], clock=clock, deadline=deadline)
    receipt = dict(status='preparing', workflow=WORKFLOW, started_at=started_at.isoformat(),
                   effective_deadline=deadline.isoformat(), max_session_minutes=90,
                   services_only_after_settlement=packet.get('services_only_after_settlement', False))
    recorder = Recorder(output/'recording', Path(packet['recording_output']), deadline)
    save = lambda: _write(output/'receipt.json', receipt)
    save()
    with patch.object(sami, 'ark', app), boundary(app), culture_terminal_boundary(sami):
        try:
            prepare(app)
            host.acquire()
            if app.compile_execution_plan('roguelike', theme='sami') is None:
                raise RuntimeError('existing_roguelike_contract_plan_failed')
            receipt['status'] = 'bootstrapping'; save()
            if not host.start():
                raise RuntimeError('environment_not_ready')
            receipt['status'] = 'starting_recording'; save()
            recorder.start()
            receipt.update(status='awaiting_frame_review', encoded_frame=recorder.frame); save()
            print('FRAME_READY '+recorder.frame, flush=True)
            # Bounded human/model visual QA, no game input during this wait.
            wait_for_frame_review(output/'frame_verified.signal', recorder.healthy,
                                  deadline, clock)
            receipt['status'] = 'single_run'; save()
            with input_deadline(app, deadline, clock):
                receipt['session'] = run_session(session_dir=output/'single', app=app, sami=sami,
                    ready=lambda: host.owns() and app._maa_task_queue_running() is False,
                    recording=recorder.ready_for_input, deadline=deadline, clock=clock,
                    needs_exploration=(lambda rows: False) if packet.get('services_only_after_settlement')
                                      else needs_exploration, environment_owner=host)
            receipt['status'] = receipt['session']['status']
            save()
        except (Exception, KeyboardInterrupt) as exc:
            receipt.update(status='partial', error=f'{type(exc).__name__}: {exc}')
            save()
        finally:
            # Recorder is an observer; its failure never starts another game.
            try:
                receipt['recording'] = recorder.stop()
            except Exception as exc:
                receipt['recording'] = dict(error=str(exc), recording_stopped=False)
            if host.acquired:
                receipt['cleanup'] = host.close() if host.start_attempted else {'verified': True, 'no_start': True}
                receipt['controller_released'] = host.release()
            receipt['diagnostics'] = app._RUN_SUMMARY
            receipt['finished_at'] = clock().isoformat()
            save()
    print(json.dumps(dict(status=receipt['status'], error=receipt.get('error'),
        cleanup=receipt.get('cleanup'), receipt=str(output/'receipt.json')), ensure_ascii=False), flush=True)
    return 0 if receipt['status'].startswith('completed') else 2


if __name__ == '__main__':
    raise SystemExit(main())
