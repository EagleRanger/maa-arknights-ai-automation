"""Upgrade only the confirmed module, one level at a time on the owned port."""
import argparse,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from account_progress_v1 import AccountProgress,uid_from_items
from feature_acceptance_transport_v1 import submit
from tools.read_operator_profile_trial import read

def quote(rows,target):
    if target not in (2,3):raise ValueError('unsupported level')
    prompt=any(re.fullmatch('确认将迟到的勋章升至'+str(target)+'级[?？]?',str(t)) and 1150<x<1880 and 800<y<940 for t,x,y in rows)
    if not prompt:raise ValueError('wrong module/level')
    needs=[];prices=[]
    for t,x,y in rows:
        if 980<y<1062 and x<1100:
            m=re.fullmatch(r'(\d+)/(\d+)',str(t))
            if m:needs.append((x,int(m[1]),int(m[2])))
            elif x>700 and str(t).isdigit():prices.append(int(t))
    if len(needs)!=4 or len(prices)!=1:raise ValueError('unverified material/trust/LMD rows')
    return sorted(needs),prices[0]

def run(out,target):
    h=json.loads((out/'receipt.json').read_text('utf-8'));fs=h['frames'];cur=fs[-1]
    from recipient_beta_v1 import module_plan,bound_host
    plan=module_plan(ROOT,'upgrade');bound_host(plan,h)
    if (h['status']!='awaiting_ai' or uid_from_items(fs[0]['items'])!=plan['account']['uid'] or
        (plan['operator'],plan['module'])!=('怒潮凛冬','HAM-X') or type(target) is not int or target not in (2,3) or target>plan['maximum_module_level']):
        raise ValueError('not the authorized account, operator or level')
    known=AccountProgress(ROOT/'runtime_state/accounts',plan['account']).decision(
        theme='OperatorProfile',capability=plan['operator']+':'+plan['module'].replace('-',''),revision='operator-detail-v1')
    if (known.get('fact') or {}).get('progress',0)>=target:
        print('verified_account_level_no_upgrade');return
    # Use most recent operator page, never another character's STAGE readout.
    prior=next(f for f in reversed(fs[:-1]) if any('RANK' in str(t) and 1700<x<1880 and 510<y<595 for t,x,y in f['items']))
    _,code,level=read(prior,'怒潮凛冬','Zimathe Raging Tide',3)
    if code!='HAMX' or level!=target-1:raise ValueError('need fresh view of previous level')
    needs,lmd=quote(cur['items'],target)
    if any(have<need for _,have,need in needs):raise ValueError('shortage: '+str(needs))
    intent=dict(target=target,previous=prior['path'],quote=cur['path'],costs=needs,lmd=lmd)
    with (out/f'module_level_{target}_intent.json').open('x',encoding='utf-8') as f:
        json.dump(intent,f,ensure_ascii=False,indent=2)
    submit(out,dict(action='tap',point=[1699,987],reason=f'confirmed HAM-X stage {target}; no other module'))
    print(json.dumps(intent,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('level',type=int,choices=[2,3]);a=p.parse_args()
    out=a.out.resolve();out.relative_to(ROOT/'outputs');run(out,a.level)
