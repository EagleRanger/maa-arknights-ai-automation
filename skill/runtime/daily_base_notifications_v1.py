"""Reuse MAA's notification/one-click harvest route, not staff reassignment."""
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
import cv2,numpy as np

ROOT=Path(__file__).resolve().parent
TEMPLATE=ROOT/'assets/vision/base_notification_v1/InfrastNotification.png'
# MAA 6.19 InfrastNotification / InfrastReward / InfrastExitReward, 1280x720.
COLLECT_WORDS=('可收获','订单交付','员信赖')


def bell_position(path):
    frame=cv2.imdecode(np.fromfile(str(path),np.uint8),1)
    template=cv2.imdecode(np.fromfile(str(TEMPLATE),np.uint8),0)
    if frame is None or frame.shape[:2]!=(1080,1920):return None
    frame=cv2.cvtColor(cv2.resize(frame,(1280,720)),cv2.COLOR_BGR2GRAY)
    roi=frame[0:300,1100:1280]
    scores=cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED)
    _,score,_,(x,y)=cv2.minMaxLoc(scores)
    if score<.9:return None
    h,w=template.shape
    return dict(x=round((1100+x+w/2)*1.5),y=round((y+h/2)*1.5),score=score)


def actions(items):
    return [(text,x,y) for text,x,y in items if 0<x<1200 and 900<y<1077
        and any(word in str(text) for word in COLLECT_WORDS) and '换班' not in str(text)]


def collect(app,claim_tasks=False):
    row=app._RUN_SUMMARY.setdefault('base_notification_cleanup',dict(complete=False,new_queues=0,operator_assignment_taps=0,drone_taps=0,steps=[]))
    if app._maa_task_queue_running() is not False:row['reason']='queue_not_idle';return row
    if not app.goto_main_menu():row['reason']='home_unverified';return row
    p=app.shot('base_notify_home');items=app.ocr(p);pos=app.find_text(items,'基建',exact=True) or app.find_text(items,'BASE',exact=True)
    if not pos:row['reason']='base_entry_unread';return row
    app.tap(*pos);app.wait(3)
    p=app.shot('base_notify_before');items=app.ocr(p)
    if not any('进驻总览' in str(t) or '控制中枢' in str(t) for t,*_ in items):row['reason']='base_page_unverified';return row
    bell=bell_position(p);row.update(before=str(p),bell=bell)
    if not bell:row['reason']='notification_template_unverified';return row
    app.tap(bell['x'],bell['y']);app.wait(2)
    for i in range(12):
        p=app.shot(f'base_notify_panel_{i}');items=app.ocr(p);text=' '.join(str(t) for t,*_ in items)
        candidates=actions(items);row['steps'].append(dict(evidence=str(p),items=items,actions=candidates))
        # Recognition stays in MAA's lower notification ROI. Never click
        # one-key shift, drones, upgrades or arbitrary 'all' buttons.
        if not candidates:
            if not any(word in text for word in ('进驻总览','控制中枢','待办','通知','线索','疲劳')):
                row['reason']='notification_page_unknown';return row
            row.update(complete=True,one_click_collectables_cleared=True,remaining_notifications_not_assumed_zero=True,final_panel=str(p))
            break
        chosen=candidates[0];app.tap(chosen[1],chosen[2]);app.wait(2)
    else:row['reason']='notification_action_limit';return row
    # MAA's documented blank exit region; only after this known panel.
    app.tap(412,187);app.wait(2)
    row['home_verified']=app.goto_main_menu() is True
    row['complete']=bool(row['complete'] and row['home_verified'])
    app.log('✅ 基建通知中可一键收取项已检查；非一键通知不伪报为0' if row['complete'] else '⚠️ 基建通知回程未核验')
    return row


@contextmanager
def boundary(app):
    import daily_mainline_completion_v1 as completion
    original_install=completion.install;saved=[]
    def late(runtime,*a,**k):
        result=original_install(runtime,*a,**k);saved.append(runtime.check_and_clear_badges)
        runtime.check_and_clear_badges=lambda *a,**k:collect(runtime,*a,**k)
        return result
    with patch.object(completion,'install',late):
        try:yield
        finally:
            for old in reversed(saved):app.check_and_clear_badges=old
