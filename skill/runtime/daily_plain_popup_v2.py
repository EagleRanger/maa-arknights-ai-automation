"""Present actual per-mode effects and specific pending work, not vague failure."""
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch
import re
import daily_plain_popup_v1 as previous

OLD_SUMMARY=previous.summary


def mode_progress(report):
    run=report.get('run_summary') or {};event=run.get('event') or {}
    if event.get('name')!='昨日海':return None
    start=(run.get('run_evidence_boundary') or {}).get('initialized_at')
    try:start=datetime.fromisoformat(start).replace(tzinfo=None)
    except (ValueError,TypeError):start=None
    current=[];known={};scheduled=run.get('event_mode_schedule') or []
    historical=(event.get('checkpoint_hint') or {}).get('historical_stages') or {}
    for code,row in {**historical,**(event.get('stages') or {})}.items():
        if not re.fullmatch(r'YW(?:-EX)?-[1-8]',code):continue
        for mode,record in (row.get('modes') or {}).items():
            if mode not in ('normal','challenge'):continue
            accepted=record.get('status')=='cleared' and bool(record.get('successful_job') or record.get('verified') is True)
            known[(code,mode)]=accepted
            try:when=datetime.fromisoformat(record['updated_at']).replace(tzinfo=None)
            except (KeyError,TypeError,ValueError):when=None
            if accepted and start is not None and when is not None and when>=start:current.append((code,mode))
    pending=[(s['stage'],s['mode']) for s in scheduled if re.fullmatch(r'YW-EX-[1-8]',str(s.get('stage'))) and not known.get((s['stage'],s['mode']))]
    return current,list(dict.fromkeys(pending))


def label(pair):return pair[0]+('突袭' if pair[1]=='challenge' else '普通三星')


def summary(report):
    title,text,status=OLD_SUMMARY(report);lines=text.splitlines();run=report.get('run_summary') or {}
    progress=mode_progress(report)
    if progress is not None:
        done,pending=progress
        lines=[s for s in lines if not s.startswith('活动昨日海：')]
        at=next((i for i,s in enumerate(lines) if s.startswith('基建')),len(lines)-1)
        lines.insert(at,'活动本轮确认：'+('、'.join(map(label,done)) if done else '本轮未新增首通；保留先前已过进度')+'。')
    else:pending=[]
    specific=[]
    if pending:specific.append('关卡待办：'+'、'.join(map(label,pending)))
    unspent=report.get('unspent_stamina') or {}
    if type(unspent.get('balance')) is int:specific.append(f"剩余{unspent['balance']}理智尚未完成活动刷取")
    notice=run.get('base_notification_cleanup') or {}
    if notice and not notice.get('complete'):
        items=[t for step in notice.get('steps',[]) for t,x,y in step.get('items',[])]
        if any('回收站产物已领取' in str(t) for t in items):specific.append('材料已领取，但奖励展示关闭/返回未核验')
        else:specific.append('基建通知检查未完成：'+str(notice.get('reason','尚未确认')))
    if (report.get('run_summary',{}).get('event',{}).get('task_rewards') or {}).get('status') in ('failed','unverified','deferred') or any('活动任务领奖' in str(v) for v in report.get('domain_issues',[])):
        specific.append('活动任务奖励领取尚未核验')
    security=run.get('security') or {}
    if security and security.get('status') not in ('completed','skipped_weekly_complete'):
        specific.append('保全派驻仍有未完成奖励，不重复已完成日常')
    if specific:
        lines=[s for s in lines if not s.startswith('待处理：')]
        lines.insert(max(1,len(lines)-1),'待处理：'+'；'.join(specific)+'。')
    daily=all((report.get('chain_status',{}).get(k) or {}).get('completed') is True and (report.get('chain_status',{}).get(k) or {}).get('ok') is True for k in previous.sink.CHAINS)
    if daily and status!='verified':
        title='明日方舟：日常已完成，另有待处理项';lines[0]=title
    if run.get('preserved_prior_copilot_costs'):
        receipt=run['preserved_prior_copilot_costs']
        lines.insert(2,f"此前已核实开荒：{receipt['completed_modes']}场，消耗{receipt['gross_cost']}理智（不计为本轮新增）。")
    return title,'\n'.join(lines),status


@contextmanager
def boundary():
    with patch.object(previous,'summary',summary):yield
