"""Independent activity operations. Return results; never advance or close a day."""
from copy import deepcopy
from ..core import Result
from ..runtime_session import blocked


def stage(session, inputs, context, previous, operation):
    event = session.event(inputs)
    if not event: return blocked('本期活动未绑定已验目录')
    name, layer = inputs['stage'], inputs['layer']
    if inputs.get('kind') == 'story':
        from event_story_audit_v1 import complete_named_story
        receipt = complete_named_story(session.app, event, name)
        ok = receipt.get('status') in ('played_and_returned_verified', 'already_read_verified')
        return Result('succeeded' if ok else 'partial', '剧情节点独立完成核验' if ok else '剧情未闭环',
                      (receipt['evidence'],) if receipt.get('evidence') else (), receipt)
    matches = [s for s in session.app._event_execution_stages(event) if s.get('display') == name]
    if len(matches) != 1 or layer not in session.app._event_stage_modes(event, matches[0]):
        return blocked('关卡或层次不在当前已验目录')
    raw = session.app.clear_event_stage(event, matches[0], mode=layer)
    if not session.queue_idle(): return Result('unknown', '本关仍在任务内，未抢控验证')
    if layer == 'challenge':
        clear = session.app.verify_event_challenge_cleared(event, name) is True
    else:
        result = session.app.verify_event_stage_cleared(event, name)
        clear = result == (True, True)
    return session.proof(clear, '该关该层完美完成已回读' if clear else '本关未完美完成，未自动换关',
                      {'stage': name, 'layer': layer, 'worker_return': raw}, tag='stage')


def rewards(session, inputs, context, previous, operation):
    event = session.event(inputs)
    if not event: return blocked('活动奖励目录未确认')
    if event.get('stage_prefix') == 'YW':
        from ..event_rewards import claim_yw
        return claim_yw(session.app, event)
    session.app.claim_event_task_rewards(event)
    row = deepcopy((session.app._RUN_SUMMARY.get('event') or {}).get('task_rewards') or {})
    ok = row.get('status') in ('claimed_verified', 'all_claimed_verified', 'no_claimable_rewards_verified')
    proof = row.get('evidence')
    return Result('succeeded' if ok and proof else 'partial', '活动奖励领取已核验' if ok and proof else '活动奖励仍待核验',
                  (str(proof),) if proof else (), row)
