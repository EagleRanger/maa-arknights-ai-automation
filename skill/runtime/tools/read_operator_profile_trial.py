"""Only read an already saved, identified operator page. No game input."""
import argparse,json,re,sys
from pathlib import Path
from statistics import median
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from account_progress_v1 import AccountProgress,uid_from_items
from ark_modules.core import ReceiptStore

def read_masteries(row,name,alias,slots):
    items=row['items']
    def text(rect):
        l,t,r,b=rect;return {str(s).strip() for s,x,y in items if l<=x<=r and t<=y<=b}
    if not ({name,alias}-{''}) & text((0,670,625,865)):raise ValueError('operator not identified')
    if not ({'专精','MAX'} & text((1680,575,1880,655))) or not any('RANK7'==t.replace(' ','').upper() for t in text((1700,510,1880,598))): raise ValueError('not the supported skill-card layout')
    with Image.open(row['path']) as im:
        if im.size!=(1920,1080) or slots not in (2,3):raise ValueError('unknown card geometry')
        im=im.convert('RGB');masteries=[]
        for x in (1342,1473,1605)[:slots]:
            values=[]
            for dx,y in ((0,511),(-5,522),(6,522)):
                pts=[im.getpixel((x+dx+a,y+b)) for a in (-1,0,1) for b in (-1,0,1)]
                med=tuple(median(p[k] for p in pts) for k in range(3))
                if max(med)-min(med)>10:raise ValueError('unclassified coloured mastery dot')
                if min(med)>210:values.append(1)
                elif 52<=min(med)<=90:values.append(0)
                else:raise ValueError('unclassified mastery dot: do not infer level')
            masteries.append(sum(values))
    return list(masteries)

def read(row,name,alias,slots):
    masteries=read_masteries(row,name,alias,slots)
    def text(rect):
        l,t,r,b=rect
        return {str(s).strip() for s,x,y in row['items'] if l<=x<=r and t<=y<=b}
    badge=text((1700,775,1880,842));stage=[int(m[1]) for t in badge if (m:=re.fullmatch(r'STAGE\s*([123])',t,re.I))]
    code=[t.upper() for t in text((1580,828,1745,895)) if re.fullmatch(r'[A-Z]{2,4}[- ]?[XYDΔ]',t.upper())]
    if len(stage)!=1 or len(code)!=1:raise ValueError('equipped module identity or level unclear')
    return list(masteries),code[0].replace(' ','').replace('-',''),stage[0]

def persist(out,seq,name,alias,slots):
    h=json.loads((out/'receipt.json').read_text('utf-8'));frames=h['frames']
    planpath=ROOT/'runtime_state/operator_module_plan.json';from recipient_beta_v1 import module_plan,bound_host
    plan=module_plan(ROOT,'inspect');identity=bound_host(plan,h)
    homes=[f for f in frames if uid_from_items(f['items'])==identity['uid']]
    if len(homes)<2:raise ValueError('account identity not established')
    row=next(f for f in frames if f['seq']==seq)
    masters,code,stage=read(row,name,alias,slots)
    store=AccountProgress(ROOT/'runtime_state/accounts',identity)
    def save(cap,n,total):
        previous=store.decision(theme='OperatorProfile',capability=name+':'+cap,revision='operator-detail-v1').get('fact') or {}
        if previous.get('progress',0)>n:
            raise ValueError('older or conflicting operator page; preserve verified progress')
        store.remember_verified(theme='OperatorProfile',capability=name+':'+cap,revision='operator-detail-v1',
            progress=n,total=total,terminal_verified=n==total,run_id=str(out),evidence=[row['path']],identity_evidence=[f['path'] for f in homes[:2]])
    for i,m in enumerate(masters,1):save('S'+str(i),m,3)
    save(code,stage,3)
    if name==plan['operator'] and code==plan['module'].replace('-','') and stage>=1:
        act=plan.setdefault('actual_progress',{})
        act.update(module_unlocked=True,module_level=stage,module_level_evidence=row['path'])
        history=act.setdefault('level_evidence',{})
        for prior in frames:
            if prior['seq']>=seq:break
            if not any(str(t).strip()==name and 0<=x<=625 and 670<=y<=865 for t,x,y in prior['items']):continue
            try:_,prior_code,prior_stage=read(prior,name,alias,slots)
            except (ValueError,OSError):continue
            if prior_code==code and prior_stage<=stage:history.setdefault(str(prior_stage),prior['path'])
        if '1' in history:act['unlock_evidence']=history['1']
        if stage==1:act['unlock_evidence']=row['path']
        history[str(stage)]=row['path']
        if stage==plan.get('maximum_module_level'):
            plan['status']='verified_named_module_at_target'
        ReceiptStore(planpath).save(plan)
    print(name,masters,code,stage)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('seq',type=int);p.add_argument('name');p.add_argument('alias');p.add_argument('slots',type=int)
    a=p.parse_args();out=a.out.resolve();out.relative_to(ROOT/'outputs');persist(out,a.seq,a.name,a.alias,a.slots)
