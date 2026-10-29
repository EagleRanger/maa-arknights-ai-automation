"""Normalize the observed header decoration, never stage digits or prices."""
from contextlib import contextmanager
from unittest.mock import patch
import re
import copilot_visual_usage_v3 as previous

OLD_DETAIL=previous.detail_cost


def normalize(items):
    result=[]
    for text,x,y in items:
        match=re.fullmatch(r'((?:O?PERATION\s*)?YW-EX-[1-8])[°º]',str(text).strip()) if x>1200 and 90<y<230 else None
        result.append((match[1] if match else text,x,y))
    return result


def detail_cost(path,items,engine):return OLD_DETAIL(path,normalize(items),engine)


@contextmanager
def boundary():
    with patch.object(previous,'detail_cost',detail_cost):yield
