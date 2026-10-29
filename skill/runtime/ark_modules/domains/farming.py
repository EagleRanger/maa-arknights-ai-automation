"""Independent farming operations. Return results; never advance or close a day."""
from ..orchestration import valid_proof
from ..core import Result
from ..runtime_session import blocked


def farm(session, inputs, context, previous, operation):
    event = session.event(inputs)
    if not event: return blocked('活动目录缺失，不替代为芯片')
    if session.app._configure_new_event_farm_from_live_inventory(event) is not True:
        return Result('partial', '当前库存、关卡三星或单次消耗未核验，不开战')
    selection = (session.app._RUN_SUMMARY.get('event') or {}).get('farm_selection') or {}
    if (selection.get('verified') is not True or not selection.get('evidence')
            or type(selection.get('cost')) is not int or selection['cost'] <= 0
            or selection.get('stage') != event['farm_stage']):
        return Result('partial', '活动主掉落选择缺证，不开战')
    raw = session.app.mode_event(stage_code=event['farm_stage'], times=99)
    return farm_receipt(session, event['farm_stage'], selection.get('cost'), raw)


def farm_receipt(session, stage, cost, raw):
    if not session.queue_idle(): return Result('unknown', '刷取队列未结束')
    balance = session.app._capture_stamina_observation('module_farm_final', navigate=True)
    if not isinstance(balance, dict):
        balance = session.app._RUN_SUMMARY.get('stamina_observations', {}).get('module_farm_final', {})
    # Report actual settlements separately. This condition only certifies
    # that no further run of the chosen stage can use remaining sanity.
    ok = (balance.get('verified') is True and type(cost) is int and cost > 0
          and type(balance.get('value')) is int and 0 <= balance['value'] < cost)
    return Result('succeeded' if ok else 'partial', '本关剩余理智不足一次' if ok else '理智闭合仍待核验',
                  (str(balance['evidence']),) if balance.get('evidence') else (),
                  {'stage': stage, 'unit_cost': cost, 'final_balance': balance, 'worker_return': raw,
                   'battle_effects_source': 'current_run_execution_accounting'})


def resource(session, inputs, context, previous, operation):
    if (inputs.get('policy_admitted') is not True or type(inputs.get('unit_cost')) is not int
            or inputs['unit_cost'] <= 0 or not valid_proof(inputs, session.now())):
        return blocked('资源路线或消耗未绑定当前库存决策')
    raw = session.app.mode_resource(stage_code=inputs['stage'], times=99)
    return farm_receipt(session, inputs['stage'], inputs['unit_cost'], raw)
