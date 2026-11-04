"""Daily supply: title -> existing checkmark -> fresh state. Startup only."""
from contextlib import contextmanager
from unittest.mock import patch
from daily_login_visual_v1 import boundary as BASE, StartupUnverified


def is_supply(items):
    title=''.join(''.join(str(t).split()) for t,x,y in items
                  if 650<=x<=1250 and 150<=y<=330)
    return any(t in title for t in ('今日配给','每日配给'))


@contextmanager
def boundary(app):
    with BASE(app):
        old_ocr,old_state,old_ensure=app.ocr,app.get_state,app.ensure_env
        active=False
        latest={}

        def ocr(path):
            items=old_ocr(path)
            if active:
                latest.update(path=str(path),items=items,supply=is_supply(items))
            return items

        def state():
            latest.clear()
            value=old_state()
            if not active:
                return value
            def action():
                if latest.get('supply'):return app.POS_DISMISS,'daily_supply'
                if value not in ('unknown','reward','main_menu'):return None
                rows=latest.get('items') or []
                from event_wish_wall_v1 import is_wall
                if is_wall(' '.join(str(t) for t,x,y in rows)):
                    return None  # Known free reward: existing wall handler first.
                xs=[(round(x),round(y)) for t,x,y in rows
                    if str(t).strip().upper() in ('X','×','✕') and 1300<x<1910 and 80<y<260]
                if len(xs)==1:return xs[0],'unrecognized_overlay'
                if not latest.get('path'):return None
                from event_signin_generic_v3 import close_point
                try:point=close_point(latest['path'],rows)
                except (OSError,ValueError,TypeError):point=None
                return (point,'unrecognized_overlay') if point else None
            for attempt in range(3):
                chosen=action()
                if chosen is None:
                    return value
                if app._maa_task_queue_running() is not False:
                    return value
                point,kind=chosen
                if kind=='daily_supply':
                    row=app._RUN_SUMMARY.setdefault('login_daily_supply',
                        dict(status='observed_not_dismissed',handler='startup_title_checkmark',frames=[]))
                    row['frames'].append(latest['path'])
                    row['confirmation_taps']=row.get('confirmation_taps',0)+1
                    app.log('  → 今日配给：点击底部确认，重新读取页面')
                else:
                    app._RUN_SUMMARY.setdefault('startup_overlay_dismissals',[]).append(dict(
                        evidence=latest['path'],point=point,claimed_now=False))
                    app.log('  → 未识别弹窗：关闭可见的右上角×，重新读取页面')
                app.tap(*point)
                app.wait(1)
                latest.clear()
                value=old_state()
            if action() is not None:
                reason='daily_supply_confirmation_no_progress_3' if latest.get('supply') else 'startup_overlay_close_no_progress_3'
                handoff=getattr(app,'_startup_ai_wait',None)
                if callable(handoff):
                    def recheck():
                        nonlocal value
                        latest.clear();value=old_state()
                        return dict(ok=value in ('main_menu','login','event_signin','monthly_sign_in','announcement')
                                    and action() is None,read_only=True,state=value,
                                    evidence=[latest['path']] if latest.get('path') else [])
                    return handoff(reason,recheck)
                raise StartupUnverified(reason)
            return value

        def ensure(*args,**kwargs):
            nonlocal active
            active=True
            try:
                while True:
                    ok=old_ensure(*args,**kwargs)
                    reason=(app._RUN_SUMMARY.get('login_visual') or {}).get('reason')
                    handoff=getattr(app,'_startup_ai_wait',None)
                    if ok is True or not reason or not callable(handoff) or reason=='startup_ai_explicit_stop':
                        break
                    def recheck():
                        latest.clear();value=old_state()
                        return dict(ok=value=='main_menu' and not latest.get('supply'),
                            read_only=True,state=value,evidence=[latest['path']] if latest.get('path') else [])
                    handoff(reason,recheck)
                    prior=app._RUN_SUMMARY.get('page_attention') or {}
                    if prior.get('reason')==reason:
                        app._RUN_SUMMARY.pop('page_attention',None)
                    # Only startup is retried; daily business has not run.
                if ok is True and 'login_daily_supply' in app._RUN_SUMMARY:
                    app._RUN_SUMMARY['login_daily_supply']['status']='overlay_drained_and_home_verified'
                return ok
            finally:
                active=False

        with patch.object(app,'ocr',ocr),patch.object(app,'get_state',state),patch.object(app,'ensure_env',ensure):
            yield
