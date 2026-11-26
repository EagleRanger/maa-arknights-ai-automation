"""Paradox-only catalogue / job binding for the prepared game owner.

Roster visibility, unlock and completion belong to the account UI. Static
resources are used solely to disambiguate a discovered operator and stage.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlencode


def compact(text):
    return re.sub(r'\s+','',str(text))


def catalogue(maa_root):
    root=Path(maa_root)/'resource'
    chars=json.loads((root/'battle_data.json').read_text('utf-8-sig'))['chars']
    names={}
    for k,v in chars.items():
        m=re.fullmatch(r'char_\d+_(\w+)',k)
        if m:names.setdefault(m[1],set()).add(v['name'])
    tile=root/'Arknights-Tile-Pos'
    maps=json.loads((tile/'overview.json').read_text('utf-8-sig'))
    result={}
    for row in maps.values():
        key=row.get('stageId','')
        m=re.fullmatch(r'mem_(\w+)_\d+',key)
        if not m or len(names.get(m[1],()))!=1 or row.get('code')!=key:continue
        file=(tile/row['filename']).resolve()
        if not file.is_relative_to(tile.resolve()) or not file.is_file():continue
        result[key]={'stage':key,'title':row['name'],'operator':next(iter(names[m[1]]))}
    return result


def exact_job(job, target):
    if not re.fullmatch(r'mem_\w+_\d+',target['stage']) or job.get('stage_name')!=target['stage']:
        raise ValueError('作业与悖论地图不一致')
    if not isinstance(job.get('actions'),list) or not job['actions']:raise ValueError('作业没有战斗动作')
    opers=list(job.get('opers') or [])
    for group in job.get('groups') or []:opers.extend(group.get('opers') or [])
    picks={o.get('skill',1) for o in opers if o.get('name')==target['operator']}
    if len(picks)>1 or any(type(p) is not int or p not in (1,2,3) for p in picks):
        raise ValueError('作业技能不唯一')
    return next(iter(picks),1)  # native ParadoxRecognitionTask default


def card_candidates(rows, maps, *, card_width, card_height):
    """Join visible pending labels to one operator on the same roster card.

    A sort badge/count proves neither that a particular card is open nor that
    the account owns every catalogue entry. Ambiguous neighbours stay unknown.
    """
    by_name={}
    for t in maps.values():by_name.setdefault(compact(t['operator']),[]).append(t)
    norm=[(compact(t),x,y) for t,x,y in rows]
    labels=[(s,x,y) for s,x,y in norm if s in by_name]
    candidates=[]
    for state,x,y in norm:
        if state not in ('未通过','未完成','未通关','已解锁未通关','已解锁未完成'):continue
        nearby=[(s,a,b) for s,a,b in labels if abs(x-a)<card_width/2 and abs(y-b)<card_height/2]
        if len(nearby)!=1:continue
        name,a,b=nearby[0]
        if len(by_name[name])!=1 or any(
            text in ('未解锁','已完成','已通关') and abs(a-xx)<card_width/2 and abs(b-yy)<card_height/2
            for text,xx,yy in norm):continue
        candidates.append(dict(target=by_name[name][0],point=(round(a),round(b)),status=state))
    return candidates


def sorted_roster(rows):
    """Read the game's own sort drawer or active top sort; counts never choose a card."""
    rows=[(compact(t),x,y) for t,x,y in rows]
    header=any('等级'==s and 1150<x<1480 and y<95 for s,x,y in rows)
    sort=[(x,y) for s,x,y in rows if '悖论模拟' in s and 1470<x<1790 and y<180]
    if not header or not sort:return None
    drawer=any(s=='获取时间' and x>1480 and y<280 for s,x,y in rows)
    cards=[(x,y) for s,x,y in rows if re.fullmatch(r'[○〇O口]?未通过',s)
           and 35<x<(1470 if drawer else 1900) and (505<y<585 or 985<y<1055)]
    return dict(drawer=drawer,sort=sort[-1],cards=sorted(set(cards),key=lambda pt:(pt[1]>800,pt[0])))


def detail_target(rows,maps):
    if any(compact(t)=='悖论模拟' and x>1440 and 70<y<185 for t,x,y in rows):
        titles={compact(t) for t,x,y in rows if x>1300 and 160<y<260}
        found=[v for v in maps.values() if compact(v['title']) in titles]
        return found[0] if len(found)==1 else None
    # A different game layout may land on the operator profile instead.
    found={s for t,x,y in rows if 0<=x<=680 and 660<=y<=935 for s in (compact(t),)}
    matches=[target for target in maps.values() if compact(target['operator']) in found]
    return matches[0] if len(matches)==1 else None


