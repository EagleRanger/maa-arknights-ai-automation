"""One explicit purchase on the existing acceptance port; no daily auto-spend."""
import argparse,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from feature_acceptance_transport_v1 import submit

def strings(items,x0,y0,x1,y1):
    return [str(t).replace(' ','') for t,x,y in items if x0<=x<=x1 and y0<=y<=y1]

def detail(items):
    def integer(pattern,rect):
        found=[int(m[1]) for t in strings(items,*rect) if (m:=re.fullmatch(pattern,t))]
        if len(found)!=1:raise ValueError('field not uniquely read: '+pattern)
        return found[0]
    if '芯片助剂' not in strings(items,100,200,800,400) or '芯片助剂' not in strings(items,1200,410,1540,515):raise ValueError('wrong product')
    return dict(balance=integer(r'(\d+)',(1620,25,1760,88)),owned=integer(r'已有(\d+)',(1460,270,1760,380)),
        price=integer(r'售价(\d+)',(1170,270,1490,380)),qty=integer(r'(\d+)',(1310,600,1430,700)),
        total=integer(r'总计支付(\d+)',(1120,720,1550,830)))

def run(out,mode):
    host=json.loads((out/'receipt.json').read_text('utf-8'));frames=host['frames'];current=frames[-1]
    if mode=='submit' and host['status']!='awaiting_ai':raise ValueError('no live owner')
    from recipient_beta_v1 import catalyst_plan,bound_host
    plan=catalyst_plan(ROOT);identity=bound_host(plan,host)
    if mode not in ('submit','verify'):raise ValueError('invalid mode')
    marker=out/'red_purchase_intent.json'
    if mode=='submit':
        if not (len(frames)>=2 and '芯片助剂' in strings(frames[-2]['items'],350,180,1850,720) and
                any('采购凭证兑换说明' in t for t in strings(frames[-2]['items'],0,950,600,1080))):raise ValueError('not verified red shop')
        before=detail(current['items'])
        if not (before['price']==before['total']==90 and before['qty']==1 and before['balance']>=90):raise ValueError('not one at 90 red')
        buy=[(x,y) for t,x,y in current['items'] if t=='购买物品' and 1160<x<1590 and 810<y<930]
        if len(buy)!=1:raise ValueError('unique confirmation required')
        # Reserve this explicit purchase across restarts. If submission is
        # uncertain, reconcile the original out directory; never auto-repeat.
        store=ROOT/'runtime_state'/'voucher_intents';store.mkdir(parents=True,exist_ok=True)
        with (store/(plan['request_id']+'.json')).open('x',encoding='utf-8') as f:
            json.dump(dict(account=identity,session=str(out),seq=current['seq']),f,ensure_ascii=False)
        with marker.open('x',encoding='utf-8') as f:json.dump(dict(account=identity,before=before,seq=current['seq'],proof=current['path']),f,ensure_ascii=False,indent=2)
        submit(out,dict(action='tap',point=list(buy[0]),reason='single authorized chip catalyst at 90 red'))
    else:
        intent=json.loads(marker.read_text('utf-8'));before=intent['before']
        if intent.get('account')!=identity:raise ValueError('purchase intent belongs to a different account')
        for current in frames:
            if current['seq']<=intent['seq']:continue
            try:after=detail(current['items'])
            except ValueError:continue
            if after['balance']==before['balance']-90 and after['owned']==before['owned']+1:break
        else:raise ValueError('not reconciled; do not repurchase')
        proof=dict(status='verified',quantity=1,goods='芯片助剂',before=before,after=after,
                   evidence=[intent['proof'],current['path']],green_or_yellow_spent=False)
        (out/'red_purchase_verified.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(proof,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['submit','verify']);p.add_argument('output',type=Path)
    a=p.parse_args();out=a.output.resolve();out.relative_to(ROOT/'outputs');run(out,a.mode)
