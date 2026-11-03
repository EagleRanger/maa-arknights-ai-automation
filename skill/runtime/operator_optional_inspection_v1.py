"""Current named module and voucher-page observations, no upgrades/purchases."""
import json
from pathlib import Path
import shutil


def frame(app,out,tag):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    source=Path(app.shot(tag));dest=out/(tag+'.png');shutil.copy2(source,dest)
    return dict(screenshot=str(dest),items=app.ocr(str(dest)))


def module(app,output):
    from operator_readonly_locator_v1 import run
    from recipient_beta_v1 import module_plan
    from operator_home_labels_v1 import observe_account
    root=Path(app.BASE);packet=module_plan(root,'inspect');identity,_=observe_account(app)
    if identity!=packet['account']:return dict(status='account_unverified_or_mismatch')
    chars=json.loads((Path(app.MAA_ROOT)/'resource/battle_data.json').read_text('utf-8'))['chars']
    found=[row for row in chars.values() if row.get('name')==packet['operator']]
    roles={'WARRIOR':'Warrior','PIONEER':'Pioneer','MEDIC':'Medic','TANK':'Tank','SNIPER':'Sniper',
           'CASTER':'Caster','SUPPORT':'Support','SPECIAL':'Special'}
    if len(found)!=1 or found[0].get('profession') not in roles:raise ValueError('operator role not uniquely resolved')
    out=Path(output);result=run(app,packet['operator'],roles[found[0]['profession']],out/'locator')
    result['page']=frame(app,out,'operator_page')
    if result['status']!='operator_page_located':return result
    points=[(x,y) for t,x,y in result['page']['items'] if '模组' in str(t) and x>1300 and y>650]
    if len(points)!=1:return dict(result,status='module_button_needs_ai',actual_module_progress=None)
    app.tap(*points[0]);app.wait(2)
    result.update(status='module_page_observed_progress_needs_review',module_page=frame(app,out,'module_page'),
                  actual_module_progress=None,module_upgrade_requested=False)
    return result


def vouchers(app,output):
    out=Path(output);result=dict(status='voucher_navigation_unverified',pages=[],purchases=0)
    if not app.goto_main_menu():return result
    home=frame(app,out,'shop_home')
    choices=[(x,y) for t,x,y in home['items'] if '采购中心' in str(t)]
    if len(choices)!=1:return dict(result,evidence=home)
    app.tap(*choices[0]);app.wait(2);entry=frame(app,out,'shop_entry')
    choices=[(x,y) for t,x,y in entry['items'] if '凭证交易所' in str(t)]
    if len(choices)!=1:return dict(result,evidence=entry)
    app.tap(*choices[0]);app.wait(2);latest=frame(app,out,'voucher_entry')
    for label in ('资质凭证区','高级凭证区','采购凭证区'):
        choices=[(x,y) for t,x,y in latest['items'] if label in str(t)]
        if len(choices)!=1:
            result['pages'].append(dict(label=label,status='tab_needs_ai',evidence=latest));continue
        app.tap(*choices[0]);app.wait(1.5);latest=frame(app,out,label)
        result['pages'].append(dict(label=label,status='observed_balance_needs_review',evidence=latest))
    result['status']='voucher_pages_observed_no_purchases'
    return result
