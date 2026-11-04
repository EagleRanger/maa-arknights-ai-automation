"""Confirm X geometry and polarity; home currency + is not a close button."""
from contextlib import contextmanager
from unittest.mock import patch
import daily_login_supply_v3 as previous
import event_signin_generic_v3 as generic

ORIGINAL_CLOSE=generic.close_point


def is_cross(path,point):
    from PIL import Image
    import numpy as np
    try:
        with Image.open(path) as im:
            if im.size!=(1920,1080):return False
            a=np.asarray(im.convert('L'))
        x,y=map(round,point)
        if x<20 or y<20 or x+20>=a.shape[1] or y+20>=a.shape[0]:return False
        light=float(np.median(a[y-2:y+3,x-2:x+3]))>=140
        mask=a>=140 if light else a<=130
        def avg(xx,yy):return float(mask[yy-1:yy+2,xx-1:xx+2].mean())
        diagonal=[avg(x+s*i,y+t*i) for i in range(9,17) for s in (-1,1) for t in (-1,1)]
        axes=[avg(x+s*i,y) for i in range(9,17) for s in (-1,1)]
        axes += [avg(x,y+s*i) for i in range(9,17) for s in (-1,1)]
        return sum(diagonal)/len(diagonal)>=.65 and sum(axes)/len(axes)<=.35
    except (OSError,ValueError,TypeError):
        return False


def close_point(path,items):
    point=ORIGINAL_CLOSE(path,items)
    return point if point and is_cross(path,point) else None


@contextmanager
def boundary(app):
    old=app.ocr
    def read(path):
        rows=old(path);result=[]
        for t,x,y in rows:
            if (str(t).strip().upper() in ('X','×','✕') and 1300<x<1910 and 80<y<260
                    and not is_cross(path,(x,y))):
                result.append(('未核关闭符号',x,y))
            else:result.append((t,x,y))
        return result
    with patch.object(app,'ocr',read),patch.object(generic,'close_point',close_point),previous.boundary(app):
        yield
