"""List public recommendations or merge the recipient's explicit selections. No game I/O."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile

SKILL=Path(__file__).resolve().parents[1]
PRESET=SKILL/'templates/zizai-idle-development.example.json'


def library():
    return json.loads(PRESET.read_text(encoding='utf-8-sig'))['module_library']


def choices(names,all_items):
    out=[];wanted={}
    if all_items and names:raise ValueError('--all 与单项选择不可混用')
    for name in names:
        token,sep,value=name.partition('=')
        if sep and value not in ('1','2','3'):raise ValueError('目标等级只支持 1、2、3')
        if token in wanted:raise ValueError('重复选择：'+token)
        wanted[token]=int(value) if sep else 1
    for item in library():
        token=item['name']+':'+item['branch']
        if all_items or token in wanted:
            out.append({k:item[k] for k in ('name','branch','module_title')} |
                       dict(target_level=wanted.pop(token,1),job_id=item['source_jobs'][0]))
    if wanted:raise ValueError('库中没有指定干员与分支：'+', '.join(wanted))
    return out


def merge(base,selected,client,uid):
    if not selected or not client or not re.fullmatch(r'[0-9]{6,12}',uid or ''):
        raise ValueError('写入需要明确的选择、客户端标识与本人 UID')
    path=base/'runtime_state/operator_development_plan.json'
    identity=dict(client=client,uid=uid)
    raw=path.read_bytes() if path.exists() else None
    plan=json.loads(raw.decode('utf-8-sig')) if raw is not None else dict(schema_version=1,account=identity,module_order=[])
    if plan.get('account')!=identity:raise ValueError('账号不匹配，原计划未改')
    queue=plan.setdefault('module_order',[])
    if not isinstance(queue,list):raise ValueError('现有模组队列不是列表')
    if queue and plan.get('module_queue_enabled') is not True:
        raise ValueError('已有停用的私人队列；先由本人核对是否恢复，不因添加预设而自动启用')
    existing={(g['name'],g['branch']) for g in queue}
    additions=[g for g in selected if (g['name'],g['branch']) not in existing]
    if not additions:return []
    queue.extend(additions);plan['module_queue_enabled']=True
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
            temp=Path(f.name);json.dump(plan,f,ensure_ascii=False,indent=2);f.write('\n')
        if (path.read_bytes() if path.exists() else None)!=raw:raise ValueError('写入前计划已变化，未覆盖')
        os.replace(temp,path)
    finally:
        if temp:temp.unlink(missing_ok=True)
    return additions


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--select',action='append',default=[],metavar='干员:分支[=等级]')
    p.add_argument('--all',action='store_true')
    p.add_argument('--apply',action='store_true')
    p.add_argument('--client');p.add_argument('--uid')
    p.add_argument('--runtime-root',type=Path)
    a=p.parse_args(argv)
    selected=choices(a.select,a.all)
    if not selected and not a.apply:
        for i,g in enumerate(library(),1):
            print(f"{i:2}. {g['name']}:{g['branch']}　{g['module_title']}　默认一阶　作业 "+
                  '、'.join(str(j) for j in g['source_jobs']))
        return
    if not a.apply:
        print('预览（未写入）：',json.dumps(selected,ensure_ascii=False));return
    base=a.runtime_root or Path(os.environ.get('ARKNIGHTS_AUTO_BASE') or SKILL/'runtime')
    if not base.is_dir():p.error('未找到本地执行根目录')
    added=merge(base,selected,a.client,a.uid)
    print(f'已新增 {len(added)} 项；已有顺序与等级原样保留。没有打开游戏。')


if __name__=='__main__':main()
