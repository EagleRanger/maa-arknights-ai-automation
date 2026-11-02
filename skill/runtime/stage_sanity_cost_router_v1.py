"""Use the strict YW reader only on YW; retain normal on-screen costs elsewhere."""
from contextlib import contextmanager
from unittest.mock import patch
import re
import stage_sanity_cost_yw_v3 as special
from stage_sanity_cost_v2 import read_cost as normal_cost


def route(original,path,items,recognizer):
    codes={str(t).strip().upper() for t,x,y in items if 1200<=x<=1680 and 90<=y<=230
           and re.fullmatch(r'(?:[A-Z0-9]{1,8}-){1,3}[0-9]{1,3}',str(t).strip().upper())}
    if len(codes)!=1:return original(path,items,recognizer)
    code=next(iter(codes))
    if re.fullmatch(r'YW-[1-8]',code):return original(path,items,recognizer)
    result=normal_cost(path,items,recognizer)
    return dict(result,stage=code) if result else None


@contextmanager
def boundary():
    # The execution recovery installer imports this symbol inside its final
    # context and binds all three readers to it. Fix the actual late consumer.
    original=special.read_cost
    with patch.object(special,'read_cost',lambda p,i,r:route(original,p,i,r)):
        yield
