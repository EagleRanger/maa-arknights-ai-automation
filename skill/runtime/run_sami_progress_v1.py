"""Normal Sami continuation: compose the existing supervisor, never filming/daily."""
import argparse
from contextlib import ExitStack
from datetime import datetime
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
WORKFLOW = 'ARK-SAMI-PROGRESS-V1'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def admit(path, now=None):
    path = Path(path).resolve()
    path.relative_to(ROOT / 'outputs/continuations')
    packet = read(path)
    current = read(ROOT / '.project-reasoning/AUTOMATION_HANDOFF.json')['current_roguelike_progress']
    now = now or datetime.now().astimezone()
    deadline = datetime.fromisoformat(packet['deadline'])
    if (current['status'] != 'active' or packet['workflow'] != WORKFLOW
            or current['workflow'] != WORKFLOW
            or (ROOT / current['handoff']).resolve() != path
            or hashlib.sha256(path.read_bytes()).hexdigest().upper() != current['handoff_sha256']
            or not datetime.fromisoformat(packet['not_before']) <= now < deadline
            or packet['theme'] != 'Sami' or packet['daily_replay'] is not False
            or packet['recording'] is not False):
        raise ValueError('current_sami_continuation_mismatch')
    for name, digest in packet['artifacts'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest().upper() != digest:
            raise ValueError('sami_dependency_changed: ' + name)
    return packet, deadline


def rewards_until_empty(service, limit=6):
    """A decrease is progress, not completion; revisit until no pending marker."""
    passes = []
    for _ in range(limit):
        row = service()
        passes.append(row)
        if row.get('ok') is not True or row.get('home_confirmed_after') is not True:
            return dict(row, ok=False, passes=passes)
        if row.get('pending_after') == 0:
            return dict(row, passes=passes)
        before, after = row.get('pending_before'), row.get('pending_after')
        if not (type(before) is int and type(after) is int and 0 <= after < before):
            return dict(row, ok=False, reason='reward_pending_not_decreasing', passes=passes)
    return dict(row, ok=False, reason='reward_claim_pass_limit', passes=passes)


def verified_cleanup(sami, app, state, status, detail):
    """Keep the old feedback channel but never hardcode cleanup=true."""
    state.update(status=status, detail=detail, finished_at=sami.now_iso())
    sami.write_checkpoint(state)
    try:
        if app._maa_task_queue_running():
            app._stop_maa_task_queue(timeout=45)
        app.cleanup_after_task(check_badges=False)
        app.stop_log_viewer()
        from ark_host.environment import INSTANCE_IMAGES
        remaining = app._running_process_images(tuple(x for x in INSTANCE_IMAGES if x != 'adb.exe'))
        state['cleanup_remaining'] = remaining
        state['cleanup_finished'] = remaining == [] and app._maa_task_queue_running() is False
        if not state['cleanup_finished']:
            state['cleanup_error'] = 'owned_environment_residue_or_queue'
    except Exception as exc:
        state.update(cleanup_finished=False, cleanup_error=f'{type(exc).__name__}: {exc}')
    state['cleanup_finished_at'] = sami.now_iso()
    sami.write_checkpoint(state)
    sami.safe_emit_attention_feedback(state, status, detail)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--handoff', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    packet, deadline = admit(args.handoff)
    import arknights_daily_runtime_v12 as app
    import run_sami_until_deadline as sami
    from ark_host.environment import prepare, require_interfaces
    from ark_host.runtime_services_v3 import boundary as runtime_boundary
    from daily_runtime_target_v1 import boundary as target_boundary, inventory
    from sami_culture_complete_v1 import boundary as culture_boundary
    from sami_demo_session_v1 import isolated_config, _write
    from run_sami_demo_v1 import input_deadline
    require_interfaces(app)
    row = inventory(app.MUMU_CLI)
    if args.check_only:
        print(json.dumps(dict(status='ready_no_game_actions', workflow=WORKFLOW,
                              vm_index=row['index'], deadline=deadline.isoformat()), ensure_ascii=False))
        return 0
    output = ROOT / packet['output']
    output.mkdir(parents=True, exist_ok=True)
    (output / 'host.claim').open('x', encoding='utf-8').close()
    manifest = output / 'run.json'
    _write(manifest, dict(run_id=packet['run_id'], workflow=WORKFLOW,
                         authority=packet['authority'], deadline=deadline.isoformat()))
    prepare(app)
    configuration = {}
    original_rewards = sami.service_expedition_records
    original_core = app._run_maa_core_roguelike_once
    def bounded_core(params, timeout=3600):
        remaining = int((deadline - datetime.now().astimezone()).total_seconds()) - 90
        if remaining < 30:
            raise RuntimeError('global_deadline_before_core')
        return original_core(params, timeout=min(timeout, remaining))
    def rewards(*args, **kwargs):
        with input_deadline(app, deadline, lambda: datetime.now().astimezone()):
            return rewards_until_empty(lambda: original_rewards(*args, **kwargs))
    with target_boundary(app), runtime_boundary(app), patch.object(sami, 'ark', app), \
            culture_boundary(sami), isolated_config(app, output, configuration), ExitStack() as stack:
        full_culture = sami.service_culture
        def culture(*args, **kwargs):
            with input_deadline(app, deadline, lambda: datetime.now().astimezone()):
                return full_culture(*args, **kwargs)
        stack.enter_context(patch.object(sami, 'service_expedition_records', rewards))
        stack.enter_context(patch.object(sami, 'service_culture', culture))
        stack.enter_context(patch.object(sami, 'cleanup',
            lambda state, status, detail: verified_cleanup(sami, app, state, status, detail)))
        stack.enter_context(patch.object(app, '_run_maa_core_roguelike_once', bounded_core))
        # Each real invocation has an independent checkpoint, not September's file.
        stack.enter_context(patch.object(sami, 'CHECKPOINT', output / 'checkpoint.json'))
        stack.enter_context(patch.object(sami, 'SUPERVISOR_LOG', output / 'supervisor.log'))
        result = sami.run(deadline, '维什戴尔', '指挥分队', '稳扎稳打',
                          no_viewer=True, run_manifest=manifest, run_id=packet['run_id'])
    _write(output / 'configuration.json', configuration)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
