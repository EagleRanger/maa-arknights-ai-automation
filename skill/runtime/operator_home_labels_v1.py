"""Normalize a proved OCR script variant only in the actual home-entry ROI."""
from contextlib import contextmanager
from unittest.mock import patch


def is_home(rows):
    # Terminal typography is intentionally not a condition. Multiple unrelated
    # navigation cards plus the account block identify the current home layout.
    from account_progress_v1 import uid_from_items
    regions={'采购中心':(1080,600,1420,825),'公开招募':(1380,650,1660,840),
        '基建':(1320,780,1680,1040),'仓库':(1650,800,1910,1060),
        '干员':(1330,410,1650,610),'编队':(1000,410,1320,620)}
    hits=set()
    for t,x,y in rows:
        label=str(t).strip().replace('編隊','编队')
        if label in regions:
            a,b,c,d=regions[label]
            if a<=x<=c and b<=y<=d:hits.add(label)
        if 500<x<1450 and 300<y<800 and any(s in label for s in ('确认退出','确定退出','离开罗德岛','确认升级')):
            return False
    return bool(uid_from_items(rows) and len(hits)>=4)


def observe_account(app):
    from account_progress_v1 import account,uid_from_items
    frames=[];uids=[]
    for _ in range(2):
        path=str(app.shot('development_account_identity'));rows=app.ocr(path)
        if not is_home(rows):return None,[]
        frames.append(path);uids.append(uid_from_items(rows));app.wait(.3)
    if uids[0]!=uids[1] or frames[0]==frames[1]:return None,[]
    return account(app.PKG,uids[0]),frames


def normalize(rows):
    return [('终端' if str(t).strip()=='終端' and 1300<=x<=1600 and 100<=y<=420 else t,x,y)
            for t,x,y in rows]


@contextmanager
def boundary(app):
    original=app.ocr
    old_home=getattr(app,'goto_main_menu',None)
    def read(*args,**kwargs):return normalize(original(*args,**kwargs))
    def go_home():
        p=app.shot('development_home_probe')
        if is_home(read(p)):
            app._RUN_SUMMARY.setdefault('development_home_evidence',[]).append(str(p))
            return True
        return old_home()
    with patch.object(app,'ocr',read):
        if old_home is None:yield
        else:
            with patch.object(app,'goto_main_menu',go_home):yield
