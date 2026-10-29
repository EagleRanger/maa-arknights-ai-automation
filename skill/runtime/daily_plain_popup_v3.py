"""Read current reconciled battle facts after final daily replaces Fight state."""
from contextlib import contextmanager
from unittest.mock import patch
import daily_plain_popup_v2 as previous
import daily_final_report_sink_v1 as sink

OLD_SUMMARY=previous.summary
OLD_EFFECTS=sink.effect_lines


def battle_lines(report):
    run=report.get('run_summary') or {};ledger=report.get('execution_accounting') or {}
    if (ledger.get('scope')!='current_run_only' or ledger.get('coverage')!='reconciled'
            or ledger.get('issues') or not ledger.get('boundary')
            or ledger['boundary']!=run.get('run_evidence_boundary')):return []
    rows={}
    for fact in ledger.get('facts') or []:
        if (fact.get('verified') is not True or fact.get('session_reconciled') is not True
                or fact.get('category')!='fight' or type(fact.get('runs')) is not int or fact['runs']<1
                or type(fact.get('net_cost')) is not int or fact['net_cost']<0
                or not fact.get('evidence') or not fact.get('stage')):continue
        row=rows.setdefault(fact['stage'],dict(runs=0,cost=0,drops={}))
        row['runs']+=fact['runs'];row['cost']+=fact['net_cost']
        for drop in fact.get('drops') or []:
            if type(drop.get('qty')) is int and drop['qty']>0:
                key=(drop.get('item_id'),drop.get('item'))
                row['drops'][key]=row['drops'].get(key,0)+drop['qty']
    result=[];choice=(run.get('event') or {}).get('farm_selection') or {}
    for stage,row in rows.items():
        result.append(f"本轮实际刷取：{stage}×{row['runs']}，消耗{row['cost']}理智。")
        main=[(name,qty) for (item,name),qty in row['drops'].items() if stage==choice.get('stage') and item==choice.get('drop_id')]
        if main:result.append('本轮主要材料到账：'+'、'.join(f'{name}×{qty}' for name,qty in main)+'。')
    return result


def summary(report):
    from daily_event_sanity_closure_v1 import validate_report
    report=validate_report(report)
    title,text,status=OLD_SUMMARY(report);lines=text.splitlines();actual=battle_lines(report)
    if actual:
        prefixes=('理智作战：','本次理智用于','今日理智用于')
        at=next((i for i,s in enumerate(lines) if s.startswith(prefixes)),3)
        lines=[s for s in lines if not s.startswith(prefixes)]
        lines[at:at]=actual
        run=report.get('run_summary') or {};prior=run.get('preserved_prior_farming') or {}
        if ((run.get('recovery_scope') or {}).get('source_sha256') and prior.get('status')=='completed'
                and type(prior.get('actual_runs')) is int and type(prior.get('sanity_consumed')) is int):
            lines.insert(at+len(actual),f"本轮续跑前已确认：{prior.get('stage')}×{prior['actual_runs']}，消耗{prior['sanity_consumed']}理智（不重复记为本轮新增）。")
    base=(report.get('run_summary') or {}).get('base_333') or {};receipt=base.get('execution_receipt') or {}
    base_ok=all(receipt.get(k) is True for k in ('config_loaded','products_verified','operator_rotation_verified','task_chain_completed'))
    if base and not base_ok:
        lines=[s.replace('基建换班','基建任务链（产品和换班仍待核验）') if s.startswith('日常已做：') else s for s in lines]
        lines=[s.replace('还有任务未完成，详情见同日完整报告','生产/贸易房间的产品与换班尚未核验') for s in lines]
    return title,'\n'.join(lines),status


def effect_lines(report):
    lines=OLD_EFFECTS(report);actual=battle_lines(report)
    if actual:
        lines=[s for s in lines if not s.startswith(('本次作战：','本次作战次数/消耗未确认'))]
        lines=actual+lines
    return lines


@contextmanager
def boundary():
    with patch.object(previous,'summary',summary),patch.object(sink,'effect_lines',effect_lines):yield
