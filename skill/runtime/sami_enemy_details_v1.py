"""The observed enemy encyclopedia overlay, not a settlement or a defeat.

Extend the existing bounded MAA interruption-recovery hook; keep its retry
budget, arguments and deadline instead of creating another gameplay loop.
"""
from contextlib import contextmanager
from unittest.mock import patch
from PIL import Image


def enemy_details(items):
    compact=lambda t:''.join(str(t).split())
    tabs={compact(t) for t,x,y in items if 1100<=x<=1650 and 25<=y<=130}
    stats=('生命值','攻击力','防御力','法术抗性','移动速度','攻击速度','元素抗性','损伤抵抗')
    hits={word for word in stats for t,x,y in items
          if word in compact(t) and 1000<=x<=1900 and 315<=y<=650}
    category=any(any(word in compact(t) for word in ('近战物理','远程物理','近战法术','远程法术'))
                 and 1000<=x<=1550 and 200<=y<=330 for t,x,y in items)
    return {'全部','精英','领袖'}<=tabs and len(hits)>=5 and category


def underlying_page(items):
    text=' '.join(str(t) for t,x,y in items)
    if all(w in text for w in ('探险手册','文化比较')) and any(w in text for w in ('开始探索','继续探索')):
        return 'sami_home'
    top={w for w in ('目标生命值','指挥等级') for t,x,y in items
         if w in str(t) and 200<=x<=850 and y<=140}
    bottom={w for w in ('干员','编队') for t,x,y in items
            if w in str(t) and 1350<=x<=1900 and y>=950}
    if len(top)==2 and len(bottom)==2:
        return 'sami_route'
    return None


def close_once(app, *, owner_idle=None):
    idle=owner_idle or (lambda:app._maa_task_queue_running() is False)
    if not idle():
        return dict(ok=False,reason='enemy_details_owner_busy',actions=[])
    path=app.shot('sami_enemy_details_before')
    items=app.ocr(path)
    if not enemy_details(items):
        return None
    with Image.open(path) as image:
        if image.size!=(1920,1080):
            return dict(ok=False,reason='enemy_details_size_unverified',actions=[],screenshot=str(path))
    if not idle():
        return dict(ok=False,reason='enemy_details_owner_became_busy',actions=[])
    app.tap(65,55)
    app.wait(1.5)
    state=None
    for index in range(2):
        after=app.shot('sami_enemy_details_after')
        after_items=app.ocr(after)
        state=underlying_page(after_items) if not enemy_details(after_items) else None
        if state:
            break
        if index==0:
            app.wait(.8)  # A black transition is not successful closure.
    closed=state is not None
    return dict(ok=closed,kind='close_enemy_details',screenshot=str(path),
        after_screenshot=str(after),position=[65,55],settlement_confirmed=False,underlying_state=state,
        reason='enemy_details_closed' if closed else 'enemy_details_close_unverified')


@contextmanager
def boundary(app):
    original=app._close_roguelike_interruption_once
    def recover(*a,**kw):
        if app._maa_task_queue_running():
            return None
        result=close_once(app)
        if result is not None:
            app._RUN_SUMMARY.setdefault('sami_enemy_details_recoveries',[]).append(result)
            return result if result.get('ok') is True else None
        return original(*a,**kw)
    with patch.object(app,'_close_roguelike_interruption_once',recover):
        yield
