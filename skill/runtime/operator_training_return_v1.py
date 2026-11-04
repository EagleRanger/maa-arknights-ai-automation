"""Return from the native training skill detail without touching the training."""
from contextlib import contextmanager
from unittest.mock import patch
import operator_training_v1 as native
from operator_home_labels_v1 import is_home


def is_training_detail(rows):
    left = ''.join(str(t).replace(' ', '') for t, x, y in rows if x < 550)
    skills = ''.join(str(t).replace(' ', '') for t, x, y in rows if x > 700)
    return ('训练中' in left and '协助者' in left
            and ('自动回复' in skills or '自動回復' in skills)
            and ('专精' in left or '專精' in left))


def return_home(app, original):
    path = app.shot('training_return_boundary')
    rows = app.ocr(path)
    if not is_training_detail(rows):
        return original()
    if app._maa_task_queue_running() is not False:
        return False
    evidence = [str(path)]
    for _ in range(3):
        # Only Android Back on this positively identified detail. Never tap a
        # skill, trainee, assistant, confirm, or cancellation control.
        app.back()
        app.wait(.5)
        path = app.shot('training_return_after_back')
        rows = app.ocr(path)
        evidence.append(str(path))
        if is_home(rows):
            ok = True
            break
        if not is_training_detail(rows):
            ok = original() is True
            break
    else:
        ok = False
    record = dict(status='home_verified' if ok else 'waiting_for_ai',
                  evidence=evidence, training_replaced=False)
    app._RUN_SUMMARY['operator_training_return'] = record
    if ok:
        return True
    wait = getattr(app, '_startup_ai_wait', None)
    if not callable(wait):
        raise RuntimeError('training return requires existing AI recovery seam')
    def probe():
        p = app.shot('training_return_ai_recheck')
        return dict(ok=is_home(app.ocr(p)) and app._maa_task_queue_running() is False,
                    read_only=True, evidence=[str(p)], state='training_return_home')
    wait('training_return_home_unverified_preserve_scene', probe)
    checked = probe()
    record.update(status='home_verified_after_ai' if checked['ok'] else 'waiting_for_ai',
                  recheck=checked)
    return checked['ok']


@contextmanager
def boundary(app):
    original_one = native._service_one
    def one(*args, **kwargs):
        original_home = app.goto_main_menu
        with patch.object(app, 'goto_main_menu', lambda: return_home(app, original_home)):
            return original_one(*args, **kwargs)
    with patch.object(native, '_service_one', one):
        yield
