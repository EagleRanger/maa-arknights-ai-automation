"""Monthly voucher planning only; never clicks or submits a shop purchase.

A native MAA shop pipeline is an executor, not proof of a complete affordable
bundle. Game observation and purchase reconciliation are separate adapters.
"""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
from unittest.mock import patch

CN=timezone(timedelta(hours=8))
COSTS=(10,18,40,70,120)
PULLS=(1,2,5,10,20)
POLICY=Path('runtime_state/voucher_exchange_policy.json')
OBSERVATION=Path('runtime_state/voucher_exchange_observation.json')


def period(now):
    if now.tzinfo is None:raise ValueError('timezone-aware time required')
    local=now.astimezone(CN)
    beginning=local.replace(day=1,hour=4,minute=0,second=0,microsecond=0)
    if local<beginning:
        beginning=(beginning-timedelta(days=1)).replace(day=1)
    following=(beginning.replace(day=28)+timedelta(days=4)).replace(day=1)
    return beginning.strftime('%Y-%m'),following.isoformat()


def yellow_plan(policy,observation,*,now=None):
    now=now or datetime.now(CN)
    cycle,next_refresh=period(now)
    result=dict(cycle=cycle,next_refresh=next_refresh,currency='yellow',
        goods='standard_headhunting_bundle',full_cost=sum(COSTS),full_pulls=sum(PULLS),
        resource_actions=0,purchase_execution='not_implemented_or_live_verified')
    if policy.get('yellow',{}).get('enabled') is not True:
        return dict(result,status='disabled')
    identity=policy.get('account')
    # Permanent/bought-this-cycle memory is account-bound, not global.
    previous=policy.get('yellow',{}).get('verified_complete') or {}
    if (identity and previous.get('account')==identity and previous.get('cycle')==cycle
            and previous.get('all_five_tiers_verified') is True and previous.get('evidence')):
        return dict(result,status='complete_until_refresh')
    if not identity or observation.get('account')!=identity:
        return dict(result,status='needs_account_bound_observation')
    if observation.get('cycle')!=cycle or observation.get('goods')!='standard_headhunting_bundle':
        return dict(result,status='needs_current_standard_shop_observation')
    try:
        observed=datetime.fromisoformat(observation['observed_at'])
        age=(now-observed).total_seconds() if observed.tzinfo else -1
    except (KeyError,TypeError,ValueError):age=-1
    if not 0<=age<=600:
        return dict(result,status='needs_fresh_observation')
    paid=observation.get('purchased_tiers')
    balance=observation.get('balance')
    # A known contiguous prefix is mandatory after an interrupted transaction.
    if (not isinstance(paid,list) or any(type(i) is not int for i in paid)
            or paid!=list(range(len(paid))) or len(paid)>5
            or type(balance) is not int or balance<0 or not observation.get('evidence')):
        return dict(result,status='needs_balance_and_tier_reconciliation')
    if len(paid)==5:return dict(result,status='all_tiers_observed_complete')
    remaining=list(range(len(paid),5));cost=sum(COSTS[i] for i in remaining)
    result.update(balance=balance,purchased_tiers=paid,remaining_tiers=remaining,
        remaining_cost=cost,remaining_pulls=sum(PULLS[i] for i in remaining))
    if balance<cost:return dict(result,status='save_for_complete_bundle',shortfall=cost-balance)
    return dict(result,status='complete_bundle_affordable',
        decision='eligible_for_native_executor_after_live_adapter_verification')


def service(root,*,now=None):
    root=Path(root)
    if not (root/POLICY).exists():return dict(status='not_configured',resource_actions=0)
    policy=json.loads((root/POLICY).read_text('utf-8'))
    observed=json.loads((root/OBSERVATION).read_text('utf-8')) if (root/OBSERVATION).exists() else {}
    return yellow_plan(policy,observed,now=now)


@contextmanager
def boundary(app):
    old=app.mode_daily;invoked=[False]
    def daily(enabled_tasks=None):
        ok=old(enabled_tasks=enabled_tasks)
        full=enabled_tasks is None or set(enabled_tasks)=={'StartUp','Infrast','Recruit','Mall','Award'}
        if ok is True and full and not invoked[0]:
            invoked[0]=True
            try:row=service(app.BASE)
            except Exception as exc:row=dict(status='planning_error',error=str(exc),resource_actions=0)
            app._RUN_SUMMARY['voucher_exchange_plan']=row
        return ok
    with patch.object(app,'mode_daily',daily):yield
