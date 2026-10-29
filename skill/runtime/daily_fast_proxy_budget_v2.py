"""Cap an AUTO queue to fresh detail-page affordability, not an arbitrary99.

AUTO still selects up to10 per batch. This fixes the observed redundant fifth
Start/medicine dialog after4 fundedYW4 runs; no refill flag is enabled.
"""
from contextlib import contextmanager
from unittest.mock import patch


def affordable_limit(stage, requested, plan):
    if (plan.get('stage') != stage or not plan.get('evidence')
            or type(requested) is not int or requested < 1):
        return None
    balance = plan.get('sanity')
    cost = (plan.get('cost_reading') or {}).get('unit_cost')
    if type(balance) is not int or balance < 0 or type(cost) is not int or cost <= 0:
        return None
    # Never pass0 to a native field where it may mean unlimited. The existing
    # no-sanity path retains ownership of pre-start insufficient-balance cases.
    funded = balance // cost
    return min(requested, funded) if funded > 0 else None


@contextmanager
def boundary():
    import daily_fast_proxy_yw_v1 as previous
    original_install = previous.install
    saved=[]

    def install(app):
        result=original_install(app)
        configure=app._configure_fight
        saved.append((app,configure))
        def limited(cfg,stage,times,*args,**kwargs):
            plan=(app._RUN_SUMMARY.get('event') or {}).get('native_batch_plan') or {}
            limit=affordable_limit(stage,times,plan)
            if limit is not None:
                plan.update(requested_limit=times,affordable_queue_limit=limit)
                app.log(f'[连续代理预算] 本次最多{limit}份，保留AUTO每批最多10；到数直接结束，不再试点补药页')
                times=limit
            return configure(cfg,stage,times,*args,**kwargs)
        app._configure_fight=limited
        return result
    try:
        with patch.object(previous,'install',install):
            yield
    finally:
        for app,configure in reversed(saved):
            app._configure_fight=configure
