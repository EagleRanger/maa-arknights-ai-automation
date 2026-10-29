"""Correct the proven EP-substring home misroute using the same frame."""
from contextlib import contextmanager
from unittest.mock import patch


def home_anchors(items):
    regions={'终端':(1300,100,1600,420),'基建':(1300,800,1660,1050),
        '任务':(1000,800,1370,1050),'采购中心':(1100,620,1400,850),
        '公开招募':(1400,650,1690,850),'仓库':(1670,830,1910,1040)}
    hits=set()
    for t,x,y in items:
        label=str(t).replace(' ','')
        if label in regions:
            a,b,c,d=regions[label]
            if a<=x<=c and b<=y<=d:hits.add(label)
    return '终端' in hits and len(hits)>=5


@contextmanager
def boundary(app):
    original=app.get_state
    def state():
        frames=[];shot=app.shot
        def capture(*args,**kwargs):
            p=shot(*args,**kwargs)
            if args and args[0]=='state':frames.append(p)
            return p
        with patch.object(app,'shot',capture):value=original()
        if value=='terminal_list' and frames:
            path=frames[-1]
            if home_anchors(app.ocr(path)):
                app._RUN_SUMMARY.setdefault('home_state_corrections',[]).append(dict(evidence=str(path),
                    original=value,corrected='main_menu',reason='five_spatial_home_anchors_not_EP_substring'))
                return 'main_menu'
        return value
    with patch.object(app,'get_state',state):yield
