"""Read the visible YW multiplier from bounded overlapping views, not a guess.

Four fixed recognition views tolerate minor frame/antialiasing variation. At
least two strong readings must agree; any other strong reading vetoes them.
The independently pinned unit cost validates, but never supplies, the glyph.
"""
import hashlib
import json
import re
import unicodedata

from stage_sanity_cost_yw_v1 import CATALOG, CATALOG_SHA, consensus


VIEWS = [((1480,871,1552,909),2), ((1480,871,1552,909),3),
         ((1476,865,1556,914),2), ((1476,865,1556,914),3)]


def vote(total, readings, expected):
    strong=[]
    for text, score in readings:
        if float(score)<.55:
            continue
        text=unicodedata.normalize('NFKC',str(text)).strip().lower().replace('x','×')
        # A confident non-multiplier is disagreement too; never cherry-pick.
        if not re.fullmatch(r'×\s*(?:[1-9]|10)',text):
            return None
        strong.append((text.replace(' ',''),float(score)))
    if len(strong)<2 or len({t for t,s in strong})!=1:
        return None
    result=consensus(total,strong[:2],expected)
    if result:
        result.update(multiplier_readings=[(str(t),float(s)) for t,s in readings],
                      agreeing_views=len(strong))
    return result


def read_cost(path, items, recognizer):
    codes={str(t).strip().upper() for t,x,y in items if x>=1200 and 90<=y<=230
           and re.fullmatch(r'YW-[1-8]',str(t).strip().upper())}
    totals={str(t).strip() for t,x,y in items if x>=1600 and y>=1000
            and re.fullmatch(r'[-−–]\s*\d{1,4}',str(t).strip())}
    if (len(codes)!=1 or len(totals)!=1 or recognizer is None
        or not any(x>=1550 and 930<=y<=1030 and '开始行动' in str(t) for t,x,y in items)
        or not any(1550<=x<=1900 and 840<=y<=930 and '代理指挥' in str(t) for t,x,y in items)):
        return None
    raw=CATALOG.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper()!=CATALOG_SHA:return None
    code=next(iter(codes))
    costs=[s['apCost'] for s in json.loads(raw)['stages'] if s['code']==code]
    if len(costs)!=1 or type(costs[0]) is not int:return None
    from PIL import Image,ImageOps
    import numpy as np
    with Image.open(path) as source:
        if source.size!=(1920,1080):return None
        source=source.convert('RGB')
        readings=[]
        for box,scale in VIEWS:
            crop=source.crop(box).resize(((box[2]-box[0])*scale,(box[3]-box[1])*scale))
            crop=ImageOps.expand(crop,border=20,fill='black')
            rows,_=recognizer([np.asarray(crop)[:,:,::-1].copy()])
            if len(rows)==1:readings.append(rows[0])
    result=vote(next(iter(totals)),readings,costs[0])
    if result:
        result.update(basis='current_visible_multiplier_consensus_plus_pinned_YW_cost',
                      evidence=str(path),stage=code,expected_cost=costs[0],catalog_sha256=CATALOG_SHA)
    return result
