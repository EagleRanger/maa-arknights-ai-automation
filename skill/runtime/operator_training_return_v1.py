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


def return_page(rows):
    """Only known foreground layouts; never confirm a selection on the way out."""
    from scan_retry_v1 import roster_grid,norm
    if any(480<x<1500 and 210<y<900 and any(s in norm(t) for s in
            ('是否','确认','取消','资源不足','获得物资')) for t,x,y in rows):return None
    if is_training_detail(rows):return 'training_detail'
    if roster_grid(rows):return 'roster'
    def at(words,l,t,r,b):
        return any(l<x<r and t<y<b and norm(s) in words for s,x,y in rows)
    if (at({'属性'},0,330,180,440) and at({'精英化'},1350,315,1650,465)
            and at({'信赖值'},0,555,230,690) and at({'管理+','管理十','管理'},1670,790,1910,935)):
        return 'profile'
    if (at({'等级'},1170,10,1380,90) and at({'稀有度'},1360,10,1510,90)
            and at({'信赖值'},1500,10,1700,90) and at({'攻击范围'},0,360,250,465)
            and at({'技能'},0,465,275,555) and at({'分支+','分支十'},275,465,555,555)
            and at({'确认'},1560,951,1870,1078)):
        return 'picker'
    return None


def return_home(app, original):
    path = app.shot('training_return_boundary')
    rows = app.ocr(path)
    if is_home(rows):
        return app._maa_task_queue_running() is False
    def fallback():
        # An unfamiliar layer can still use the ordinary navigation helpers;
        # if they ask for AI, keep the identity of the operation that owns it.
        hold=getattr(app,'_startup_ai_wait',None)
        if not callable(hold):return original()
        def wait(reason,verify):
            if reason=='navigation_ocr_unverified_preserve_scene':
                reason='training_return_home_unverified_preserve_scene'
            return hold(reason,verify)
        with patch.object(app,'_startup_ai_wait',wait):return original()
    page=return_page(rows)
    if not page:
        return fallback()
    if app._maa_task_queue_running() is not False:
        return False
    evidence = [str(path)]
    for _ in range(3):
        if app._maa_task_queue_running() is not False:return False
        if page=='training_detail':app.back()
        else:app.tap(*app.POS_BACK)  # in-game top-left Back; NOT picker confirmation
        app.wait(1)
        path = app.shot('training_return_after_back')
        rows = app.ocr(path)
        evidence.append(str(path))
        if is_home(rows):
            ok = True
            break
        page=return_page(rows)
        if not page:
            ok = fallback() is True
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
