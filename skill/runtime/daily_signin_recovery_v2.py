"""Release only the matching navigation latch after the live owner's recheck.

Keep the incident and reward evidence. A verified home does not prove a claim;
it only permits the original daily planner to execute the unfinished business.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from ark_host.cooperation_v1 import atomic_json, read_message
from daily_signin_recovery_v1 import AI_REASON

NAVIGATION_REASONS = {'wish_wall_reward_pending_home_unverified'}


def release_navigation(app, run_id, captured):
    summary = app._RUN_SUMMARY
    if not captured or summary.get('page_attention') != captured:
        return False
    if captured.get('reason') not in NAVIGATION_REASONS or captured.get('battle_result') is not None:
        return False
    state = summary.get('startup_ai_cooperation') or {}
    cooperation = state.get('cooperation') or {}
    proof = cooperation.get('recheck') or {}
    if (state.get('run_id') != run_id or state.get('status') != 'resumed'
            or cooperation.get('status') != 'rechecked_resume_same_step'
            or proof.get('ok') is not True or proof.get('read_only') is not True
            or proof.get('state') != 'main_menu' or not proof.get('evidence')
            or app._maa_task_queue_running() is not False):
        return False
    path = Path(captured.get('path', '')).resolve()
    try:
        path.relative_to((Path(app.OUTPUT_DIR) / 'event_page_attention').resolve())
        incident = read_message(path)
        if (incident.get('run_id') != run_id or incident.get('reason') != captured['reason']
                or incident.get('battle_result') is not None):
            return False
        # Delivery provenance and original observations remain unchanged.
        incident.update(status='navigation_resolved_by_ai_recheck', needs_attention=False,
            resolved_by_event_id=cooperation.get('event_id'),
            navigation_recheck=deepcopy(proof), business_completion_granted=False)
        atomic_json(path, incident)
    except (OSError, ValueError, TypeError):
        return False
    summary.setdefault('resolved_page_attention', []).append(dict(
        deepcopy(captured), status='navigation_resolved_by_ai_recheck',
        recheck_event_id=cooperation.get('event_id'), evidence=deepcopy(proof['evidence']),
        business_completion_granted=False))
    summary.pop('page_attention', None)
    app.log('[AI接回] 当前首页已核验，解除同一导航阻断，继续原定业务；未新增领奖或通关认定')
    return True


@contextmanager
def boundary(app):
    import daily_startup_cooperation_v1 as cooperation
    original = cooperation.wait_for_ai

    def wait(port, run_id, reason, verify, **kwargs):
        captured = deepcopy(port._RUN_SUMMARY.get('page_attention'))
        result = original(port, run_id, reason, verify, **kwargs)
        if reason.split('::', 1)[0] == AI_REASON and result == 'main_menu':
            release_navigation(port, run_id, captured)
        return result

    with patch.object(cooperation, 'wait_for_ai', wait):
        yield


def run_composed(operation, app):
    import run_daily as engine
    original = engine.main

    def main(*args, **kwargs):
        with boundary(app):
            return original(*args, **kwargs)

    with patch.object(engine, 'main', main):
        return operation()
