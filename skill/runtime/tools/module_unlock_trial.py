"""Submit only the explicitly named HAM-X stage-one unlock on a verified frame."""
import argparse,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from account_progress_v1 import uid_from_items
from feature_acceptance_transport_v1 import submit
from operator_module_missions_v2 import requirements

def eligible(rows):
    if not requirements(rows).get('missions_complete'):return False
    prompt=''.join(str(t) for t,x,y in rows if 1150<x<1870 and 820<y<930)
    if '是否解锁迟到的勋章' not in prompt:return False
    costs=[(t,x) for t,x,y in rows if 980<y<1060 and x<900]
    def enough(lo,hi,need):
        pairs=[re.fullmatch(r'(\d+)/'+str(need),str(t)) for t,x in costs if lo<x<hi]
        return any(m and int(m[1])>=need for m in pairs)
    return (enough(80,225,60) and enough(260,450,4) and enough(485,625,2)
            and any(str(t)=='80000' and 695<x<850 for t,x in costs))

def run(out):
    h=json.loads((out/'receipt.json').read_text('utf-8')); frame=h['frames'][-1]
    from recipient_beta_v1 import module_plan,bound_host
    plan=module_plan(ROOT,'unlock');bound_host(plan,h)
    if not (h['status']=='awaiting_ai' and uid_from_items(h['frames'][0]['items'])==plan['account']['uid'] and
            plan['maximum_module_level']>=1 and
            (plan['operator'],plan['module'])==('怒潮凛冬','HAM-X') and eligible(frame['items'])):
        raise ValueError('do not unlock: identity, stage-one prompt, costs or completed tasks not verified')
    with (out/'module_stage_one_intent.json').open('x',encoding='utf-8') as f:
        json.dump(dict(operator=plan['operator'],module=plan['module'],target=1,proof=frame['path'],seq=frame['seq']),f,ensure_ascii=False)
    submit(out,dict(action='tap',point=[1699,987],reason='verified named module stage-one checkmark'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args()
    out=a.out.resolve();out.relative_to(ROOT/'outputs');run(out)
