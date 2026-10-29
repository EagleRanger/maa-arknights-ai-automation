"""Close a funded activity farm by live unit cost, including tail-time recovery."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


def target(summary):
    row=(summary.get('event') or {}).get('farm_selection') or {}
    if row.get('verified') is not True or not row.get('evidence') or type(row.get('cost')) is not int or row['cost']<=0:return None
    return row


def validate_report(report):
    choice=target(report.get('run_summary') or {})
    final=(report.get('stamina_validation') or {}).get('final') or {}
    value=report.get('final_stamina')
    if choice is None or final.get('verified') is not True or type(value) is not int or value<choice['cost']:return report
    result=deepcopy(report)
    result['unspent_stamina']=dict(balance=value,target=choice['stage'],unit_cost=choice['cost'],
        reason=f"仍可执行当前活动关{choice['stage']}（单次{choice['cost']}），不按固定21理智门槛判耗尽")
    result.update(workflow_completed=False,daily_all_ok=False,all_tasks_completed=False,overall_status='partial')
    result['domain_issues']=list(dict.fromkeys([*result.get('domain_issues',[]),f"剩余{value}理智仍够{choice['stage']}单次{choice['cost']}；理智尚未闭合"]))
    return result


def final_tail(app,original,packet=None,max_cycles=3):
    choice=target(app._RUN_SUMMARY)
    farm=(app._RUN_SUMMARY.get('event') or {}).get('farm') or {}
    # A standalone daily/base operation or a never-started farm cannot acquire
    # a stamina action merely by asking to finish its daily tail.
    if choice is None or not (type(farm.get('actual_runs')) is int and farm['actual_runs']>0):return original()
    record=app._RUN_SUMMARY.setdefault('activity_sanity_closure',dict(stage=choice['stage'],unit_cost=choice['cost'],checks=[],farm_phases=[deepcopy(farm)]))
    for cycle in range(max_cycles):
        if original() is not True:record['status']='daily_tail_failed';return False
        if app._maa_task_queue_running() is not False:record['status']='queue_not_idle';return False
        observation=app._capture_stamina_observation(f'post_daily_closure_{cycle}',navigate=True)
        record['checks'].append(observation)
        if observation.get('verified') is not True or type(observation.get('value')) is not int:
            record['status']='live_balance_unverified';return False
        if observation['value']<choice['cost']:
            record.update(status='below_current_unit_cost',final_balance=observation['value'])
            return True
        if cycle==max_cycles-1:
            record['status']='closure_cycle_limit';return False
        paused=any((app._RUN_SUMMARY.get(k) or {}).get('status') in ('paused','blocked') for k in ('flow_control','stamina_flow_control'))
        if paused or app._RUN_SUMMARY.get('page_attention') or not app._plan_allows('event_farm'):
            record['status']='stamina_action_not_admitted';return False
        if packet and datetime.now().astimezone()>=datetime.fromisoformat(packet['battle_not_after']):
            record['status']='battle_start_window_closed';return False
        event=app.get_active_event()
        if not event or event.get('name')!=(app._RUN_SUMMARY.get('event') or {}).get('name') or event.get('farm_stage')!=choice['stage']:
            record['status']='target_changed';return False
        app._DAILY_COMPLETION_NOT_BEFORE=datetime.now()
        funded=observation['value']//choice['cost']
        app.log(f"[理智闭合] 收尾后实读{observation['value']}，仍够{choice['stage']}最多{funded}份；同关补刷后再做一次战后收尾")
        if app.mode_event(stage_code=choice['stage'],times=funded) is not True:
            record['status']='funded_followup_not_verified';return False
        phase=deepcopy((app._RUN_SUMMARY.get('event') or {}).get('farm') or {})
        if type(phase.get('actual_runs')) is not int or phase['actual_runs']<=0:
            record['status']='followup_has_no_actual_battle';return False
        record['farm_phases'].append(phase)
        if app._RUN_SUMMARY.get('page_attention') or app.claim_event_task_rewards(event) is not True:
            record['status']='followup_activity_rewards_unverified';return False
    return False


@contextmanager
def boundary(app,packet=None):
    import daily_final_report_sink_v2 as sink
    import daily_final_report_sink_v1 as presentation
    tail,finish=app._run_full_final_daily_step,sink.finalize_file
    def close():return final_tail(app,tail,packet)
    close._live_unit_cost_closure=True
    def finalized(path,**kwargs):
        old=finish(path,**kwargs);new=validate_report(old)
        if new is not old:
            presentation.write_json(Path(path),new)
            Path(path).with_suffix('.md').write_text(presentation.markdown(new),encoding='utf-8')
        return new
    with patch.object(app,'_run_full_final_daily_step',close),patch.object(sink,'finalize_file',finalized):yield
