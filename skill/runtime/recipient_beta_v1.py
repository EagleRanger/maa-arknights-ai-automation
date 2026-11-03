"""Opt-in recipient policies. No account, target or spending defaults ship."""
import json
import re
from pathlib import Path
from account_progress_v1 import account,uid_from_items
from operator_home_labels_v1 import is_home

# Tested capability identifier, never an implicit target for the recipient.
SUPPORTED=('怒潮凛冬','char_1051_headb2','HAM-X')
ACTIONS={'inspect','mission_battle','unlock','upgrade'}
def private(root,name):
    path=Path(root)/'runtime_state'/name
    if not path.is_file():raise ValueError('optional feature not configured: '+name)
    obj=json.loads(path.read_text('utf-8-sig'))
    if not isinstance(obj,dict) or obj.get('enabled') is not True:raise ValueError('optional feature not enabled')
    return obj

def identity(plan):
    v=plan.get('account')
    if not isinstance(v,dict):raise ValueError('explicit recipient account required')
    return account(v.get('client'),v.get('uid'))

def bound_host(plan,host):
    expected=identity(plan)
    frames=host.get('frames') or []
    if (host.get('client')!=expected['client'] or not frames or not is_home(frames[0]['items'])
        or uid_from_items(frames[0]['items'])!=expected['uid']):
        raise ValueError('recipient account or game client unverified')
    return expected

def module_plan(root,action):
    p=private(root,'operator_module_plan.json')
    identity(p)
    if tuple(p.get(k) for k in ('operator','character_id','module'))!=SUPPORTED:
        raise ValueError('unsupported module Beta; do not substitute a tested character')
    actions=p.get('actions')
    if not isinstance(actions,list) or any(type(s) is not str or s not in ACTIONS for s in actions) or action not in actions:
        raise ValueError('module action not enabled in recipient plan')
    if action in ('unlock','upgrade') and (type(p.get('maximum_module_level')) is not int or not 1<=p['maximum_module_level']<=3):
        raise ValueError('explicit maximum module level 1..3 required')
    return p

def catalyst_plan(root):
    p=private(root,'red_catalyst_plan.json')
    identity(p)
    if not isinstance(p.get('request_id'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',p['request_id']):
        raise ValueError('one explicit local purchase request_id required')
    if (p.get('product')!='芯片助剂' or p.get('currency')!='采购凭证' or
        type(p.get('quantity')) is not int or p['quantity']!=1 or
        type(p.get('max_total')) is not int or p['max_total']!=90):
        raise ValueError('supported Beta scope is one chip catalyst for 90 red vouchers')
    return p
