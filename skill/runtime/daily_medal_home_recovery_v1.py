"""Bounded medal archive -> quick navigation -> verified home, no battle."""
from contextlib import contextmanager
from unittest.mock import patch
from daily_fast_proxy_yw_v1 import page_kind


def medal_page(items):
    text=' '.join(str(t) for t,x,y in items)
    if all(s in text for s in ('蚀刻章套组收藏','蚀刻章列表','总收集数')):
        return 'medal_archive'
    if all(s in text for s in ('总收集数','活动奖章','拟生态')):
        return 'medal_list'
    if all(s in text for s in ('拟生态攻坚奖章','镀层方式','战备补给')):
        return 'medal_detail'
    return None


def is_home(items):
    # The shortcut overlay repeats all home labels; its 首页 button is not
    # evidence that navigation has already reached the actual home scene.
    if any(str(t).strip()=='首页' and 40<=x<=280 and 250<=y<=500 for t,x,y in items):
        return False
    names={str(t).strip() for t,x,y in items}
    return '终端' in names and len(names & {'采购中心','公开招募','任务','基建'})>=2


def recover(app):
    evidence=[]
    def result(status,reason):
        return dict(status=status,reason=reason,evidence=evidence,battle_started=False)
    def read(tag):
        for n in range(4):
            p=app.shot('medal_home_'+tag+'_'+str(n));v=app.ocr(p)
            evidence.append(dict(screenshot=str(p),ocr=v))
            text=' '.join(t for t,x,y in v)
            if text.strip() and not (len(v)<=2 and 'RHODESISLAND' in ''.join(text.upper().split())):return v
            app.wait(2)
        return v
    if app._maa_task_queue_running() is not False:return result('blocked','queue_not_confirmed_idle')
    v=read('start')
    if is_home(v):return result('home_verified','already_home')
    kind=medal_page(v)
    if not kind:return result('not_applicable','not_medal_page')
    if app._maa_task_queue_running() is not False:return result('blocked','queue_changed')
    # Same visible top house control already verified on medal-detail pages.
    app.tap(400,55);app.wait(2);v=read('quicknav')
    quick,pos=page_kind(v)
    if quick!='quick_nav':return result('blocked','quicknav_home_not_unique')
    if app._maa_task_queue_running() is not False:return result('blocked','queue_changed')
    app.tap(*pos);app.wait(4);v=read('after_home')
    return result('home_verified' if is_home(v) else 'blocked',
                  'medal_to_home_verified' if is_home(v) else 'home_not_confirmed')


@contextmanager
def boundary(app):
    # V6/DP install replaces early navigation functions. Use the established
    # completion seam, before YW captures this callable as its fallback.
    import daily_mainline_completion_v1 as completion
    original_install=completion.install;saved=[]
    def late(runtime,*args,**kwargs):
        result=original_install(runtime,*args,**kwargs)
        original=runtime.goto_main_menu;saved.append(original)
        def home(*a,**kw):
            proof=recover(runtime)
            if proof['status']=='not_applicable':return original(*a,**kw)
            runtime._RUN_SUMMARY.setdefault('medal_home_recovery',[]).append(proof)
            return proof['status']=='home_verified'
        runtime.goto_main_menu=home
        return result
    with patch.object(completion,'install',late):
        try:yield
        finally:
            for original in reversed(saved):app.goto_main_menu=original
