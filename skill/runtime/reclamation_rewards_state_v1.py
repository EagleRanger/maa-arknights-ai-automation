"""Prosperity exchange evidence, separate from roguelike level claiming.

This parser never clicks or starts farming. Positive-balance item selection
remains an explicit AI-assisted branch until its detail/confirmation is tested.
"""
import re
from navigation_text_v1 import key


def state(rows):
    labels=[key(t) for t,x,y in rows]
    page=(key('繁荣馈赠') in labels and key('开始演算') not in labels and
          (key('EXPANSIONALREWARDS') in labels or key('扩充结束') in labels))
    values={int(str(t).strip()) for t,x,y in rows if 1780<x<1910 and y<130
            and re.fullmatch(r'\d+',str(t).strip())}
    balance=next(iter(values)) if len(values)==1 else None
    sold=[(int(x),int(y)) for t,x,y in rows if key(t)==key('售罄') and y>300]
    # This only proves no exchange is affordable now; not all historical tiers.
    no_points=page and balance==0 and bool(sold)
    return dict(page=page,points=balance,visible_sold_out=len(sold),
                no_exchange_now=no_points,positive_exchange_verified=False)


def verified_exchange(before,after,*,item_changed=False,reward_reveal=False):
    a,b=before.get('points'),after.get('points')
    return (before.get('page') is True and after.get('page') is True and
            type(a) is int and type(b) is int and 0<=b<a and
            (item_changed is True or reward_reveal is True))
