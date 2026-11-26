"""One player goal, with an explicit distinction between one-off and saved goals."""
import json
from pathlib import Path
import importlib.util
from functools import lru_cache

ROOT=Path(__file__).resolve().parent

@lru_cache(maxsize=1)
def selector():
    path=ROOT.parent/'scripts/select_module_presets.py'
    spec=importlib.util.spec_from_file_location('local_module_presets',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def resolve(v):
    name=v.get('operator');branch=v.get('module') or v.get('branch')
    level=v.get('target_level',1)
    if not isinstance(name,str) or not name.strip() or type(level)!=int or not 1<=level<=3:
        raise ValueError('需指定干员；不写目标等级默认为一阶')
    hits=[g for g in selector().library() if g['name']==name and (not branch or g['branch']==branch)]
    if len(hits)==1:
        g=hits[0]
        if v.get('module_title') not in (None,g['module_title']):raise ValueError('模组名称与分支不一致')
        return dict(name=name,branch=g['branch'],module_title=g['module_title'],target_level=level)
    import re
    if not isinstance(branch,str) or not re.fullmatch(r'[A-Z0-9]{2,6}-[A-ZΔ]',branch) or not v.get('module_title'):
        raise ValueError('无法唯一确定模组；请给出干员、具名分支和游戏中的模组名')
    return dict(name=name,branch=branch,module_title=v['module_title'],target_level=level)

def route(v):
    if set(v)-{'action','operator','module','branch','module_title','target_level','client','uid'}:
        raise ValueError('未知模组参数')
    if 'module' in v and 'branch' in v and v['module']!=v['branch']:raise ValueError('分支冲突')
    action=v.get('action','develop' if 'operator' in v else 'list')
    if action in ('list','inspect','next'):
        if set(v)-{'action'}:raise ValueError('查看清单/队列下一项不接收点名参数')
        return ('operator.modules' if action=='next' else 'module.list'),{}
    if action not in ('add','develop'):raise ValueError('模组动作：list、add、next、develop')
    goal=resolve(v)
    if action=='develop':
        if 'client' in v or 'uid' in v:raise ValueError('单项执行按当前实测账号，不使用传入账号')
        return 'module.one',goal
    return 'module.add',dict(goal=goal,client=v.get('client'),uid=v.get('uid'))

def offline(root,task,v):
    from operator_module_queue_v1 import overview
    if task=='module.list':
        return dict(queue=overview(root),available=[dict(operator=g['name'],branch=g['branch'],title=g['module_title']) for g in selector().library()],game_actions=0)
    path=root/'runtime_state/operator_development_plan.json'
    account=json.loads(path.read_text('utf-8-sig')).get('account',{}) if path.exists() else {}
    g=v['goal']
    added=selector().merge(root,[g],v.get('client') or account.get('client'),v.get('uid') or account.get('uid'))
    return dict(status='added' if added else 'already_listed',goal=g,game_actions=0)