def discover_one(app, maps):
    """Navigate from home or the roster, using the native sort and live card label."""
    from operator_home_labels_v1 import is_home
    evidence=[]
    def read(tag):
        path=app.shot('paradox_'+tag); evidence.append(str(path));return app.ocr(path)
    def press(point):
        if not app._RUN_MUTEX_HANDLE or app._maa_task_queue_running() is not False:
            raise ValueError('设备或队列已换手')
        app.tap(*point);app.wait(1.6)
    def one(rows,labels,box):
        l,t,r,b=box
        hits=[(x,y) for s,x,y in rows if compact(s) in labels and l<x<r and t<y<b]
        return hits[0] if len(hits)==1 else None
    seen=set()
    for _ in range(8):
        rows=read('roster')
        if is_home(rows):
            tag='home';point=one(rows,{'干员'},(1310,390,1700,640))
        else:
            sort=sorted_roster(rows)
            if sort and sort['drawer']:
                tag='close' if sort['cards'] else 'sort'
                point=one(rows,{'X','×','x'},(1750,0,1920,105)) if sort['cards'] else sort['sort']
            elif sort and sort['cards']:
                point=sort['cards'][0]
                press(point);detail=read('operator');target=detail_target(detail,maps)
                for _ in range(2):
                    if target or sorted_roster(detail) or app._maa_task_queue_running() is not False:break
                    app.wait(.8);detail=read('operator_settle');target=detail_target(detail,maps)
                return dict(target=target,point=point,
                            visible_pending=len(sort['cards']),evidence=evidence)
            elif sort:
                # The custom slot remembers its label across logins even when
                # “等级” is the active sort. Select the visible header first.
                tag='activate_saved_sort';point=sort['sort']
            else:
                header=one(rows,{'等级'},(1150,0,1470,100)) and one(rows,{'稀有度'},(1380,0,1530,100))
                tag='menu';point=one(rows,{'...','…','···'},(1550,0,1800,110)) if header else None
        if point is None or tag in seen:break
        seen.add(tag);press(point)
    return dict(target=None,evidence=evidence,reason='live_roster_or_pending_card_unverified')


def find_job(target,output,fetch):
    """Search by the game's stage title, download and recheck exact mem id/actions."""
    query=urlencode(dict(page=1,limit=30,desc='true',orderBy='hot',document=target['title']))
    found=fetch('https://prts.maa.plus/copilot/query?'+query)
    if found.get('status_code')!=200:raise ValueError('作业查询未成功')
    choices=[]
    for row in found['data']['data']:
        try:
            j=json.loads(row['content']);i=int(row['id'])
            if row.get('available') is True and i>0 and j.get('stage_name')==target['stage']:
                choices.append((row.get('uploader')=='自在道爷',float(row.get('rating_ratio') or 0),
                                float(row.get('hot_score') or 0),i))
        except (ValueError,TypeError,KeyError):continue
    for _,__,___,i in sorted(choices,reverse=True)[:5]:
        response=fetch(f'https://prts.maa.plus/copilot/get/{i}')
        row=response.get('data') or {}
        if response.get('status_code')!=200 or row.get('available') is not True or row.get('id')!=i:continue
        try:j=json.loads(row['content']);skill=exact_job(j,target)
        except (ValueError,TypeError,KeyError):continue
        out=Path(output);out.mkdir(parents=True,exist_ok=True)
        file=out/f"{target['stage']}-{i}.json"
        if file.exists():
            if json.loads(file.read_text('utf-8'))!=j:raise ValueError('当前作业版本与已保存证据不同')
        else:
            with file.open('x',encoding='utf-8') as f:json.dump(j,f,ensure_ascii=False,indent=2)
        return dict(id=i,stage=target['stage'],file=str(file),skill=skill)
    return None


