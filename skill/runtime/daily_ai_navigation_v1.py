"""Let the execution AI verify navigation without asking failed OCR to agree.

Only a current, pictured homepage can satisfy a navigation wait. This cannot
claim rewards, finish a battle, change a resource policy, or start another owner.
"""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import hashlib

from ark_host.cooperation_v1 import read_message

REASONS = {
    'navigation_ocr_unverified_preserve_scene',
    'activity_return_unverified_preserve_scene',
    'training_return_home_unverified_preserve_scene',
}


def same_navigation_scene(reviewed, fresh):
    """Compare navigation surfaces, not OCR spelling or animated home artwork."""
    import numpy as np
    from PIL import Image
    values = []
    for path in (reviewed, fresh):
        with Image.open(path) as image:
            if image.size != (1920, 1080):
                return False
            # Menu grid and top status strip both change when a modal covers
            # home. The assistant/illustration at left is intentionally ignored.
            values.append([np.asarray(image.convert('RGB').crop(box).resize((160, 80)), dtype=float)
                           for box in ((1050, 420, 1910, 1040), (1050, 20, 1900, 160))])
    for first, second in zip(*values):
        delta = np.abs(first - second).mean(axis=2)
        if float(delta.mean()) > 8 or float((delta > 28).mean()) > .08:
            return False
    return True


def visual_recheck(app, run_id, reason, observation):
    """An AI navigation receipt is an alternative observer, never a done flag."""
    if reason not in REASONS or observation.get('ok') is True:
        return observation
    if observation.get('read_only') is not True or app._maa_task_queue_running() is not False:
        return observation
    folder = Path(app.OUTPUT_DIR) / 'daily_cooperation' / run_id
    checkpoint = read_message(folder / 'checkpoint.json')
    reply = read_message(folder / 'ai_response.json')
    proof = reply.get('navigation_observation') or {}
    event = checkpoint.get('cooperation') or {}
    if (checkpoint.get('status') != 'waiting_for_ai' or checkpoint.get('run_id') != run_id
            or reply.get('run_id') != run_id or reply.get('event_id') != event.get('event_id')
            or reply.get('action') != 'recheck' or proof.get('state') != 'main_menu'
            or not proof.get('note') or not observation.get('evidence')):
        return observation
    try:
        reviewed = Path(proof['evidence']).resolve()
        reviewed.relative_to(folder.resolve() / 'ai_navigation')
        if hashlib.sha256(reviewed.read_bytes()).hexdigest() != proof['sha256']:
            return observation
        fresh = Path(observation['evidence'][-1])
        if not same_navigation_scene(reviewed, fresh):
            return dict(observation, ai_navigation_rejected='scene_changed_recapture_for_ai')
    except (OSError, ValueError, KeyError):
        return observation
    result = dict(observation, ok=True, state='main_menu', verified_by='execution_ai_visual',
                  ai_evidence=str(reviewed), response_id=reply['response_id'],
                  business_completion_granted=False)
    app._RUN_SUMMARY.setdefault('ai_navigation_rechecks', []).append(result)
    return result


def write_navigation_reply(output, *, run_id, event_id, screenshot, note):
    """Called after AI has inspected the picture; no game input or launch."""
    from uuid import uuid4
    from shutil import copyfile
    from ark_host.cooperation_v1 import atomic_json
    from tools.ark_cooperation_control import process_alive
    folder = Path(output).resolve()
    checkpoint = read_message(folder / 'checkpoint.json')
    event = checkpoint.get('cooperation') or {}
    if (checkpoint.get('status') != 'waiting_for_ai' or checkpoint.get('run_id') != run_id
            or event.get('event_id') != event_id or checkpoint.get('finished_at')
            or process_alive(checkpoint.get('controller_pid')) is not True):
        raise ValueError('reply requires this live waiting owner')
    if str((event.get('failure') or {}).get('reason', '')).split('::', 1)[0] not in REASONS:
        raise ValueError('visual reply is only for navigation, not a business result')
    if not note or not str(note).strip():
        raise ValueError('brief visual observation required')
    source = Path(screenshot).resolve()
    if not same_navigation_scene(source, source):
        raise ValueError('expected actual 1920x1080 game frame')
    key = uuid4().hex
    target = folder / 'ai_navigation' / (key + '.png')
    target.parent.mkdir(parents=True, exist_ok=True)
    copyfile(source, target)
    result = dict(run_id=run_id, event_id=event_id, response_id=key, action='recheck',
        navigation_observation=dict(state='main_menu', evidence=str(target),
            sha256=hashlib.sha256(target.read_bytes()).hexdigest(), note=note,
            at=datetime.now().astimezone().isoformat()))
    atomic_json(folder / 'ai_response.json', result)
    return dict(status='navigation_reply_written_not_yet_applied', response_id=key)


@contextmanager
def boundary(app):
    import daily_startup_cooperation_v1 as cooperation
    import operator_training_return_v1 as training
    original_wait = cooperation.wait_for_ai
    original_recover = app._wait_unknown_navigation_page
    original_training = training.return_home
    def wait(port, run_id, reason, verify, **kwargs):
        sequence = port._RUN_SUMMARY.get('ai_wait_sequence', 0) + 1
        port._RUN_SUMMARY['ai_wait_sequence'] = sequence
        # A later incident at the same page must not reuse a delivered/resolved
        # event or an earlier reply. This is internal, not another user packet.
        incident = reason + '::' + str(sequence)
        return original_wait(port, run_id, incident,
            lambda: visual_recheck(port, run_id, reason, verify()), **kwargs)
    def accept_navigation(operation, *args, **kwargs):
        before = len(app._RUN_SUMMARY.get('ai_navigation_rechecks', []))
        result = operation(*args, **kwargs)
        if (result is False and len(app._RUN_SUMMARY.get('ai_navigation_rechecks', [])) > before
                and app._maa_task_queue_running() is False):
            # Legacy callers re-read the same failed OCR after the wait. The
            # wait already verified a fresh frame against AI's actual picture.
            proof = app._RUN_SUMMARY['ai_navigation_rechecks'][-1]
            fresh = app.shot('ai_navigation_final_probe')
            if same_navigation_scene(proof['evidence'][-1], fresh):
                return True
            # A new overlay really appeared after the successful recheck.
            # Keep the original stack waiting instead of accepting stale proof.
            hold = getattr(app, '_startup_ai_wait', None)
            if callable(hold):
                from ocr_tolerance_v1 import navigation_home
                def verify():
                    path = app.shot('ai_navigation_changed_scene')
                    return dict(ok=navigation_home(app.ocr(path)), read_only=True,
                                state='main_menu', evidence=[str(path)])
                return hold('navigation_ocr_unverified_preserve_scene', verify) == 'main_menu'
        return result
    with patch.object(cooperation, 'wait_for_ai', wait), \
         patch.object(app, '_wait_unknown_navigation_page', lambda: accept_navigation(original_recover)), \
         patch.object(training, 'return_home', lambda *a, **k: accept_navigation(original_training, *a, **k)):
        yield
