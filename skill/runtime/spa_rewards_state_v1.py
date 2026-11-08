"""SPA Regulation rewards observation; no farming or purchases on inspection.

Use on the caller's fresh 1920x1080 OCR rows. The shop is NOT a level-reward
track. Missing currency OCR stays unknown and requests a local reread.
"""
import re
from navigation_text_v1 import key


def inspect(rows):
    labels=[key(str(t)) for t,x,y in rows]
    has=lambda text:any(key(text) in label for label in labels)
    shop=has('限时兑换') and has('累计消耗') and any(has(t) for t in (
        '剩余','模组数据块','晶体电子单元','晶体电路'))
    targets=has('关键目标') and any(has(t) for t in ('PROCESS','REQUIREMENT','通过第','通关1次'))
    lobby=has('功勋兑换处') and any(has(t) for t in ('极速模拟','独立模拟','搜寻队友'))
    dialog=all(has(t) for t in ('售价','商品内容','购买数量','总计支付'))
    currency_rect=((1760,15,1880,115) if dialog else
                   (150,968,235,1018) if lobby else (1490,15,1600,115))
    left,top,right,bottom=currency_rect
    nums={int(str(t).strip()) for t,x,y in rows
          if left<=x<=right and top<=y<=bottom and re.fullmatch(r'\d+',str(t).strip())}
    balance=next(iter(nums)) if (shop or dialog or lobby) and len(nums)==1 else None
    claim=[(int(x),int(y)) for t,x,y in rows
           if key(str(t)) in {key('领取'),key('领取奖励'),key('一键领取'),key('全部领取')}
           and x>700 and y>140]
    page='purchase_dialog' if dialog else 'shop' if shop else 'targets' if targets else 'lobby' if lobby else 'unknown'
    return dict(page=page,balance=balance,visible_claim_buttons=claim,
                next_action='reread_currency_roi' if (shop or dialog or lobby) and balance is None else
                            'validate_item_quantity_and_budget' if dialog else
                            'no_exchange_affordable_now' if shop and balance==0 else
                            'apply_account_exchange_plan' if shop else
                            'inspect_claim_buttons' if targets and claim else
                            'inspect_remaining_targets' if targets else 'navigate_rewards' if lobby else 'needs_ai',
                currency_roi=list(currency_rect) if (shop or dialog or lobby) and balance is None else None,
                all_rewards_complete=False,purchases=0)


def observe(app, path, rows):
    """Read-only, bounded local OCR fallback; never infers zero or clicks."""
    from ocr_tolerance_v1 import line_items
    values=list(rows); state=inspect(values); evidence=[]
    if state['currency_roi']:
        for scale in (2,3):
            extra=line_items(app,path,state['currency_roi'],scale=scale)
            evidence.append(dict(scale=scale,items=extra))
            candidate=inspect(values+extra)
            if candidate['balance'] is not None:
                state=candidate;break
    return dict(state,local_currency_reads=evidence)


def verified_purchase(before,after,*,item_remaining_before=None,item_remaining_after=None,reward_reveal=False):
    a,b=before.get('balance'),after.get('balance')
    stock=(type(item_remaining_before) is int and type(item_remaining_after) is int
           and 0<=item_remaining_after<item_remaining_before)
    return (before.get('page')=='shop' and after.get('page')=='shop'
            and type(a) is int and type(b) is int and 0<=b<a
            and (stock or reward_reveal is True))


def verified_claim(*,before_claimable,after_claimable,reward_reveal=False):
    return (type(before_claimable) is int and type(after_claimable) is int
            and 0<=after_claimable<before_claimable and reward_reveal is True)
