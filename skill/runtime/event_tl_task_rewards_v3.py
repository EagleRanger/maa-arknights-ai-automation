"""Reuse the TL claim flow; repair navigation text before its real consumer."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import event_tl_task_rewards_v1 as old
from navigation_text_v1 import Target, key, same_label, recover
from ocr_tolerance_v1 import navigation_home

HOME = {'采购中心': (1080,600,1420,825), '公开招募': (1380,650,1660,840),
        '基建': (1320,780,1680,1040), '仓库': (1650,800,1910,1060),
        '干员': (1330,410,1650,610), '编队': (1000,410,1320,620),
        '终端': (1300,100,1600,420)}
BANNER = Target(old.NAME, (1500,160,1880,350))
LOBBY = Target(old.LABEL, (1470,260,1910,540))
HEADER = Target(old.LABEL, (550,0,1130,105))


def cosmetic(rows):
    out=[]
    for text,x,y in rows:
        for label,(l,t,r,b) in HOME.items():
            if l<=x<=r and t<=y<=b and same_label(text,label):
                text=label;break
        out.append((text,x,y))
    return out


def scene(rows):
    if navigation_home(cosmetic(rows)):
        return BANNER
    joined=key(''.join(str(t) for t,x,y in rows))
    if key('作战结束时间') in joined and key('战时新闻委员会') in joined:
        return LOBBY
    if 'requirement' in joined and ('rewards' in joined or 'process' in joined):
        return HEADER
    return None


@contextmanager
def boundary(app):
    original=app.ocr
    original_home=old.is_home
    def read(path,*args,**kwargs):
        rows=original(path,*args,**kwargs)
        if not Path(str(path)).name.startswith('tl_tasks_'):
            return rows
        rows=cosmetic(rows); target=scene(rows)
        if target:
            rows=recover(app,path,rows,target,original,lambda r:scene(r)==target)
            rows=cosmetic(rows)
            # Only navigation anchors; never rewrite claim text or numbers.
            for label in ('作战结束时间','战时新闻委员会','REQUIREMENT','REWARDS','PROCESS'):
                rows=[(label if same_label(t,label) else t,x,y) for t,x,y in rows]
        return rows
    with patch.object(app,'ocr',read),patch.object(old,'is_home',lambda r:navigation_home(cosmetic(r)) or original_home(r)):
        yield


def run_composed(operation,app):
    import run_daily as engine
    original=engine.main
    def main(*args,**kwargs):
        with boundary(app):return original(*args,**kwargs)
    with patch.object(engine,'main',main):return operation()
