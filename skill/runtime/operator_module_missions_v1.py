"""Named module inspection and constrained mission battle; no daily/cleanup.

An already three-star chapter is not proof of this operator's mission. Reuse
the existing chapter/formation/Copilot/result primitives, then re-read modules.
"""
import json
from pathlib import Path
from operator_optional_inspection_v1 import frame

def inspect(app,output):
    from operator_optional_inspection_v1 import module
    result=module(app,output)
    if result['status']!='module_button_needs_ai':return result
    rows=result['page']['items']
    # Actual module-management block also labels a still-original certificate
    # as ORIGINAL / STAGE -, not literally 模组. No upgrade button is used.
    anchors=any(str(t)=='ORIGINAL' and 1550<x<1750 and 760<y<930 for t,x,y in rows)
    choices=[(x,y) for t,x,y in rows if '管理' in str(t) and 1700<x<1900 and 760<y<930]
    if anchors and len(choices)==1:
        app.tap(*choices[0]);app.wait(2)
        result.update(status='module_management_observed',module_page=frame(app,output,'module_management'),
                      actual_module_progress=None,module_upgrade_requested=False)
    return result

def validate_job(data,operator,roles):
    if data.get('stage_name') not in {'main_16-05','main_16-05#s'} or not data.get('actions'):
        raise ValueError('exact normal 16-6 job with actions required')
    opers=data.get('opers') or []
    if not any(o.get('name')==operator for o in opers):raise ValueError('own mission operator must be explicit')
    candidates=opers+[o for g in data.get('groups',[]) for o in g.get('opers',[])]
    for op in candidates:
        name=op.get('name')
        if name not in roles:raise ValueError('unknown job profession: '+str(name))
        if name!=operator and roles[name] in {'WARRIOR','TANK'}:
            raise ValueError('mission excludes other guards/defenders: '+name)
    if not any(a.get('type')=='Deploy' and a.get('name')==operator for a in data['actions']):
        raise ValueError('mission operator deployment absent')
    return True

def battle(app,job_path,output):
    # Legacy direct entry must use the same recipient policy and fresh mission readback.
    from operator_module_missions_v2 import run
    return run(app,job_path,output)
