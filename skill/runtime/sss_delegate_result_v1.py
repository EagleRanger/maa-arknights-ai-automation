"""Actual SSS delegation receipt screen, distinct from generic loot overlays."""
from contextlib import contextmanager
from unittest.mock import patch
import re


def receipt(items):
    text=' '.join(str(t).replace(' ','') for t,_,_ in items)
    strip=re.search(r'(?<!\d)(\d{1,2})/60(?!\d)',text)
    device=re.search(r'(?<!\d)(\d{1,2})/24(?!\d)',text)
    valid=('保全作战完成' in text and '完成时间' in text and '数据增补条' in text
        and '数据增补仪' in text and strip and device)
    return dict(verified=bool(valid),counts=dict(strip=int(strip[1]),device=int(device[1])) if valid else {})


def dismiss(app):
    frame=app.shot('sss_delegate_settlement_before');proof=receipt(app.ocr(frame))
    proof['before']=str(frame)
    if not proof['verified']:return proof
    # The inspected screen has no button: its lower-right blank closes the
    # receipt. Exactly one click; never repeat a submission or call Start.
    app.tap(1750,980);app.wait(3)
    frame=app.shot('sss_delegate_settlement_after');proof['after']=str(frame)
    proof['dismissed']=not receipt(app.ocr(frame))['verified']
    return proof


@contextmanager
def boundary(app):
    original=app.goto_main_menu
    def home(*args,**kwargs):
        proof=dismiss(app)
        if proof['verified']:
            app._RUN_SUMMARY.setdefault('sss_settlement_return',[]).append(proof)
            if not proof.get('dismissed'):return False
        return original(*args,**kwargs)
    with patch.object(app,'goto_main_menu',home):yield


def post_service(app,packet):
    from delegate_inventory_observe_v2 import observe
    from sss_reward_pages_v2 import service
    out=dict(resource_commits=0)
    stock=observe(app);out['inventory']=stock
    rows=stock.get('stacks') or []
    verified=stock.get('status')=='card_stacks_verified' and all(r.get('item_identity_verified') for r in rows)
    out['cards_after_verified']=bool(verified and sum(r['quantity'] for r in rows)==5
        and sum(r['quantity'] for r in rows if r['days']>=7)==5)
    if not stock.get('home_verified'):return dict(out,home_verified=False,reason='post_inventory_home_unverified')
    if not app.goto_sss_page():return dict(out,home_verified=False,reason='sss_home_unverified')
    context=app.discover_current_sss_context();out['context']=context
    out['rewards']=service(app,context['regions'])
    audit=out['rewards']
    if audit.get('home_verified') and all(type((audit.get('counts') or {}).get(k)) is int for k in ('strip','device')):
        prior=app.load_sss_progress()
        prior.update(area_period=context['area_period'],reward_cycle=context['reward_cycle'],
            reward_counts=audit['counts'],reward_service=audit,reward_capped=bool(audit.get('monthly_capped')),
            delegation_settlement_source=packet['sss_committed_receipt'])
        app.save_sss_progress(prior)
        out['progress_saved']=True
    out['home_verified']=app.goto_main_menu() is True and app.get_state()=='main_menu'
    out['status']='delegation_and_card_balance_verified' if out['cards_after_verified'] else 'card_balance_unverified_no_retry'
    return out
