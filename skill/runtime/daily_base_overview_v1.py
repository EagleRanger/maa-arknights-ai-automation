"""Recognize a horizontally panned base without requiring Control-center text."""
from contextlib import contextmanager
from unittest.mock import patch


def overview(items):
    def anchor(label,box):
        a,b,c,d=box
        return any(str(t).strip()==label and a<=x<=c and b<=y<=d for t,x,y in items)
    if not (anchor('进驻总览',(20,120,400,250)) and anchor('建造模式',(20,260,400,360))
            and anchor('OFF',(180,260,400,360))):return False
    text=' '.join(str(t) for t,x,y in items if 450<x<1500 and 300<y<900)
    if any(k in text for k in ('确认升级','是否','离开罗德岛基建','网络连接','获得物资')):return False
    utilities=('会客室','加工站','办公室','训练室','回收站','宿舍','活动室','制造站','贸易站','发电站')
    hits={label for label in utilities if any(str(t).startswith(label) and 230<y<1030 for t,x,y in items)}
    return len(hits)>=3


@contextmanager
def boundary(app):
    old=app.get_state
    def state():
        seen=[];original=app.ocr
        def observe(path):
            items=original(path);seen.append((str(path),items));return items
        with patch.object(app,'ocr',observe):value=old()
        if value=='unknown' and seen and overview(seen[-1][1]):
            app._RUN_SUMMARY.setdefault('base_overview_corrections',[]).append(dict(evidence=seen[-1][0],reason='spatial_overview_anchors',original=value))
            return 'base'
        return value
    with patch.object(app,'get_state',state):yield
