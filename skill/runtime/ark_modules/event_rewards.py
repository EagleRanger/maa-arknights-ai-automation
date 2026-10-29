"""YW reward worker; only this observed task banner admits its OCR alias.

Reuses the existing event navigator/reward drainer. Does not run another daily
chain or close the environment. Claim-all and viewport-only are not equivalent.
"""
from copy import deepcopy
from unittest.mock import patch
from .core import Result
from yw_task_banner_v1 import task_page,pending,claim_all_point,normalize


def claim_yw(app, event):
    evidence, pending_frames, all_taps, reward_frames = [], [], [], []
    old_ocr, old_tap, old_drain = app.ocr, app.tap, app._drain_reward_sequence
    active_point = None
    def ocr(path):
        nonlocal active_point
        rows = old_ocr(path)
        active_point = claim_all_point(rows)
        if task_page(rows):
            evidence.append(str(path))
            if pending(rows): pending_frames.append(str(path))
        return normalize(rows)
    def tap(x,y,*args,**kw):
        if app._maa_task_queue_running() is not False:
            raise RuntimeError('queue changed before reward navigation')
        if active_point == (x,y): all_taps.append((x,y))
        return old_tap(x,y,*args,**kw)
    def drain(*args,**kw):
        result = old_drain(*args,**kw)
        if result: reward_frames.append(deepcopy(result))
        return result
    with patch.object(app,'ocr',ocr), patch.object(app,'tap',tap), patch.object(app,'_drain_reward_sequence',drain):
        returned = app.claim_event_task_rewards(event)
    summary = deepcopy((app._RUN_SUMMARY.get('event') or {}).get('task_rewards') or {})
    checks=[]
    if app._maa_task_queue_running() is False:
        for n in range(2):
            path=app.shot('yw_tasks_final_'+str(n)); rows=old_ocr(path); evidence.append(str(path))
            checks.append(dict(task_page=task_page(rows), pending=pending(rows),
                               claim_button=any(str(t).strip() in ('一键领取','键领取','领取','领取奖励') for t,x,y in rows)))
            if n==0: app.wait(2)
    after_empty = len(checks)==2 and all(r['task_page'] and not r['pending'] and not r['claim_button'] for r in checks)
    # A global claim-all was actually sent, rewards appeared, and the same task
    # banner no longer offers any pending claim in two fresh frames.
    ok = (returned is True and bool(pending_frames) and bool(all_taps) and bool(reward_frames) and after_empty)
    summary.update(status='all_claimed_verified' if ok else 'unverified',
                   detail='本次一键领取及待领横幅消失已核验' if ok else '尚未取得一键领取前后完整证据',
                   claim_all_taps=len(all_taps), reward_sequences=reward_frames, final_checks=checks,
                   pending_evidence=pending_frames, evidence=evidence,
                   worker_return=returned)
    app._RUN_SUMMARY.setdefault('event',{})['task_rewards']=summary
    return Result('succeeded' if ok else 'partial', summary['detail'], tuple(evidence), summary)
