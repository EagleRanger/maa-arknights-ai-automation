"""Local, identity-bound terminal receipts; never starts or controls the game."""
import json
from pathlib import Path


def bind_manifest(path, run_id):
    if not path and not run_id:
        return {}
    if not path or not run_id:
        raise ValueError('run-manifest and run-id must be supplied together')
    path = Path(path).resolve()
    record = json.loads(path.read_text(encoding='utf-8-sig'))
    if record.get('run_id') != run_id:
        raise ValueError('run manifest identity mismatch')
    if record.get('finished_at') or record.get('cleanup_finished'):
        raise ValueError('terminal run cannot be reused')
    return {'run_id': run_id, 'run_manifest': str(path)}


def terminal_projection(state):
    sessions = state.get('sessions') or []
    settled = [s for s in sessions if s.get('maa_status') in
               ('exploration_failed', 'game_pass_confirmed')
               and (s.get('settlement_drain') or {}).get('ok') is True]
    return {
        'status': state['status'],
        'business_status': state['status'],
        'business_detail': state.get('detail'),
        'finished_at': state['finished_at'],
        'sami_checkpoint_started_at': state['started_at'],
        'sami_result': {'sessions_observed': len(sessions),
                        'sessions_settled': len(settled),
                        'sessions_unsettled': len(sessions) - len(settled),
                        'game_pass_count': sum(s.get('game_pass') is True for s in settled)},
        'cleanup_finished': state.get('cleanup_finished') is True,
        'cleanup_finished_at': state.get('cleanup_finished_at'),
        'cleanup_error': state.get('cleanup_error'),
        'next_checkpoint': 'terminal; no implicit restart or replay',
    }


def _atomic_json(path, data):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def persist_terminal(state):
    if not state.get('run_manifest') or not state.get('finished_at'):
        return False
    if not state.get('cleanup_finished') and not state.get('cleanup_error'):
        return False  # A terminal signal before cleanup is not the final receipt.
    path = Path(state['run_manifest'])
    record = json.loads(path.read_text(encoding='utf-8-sig'))
    if not state.get('run_id') or record.get('run_id') != state['run_id']:
        raise ValueError('run manifest identity changed; refusing terminal overwrite')
    bound_start = record.get('sami_checkpoint_started_at')
    if bound_start and bound_start != state['started_at']:
        raise ValueError('supervisor instance mismatch')
    snapshot = path.with_name(path.stem + '.sami_terminal.json')
    if snapshot.exists():
        previous = json.loads(snapshot.read_text(encoding='utf-8-sig'))
        if previous != state:
            raise ValueError('immutable terminal snapshot already exists')
    else:
        _atomic_json(snapshot, state)
    record.update(terminal_projection(state))
    record['sami_terminal_evidence'] = str(snapshot)
    _atomic_json(path, record)
    return True
