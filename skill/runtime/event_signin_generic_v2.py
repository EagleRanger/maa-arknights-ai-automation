"""Final sign-in consumer: claim known layouts, return unknown rewards to AI."""
from contextlib import contextmanager
from unittest.mock import patch
import event_celebration_login_v1 as cards


def ticket_offer(text):
    value=cards.compact(text)
    return all(k in value for k in ('限时登录领取','寻访凭证','该物品过期时间'))


def ticket_handler(path,text,*,shot,read,tap,wait,busy,read_items):
    if not ticket_offer(text):return None
    out=dict(ok=False,reason='free_ticket_claim_unlocated',claimed_count=0,
             claimed_now=False,evidence=[str(path)],recognizer='ARK-FREE-LOGIN-TICKET-V2')
    point=cards.ticket_point(read_items(path))
    if busy():return dict(out,reason='maa_busy')
    if point is None:return out
    tap(*point);wait(3)
    p=shot('free_ticket_reward');out['evidence'].append(str(p));value=read(p)
    if '获得物资' not in value or '寻访' not in value:
        return dict(out,reason='free_ticket_reward_unverified')
    out.update(claimed_now=True,claimed_count=1,reward=str(p))
    tap(960,960);wait(2)
    q=shot('free_ticket_claimed');out['evidence'].append(str(q));value=read(q)
    return dict(out,ok=not ticket_offer(value),reason='claimed_and_closed' if not ticket_offer(value)
                else 'free_ticket_close_unverified')


@contextmanager
def boundary():
    import event_signin_preview_v7 as final
    import event_signin_lifecycle_v1 as lifecycle
    from daily_home_state_v1 import home_anchors
    old_handle,old_detect,old_service=final.OLD_HANDLE,final.OLD_DETECT,lifecycle.OLD_SERVICE
    def handle(path,text,**kw):
        value=ticket_handler(path,text,**kw)
        if value is None:value=cards.handler(path,text,**kw)
        return old_handle(path,text,**kw) if value is None else value
    def service(app,**kw):
        result=old_service(app,**kw)
        if result.get('home_verified') or app._maa_task_queue_running():return result
        # No reward guess: leave the unknown sign-in pending, close ONLY a
        # positively identified sign-in overlay's visible X, then verify home.
        p=str(app.shot('signin_ai_handoff_before'));items=app.ocr(p)
        text=' '.join(str(t) for t,x,y in items)
        known=old_detect(text) or cards.is_celebration_calendar(text) or ticket_offer(text)
        xs=[(round(x),round(y)) for t,x,y in items if str(t).strip().upper() in ('X','×','✕')
            and 1300<x<1910 and 80<y<260]
        if known and len(xs)==1:
            app.tap(*xs[0]);app.wait(2)
            after=str(app.shot('signin_ai_handoff_home'));rows=app.ocr(after)
            after_text=' '.join(str(t) for t,x,y in rows)
            home=(home_anchors(rows) and not old_detect(after_text)
                  and not cards.is_celebration_calendar(after_text) and not ticket_offer(after_text))
            result.setdefault('evidence',[]).extend([p,after])
            result.update(home_verified=bool(home),unhandled_signin_sent_to_ai=True,
                          reward_status='pending_not_claimed',close_point=xs[0])
        return result
    # Preview V7 installs AFTER outer adapters. Its captured final aliases are
    # the actual runtime seam, shared by popup handling and proactive discovery.
    with patch.object(final,'OLD_HANDLE',handle), \
         patch.object(final,'OLD_DETECT',lambda t:old_detect(t) or cards.is_celebration_calendar(t) or ticket_offer(t)), \
         patch.object(lifecycle,'OLD_SERVICE',service):yield