def start_selected(app,target,filename,output):
    """Bind the title on the detail page and the skill on the following page, in one owner."""
    from maa_utility_custom_v1 import _submit
    if not app._RUN_MUTEX_HANDLE or app._maa_task_queue_running() is not False:raise ValueError('设备不归本控制器')
    official=catalogue(app._maa_install_root()).get(target['stage'])
    if not official or official!=target:raise ValueError('干员与地图未绑定')
    file=Path(filename).resolve(strict=True)
    skill=exact_job(json.loads(file.read_text('utf-8-sig')),target)
    frame=app.shot('paradox_before_native_start')
    rows=app.ocr(frame)
    buttons=[(x,y) for t,x,y in rows if compact(t)=='开始模拟' and x>1640 and y>900]
    if (len(buttons)!=1 or any('已完成模拟作战' in compact(t) for t,_,_ in rows)
            or detail_target(rows,{target['stage']:target})!=target
            or not any(compact(t)==compact(target['title']) and x>1300 and 160<y<260 for t,x,y in rows)):
        raise ValueError('悖论关卡标题或详情入口未确认，未启动MAA')
    def press(point):
        if not app._RUN_MUTEX_HANDLE or app._maa_task_queue_running() is not False:raise ValueError('设备或队列已换手')
        app.tap(*point);app.wait(1.5)
    press(buttons[0])
    menu=app.shot('paradox_choose_job_skill')
    labels=app.ocr(menu)
    # The game's skill picker displays no stage title. Read all three skill
    # slots, then verify the blue Start button is on the job-selected row.
    def slots(items):
        return [[(compact(t),x,y) for t,x,y in items if 395<x<585 and abs(y-row_y)<27
                 and re.search(r'[\u4e00-\u9fff]',t)] for row_y in (355,665,976)]
    choices=slots(labels)
    if not all(len(s)==1 for s in choices):raise ValueError('技能面板未确认，未启动 MAACore')
    label,x,y=choices[skill-1][0]
    press((round(x),round(y)))
    after=app.shot('paradox_skill_ready')
    fresh=app.ocr(after)
    ready=[(xx,yy) for t,xx,yy in fresh if compact(t)=='开始模拟' and 1440<xx<1635 and abs(yy-(y-52))<45]
    if len(ready)!=1 or [[s[0] for s in slot] for slot in slots(fresh)]!=[[s[0] for s in slot] for slot in choices] or app._maa_task_queue_running() is not False:
        raise ValueError('目标技能行的开始模拟未确认；不提交作业')
    before=getattr(app,'_paradox_before_submit',None)
    if before is not None:before(target,file,after)
    return _submit(app,'ParadoxCopilot',{'filename':str(file)},'paradox',output,timeout=540)


def one_module(session,inputs,context,previous,operation):
    from ark_modules.core import Result
    from uuid import uuid4
    app=session.app
    if inputs: return Result('blocked','单关测试自动选未通过者，不接受点名或额外战斗参数')
    maps=catalogue(app._maa_install_root())
    passed=[r.data['target'] for r in previous.values() if r.status=='succeeded' and isinstance(r.data.get('target'),dict)
            and (r.data.get('native') or {}).get('kind')=='paradox']
    if passed:
        if not app._RUN_MUTEX_HANDLE or app._maa_task_queue_running() is not False:
            return Result('blocked','上一关后尚未取得独占空闲现场')
        last=app.ocr(app.shot('paradox_previous_settled'))
        if ('已完成模拟作战' in {compact(s) for s,_,_ in last}
                and detail_target(last,maps)==passed[-1]):
            app.back();app.wait(1.6)
    choice=discover_one(app,maps)
    data=dict(choice);proof=list(choice['evidence']);target=choice.get('target')
    if not target:return Result('partial','未形成未通过卡片与干员/关卡的对应证据',tuple(proof),data)
    if any(v.get('operator')==target['operator'] or v.get('stage')==target['stage'] for v in passed):
        return Result('partial','候选与本次已验关卡重复；未开战，不计新样本',tuple(proof),data)
    out=Path(session.output)/('paradox_'+uuid4().hex)
    job=find_job(target,out/'jobs',app._fetch_prts_json);data['job']=job
    if not job:return Result('partial','未找到该悖论地图的可执行作业',tuple(proof),data)
    native=start_selected(app,target,job['file'],out/'native');data['native']=native
    proof.append(native['callbacks'])
    frame=app.shot('paradox_settlement');proof.append(str(frame))
    settled=clear_verified(native,target,app.ocr(frame))
    return Result('succeeded' if settled else 'partial',
                  target['operator']+' · '+target['title']+(' 已核实结算' if settled else ' 尚未确认游戏结算'),
                  tuple(proof),data)


def clear_verified(native,target,rows):
    if native.get('status')!='native_completed_effect_pending' or native.get('timed_out'):return False
    words={compact(t) for t,_,_ in rows}
    if words & {'行动失败','代理失败','模拟失败','MISSIONFAILED'}:return False
    return (detail_target(rows,{target['stage']:target})==target and
            bool(words & {'已完成模拟作战','已通过','首次通关奖励已领取'})) or (
            'MISSIONACCOMPLISHED' in words or '模拟成功' in words)
