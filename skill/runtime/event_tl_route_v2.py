"""Keep zoned authority times but adapt the legacy local-naive date consumer."""
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch
import event_tl_route_v1 as previous

ORIGINAL_PROFILE=previous.profile

def profile(*args,**kwargs):
    result=ORIGINAL_PROFILE(*args,**kwargs)
    if not result:return result
    result['activity_window']=dict(start_at=result['start'],end_at=result['end'],timezone='Asia/Shanghai')
    for name in ('start','end'):
        result[name]=datetime.fromisoformat(result[name]).astimezone().replace(tzinfo=None).isoformat()
    return result

@contextmanager
def boundary():
    with patch.object(previous,'profile',profile):yield
