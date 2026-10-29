"""A missing Pure Gold row in the matching completed Depot is a zero, not unknown."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import hashlib,json
import daily_orundum_priority_v1 as priority

ROOT=Path(__file__).resolve().parent


def completed_sparse_gold(tip,raw):
    depot=(tip or {}).get('depot') or {};counts=depot.get('counts') or {};data=(raw or {}).get('data')
    if depot.get('fresh') is not True or raw.get('done') is not True or not isinstance(data,dict) or not data:return tip
    try:
        if datetime.fromisoformat(raw['syncTime'])!=datetime.fromisoformat(depot['sync_time']):return tip
    except (KeyError,TypeError,ValueError):return tip
    if '3003' in counts or '3003' in data:return tip
    # Two positive, directly present inputs and a matching full snapshot are
    # required. Null/partial/stale inventory is never promoted to zero.
    if any(type(counts.get(k)) is not int or counts[k]<=0 or data.get(k)!=counts[k] for k in ('30012','4001')):return tip
    result=deepcopy(tip);result['depot']['counts']['3003']=0
    result['depot']['zero_inferences']={'3003':'absent_in_matching_done_true_fresh_depot'}
    return result


@contextmanager
def boundary(app):
    original=priority.choose_orundum_priority_333_plan
    def choose(tip):
        normalized=tip
        try:
            path=Path(tip['source']['depot']).resolve();path.relative_to(ROOT)
            content=path.read_bytes();raw=json.loads(content.decode('utf-8-sig'))
            normalized=completed_sparse_gold(tip,raw)
            if normalized is not tip:
                app._RUN_SUMMARY.setdefault('base_333_policy',{})['inventory_zero_inferences']=dict(
                    item='3003',value=0,evidence=str(path),sha256=hashlib.sha256(content).hexdigest().upper(),
                    sync_time=tip['depot']['sync_time'],basis='matching_done_true_fresh_depot')
        except (KeyError,ValueError,OSError,TypeError):pass
        return original(normalized)
    with patch.object(priority,'choose_orundum_priority_333_plan',choose):yield
