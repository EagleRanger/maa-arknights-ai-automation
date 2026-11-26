"""Thin bindings to shipped business functions. No second game algorithm."""
from pathlib import Path
from dataclasses import asdict
import importlib
import json

from ark_modules.core import Result
from ark_modules.operations import BY_NAME as BUSINESS, Operation
from ark_modules.progress_operations_v1 import BY_NAME as PROGRESS
from ark_modules.runtime_session import RuntimeSession
from receiver_catalog_v1 import CHAINS, validate


def structured(session, task, row, *, good=()):
    """Preserve raw evidence/status; a callback alone never becomes completion."""
    if not isinstance(row, dict):
        row = dict(return_value=row)
    status = row.get('status', 'effect_requires_review')
    evidence = []
    for frame in row.get('pages', []):
        if isinstance(frame, dict) and frame.get('screenshot'):
            evidence.append(frame['screenshot'])
    evidence.append(str(session.app.shot('receiver_' + task.replace('.', '_'))))
    return Result('succeeded' if status in good else 'partial', status, tuple(evidence), row)


def chain(session, inputs, context, previous, task):
    from ark_modules.daily_tasks import PreparedDailyQueue
    from ark_modules.domains.base import base_config_current
    name = CHAINS[task]
    app = session.app
    port = PreparedDailyQueue(app, session.output / task,
        base_plan_ready=lambda: base_config_current(app._RUN_SUMMARY.get('base_333') or {}),
        base_effect_verified=lambda: ((app._RUN_SUMMARY.get('base_333') or {}).get(
            'execution_receipt') or {}).get('status') == 'applied_verified', clock=session.now)
    blocked = port.preflight((name,))
    if blocked:
        return blocked
    if app.goto_main_menu() is not True:
        return Result('partial', '当前单项尚未到首页，保留现场')
    row = port.execute_daily_chains((name,)).get(name) or {}
    ok = row.get('verified') is True and bool(row.get('evidence'))
    return Result('succeeded' if ok else 'partial', name + ('已核验' if ok else '待核验'),
                  (row['evidence'],) if row.get('evidence') else (), row)


def extra(session, inputs, context, previous, task):
    app, out = session.app, session.output / (str(session.sequence) + '-' + task)
    if task in ('goal.event', 'goal.event_farm', 'goal.activity_rewards'):
        event = session.event(inputs) if inputs.get('event') else app.get_active_event()
        if task == 'goal.activity_rewards':
            from event_signin_discovery_v6 import service
            signin = service(app)
            if not event:
                return structured(session, task, dict(signin, event_tasks='no_active_event'), good=('checked',))
        elif not event:
            return Result('skipped', '当前没有有效活动，不替换为其它关卡')
        if not isinstance(event, dict) or not event.get('name'):
            return structured(session, task, dict(status='active_event_requires_ai', observed_event=event))
        session.events[event['name']] = event
        app.ACTIVE_EVENTS.insert(0, event)
        selected = dict(inputs, event=event['name'])
        if task == 'goal.event_farm':
            return session.execute('activity.farm', selected, context)
        results = []
        route_verified = task != 'goal.activity_rewards' or signin.get('status') == 'checked'
        if task == 'goal.event':
            names = set(inputs.get('stages') or [])
            candidates = list(app._event_execution_stages(event))
            selected_names = set()
            if not candidates:
                route_verified = False
            for stage in candidates:
                name = stage.get('display')
                if names and name not in names:
                    continue
                selected_names.add(name)
                modes = app._event_stage_modes(event, stage)
                for mode in modes:
                    if mode == 'challenge' and inputs.get('include_challenge', True) is False:
                        continue
                    if app._maa_task_queue_running() is not False:
                        return Result('unknown', '当前作战未结算，不继续操作', data={'stages': results})
                    if stage.get('kind') == 'story' or '-ST-' in str(name):
                        from event_story_audit_v1 import complete_named_story
                        row = complete_named_story(app, event, name)
                        ok = row.get('status') in ('played_and_returned_verified', 'already_read_verified')
                    else:
                        raw = app.clear_event_stage(event, stage, mode=mode,
                            max_attempts=getattr(app, '_PUBLIC_TASK_MAX_ATTEMPTS', 5))
                        ok = (app.verify_event_challenge_cleared(event, name) is True if mode == 'challenge'
                              else app.verify_event_stage_cleared(event, name) == (True, True))
                        row = dict(worker_return=raw)
                    results.append(dict(stage=name, mode=mode, verified=ok, result=row))
            if event.get('stage_prefix') == 'TL':
                from event_press_committee_v2 import service as press, GOOD
                extra_content = press(app, out / 'extras')
                route_verified = route_verified and extra_content.get('status') in GOOD
                results.append(dict(additional_content=extra_content))
            if names - selected_names:
                route_verified = False
        rewards = session.execute('activity.rewards', selected, context)
        failed = [r for r in results if r.get('verified') is False]
        return Result('succeeded' if rewards.status == 'succeeded' and not failed and route_verified else 'partial',
            '活动目标已返回；未通过项目单独列出，不冒称全清', rewards.evidence,
            dict(stages=results, rewards=asdict(rewards), unfinished=failed,
                 signin=signin if task == 'goal.activity_rewards' else None))
    if task == 'goal.base':
        prepare = session.execute('base.prepare', {}, context)
        if prepare.status != 'succeeded':
            return prepare
        infrast = session.execute('base.infrast', {}, context, {'base': prepare})
        return Result(infrast.status, '按实际基建方案执行并核验；不串入整日日常',
                      infrast.evidence, dict(plan=asdict(prepare), infrastructure=asdict(infrast)))
    if task == 'goal.module':
        from operator_module_missions_v1 import inspect
        row = inspect(app, out / 'progress')
        row.update(goal='module', target_level=inputs.get('target_level', 3),
            next_action='执行AI读取当前模组进度；未完任务复用作业，报价后沿原具名辅助器推进并回读等级')
        return structured(session, task, row)
    if task == 'goal.red_catalyst':
        from recipient_beta_v1 import catalyst_plan
        from operator_optional_inspection_v1 import vouchers
        plan = catalyst_plan(app.BASE)
        row = vouchers(app, out)
        row.update(goal='one_chip_catalyst', request_id=plan['request_id'], quantity=1, maximum_red=90,
            next_action='同一执行AI核当前红票商品报价后调用内部submit/verify，不另开宿主或重买未知提交')
        return structured(session, task, row)
    if task == 'resource.farm':
        if type(inputs['times']) is not int or not 1 <= inputs['times'] <= 999:
            raise ValueError('times 必须为明确的1到999次，不自动改成刷光理智')
        value = app.mode_resource(stage_code=inputs['stage'], times=inputs['times'])
        return structured(session, task, dict(status='native_returned_requires_settlement', result=value,
            actual_summary=app._RUN_SUMMARY.get('resource'), requested_times=inputs['times']))
    if task == 'sss.formation':
        job = json.loads(Path(inputs['job']).read_text(encoding='utf-8-sig'))
        region = inputs['region']
        # The profile is recipient input, never the author's operator pool.
        from unittest.mock import patch
        with patch.dict(app.SSS_FORMATION_PROFILES, {region: inputs['profile']}):
            from receiver_sss_formation_v1 import prepare
            row = prepare(app, region, job)
        return session.proof(row.get('formation_confirmed') is True, '保全编队目标返回；未调用战斗',
                             row, tag='formation')
    if task == 'base.room.trust':
        from run_activity_room_service_v1 import service
        return structured(session, task, service(app, inputs['position'], out), good=('invited_verified',))
    if task == 'operator.training':
        from operator_training_v2 import service
        row = service(app, root=app.BASE)
        return structured(session, task, row, good=('goals_complete',))
    if task == 'operator.module.inspect':
        from operator_module_missions_v1 import inspect
        return structured(session, task, inspect(app, out))
    if task == 'operator.module.mission':
        from operator_module_missions_v2 import run
        return structured(session, task, run(app, inputs['job'], out), good=('module_missions_verified',))
    if task == 'vouchers.inspect':
        from operator_optional_inspection_v1 import vouchers
        return structured(session, task, vouchers(app, out))
    if task == 'activity.press':
        from event_press_committee_v2 import service, GOOD
        return structured(session, task, service(app, out), good=GOOD)
    if task == 'activity.signin':
        from event_signin_discovery_v6 import service
        return structured(session, task, service(app), good=('checked',))
    if task == 'navigation.home':
        ok = app.goto_main_menu() is True
        return session.proof(ok, '原首页导航/有效活动弹层处理已返回' if ok else '页面需AI接回', {}, tag='home')
    if task in ('observe', 'tutorial.ai'):
        from operator_optional_inspection_v1 import frame
        row = frame(app, out, 'current')
        return Result('succeeded', '新图已取得，不代表业务完成', (row['screenshot'],), row)
    if task == 'roguelike.explore':
        theme = inputs['theme']
        if theme not in ('Phantom', 'Mizuki', 'Sami', 'Sarkaz', 'JieGarden', 'BlackFlow'):
            raise ValueError('指定已适配主题，不自动替换')
        value = app.mode_roguelike(theme=theme)
        return structured(session, task, dict(status='native_returned_requires_settlement', result=value,
            actual_summary=app._RUN_SUMMARY.get('roguelike')))
    if task == 'reclamation.run':
        if type(inputs['cycles']) is not int or inputs['cycles'] < 1:
            raise ValueError('cycles 必须为明确的正整数')
        value = app.mode_reclamation(target_cycles=inputs['cycles'], stop_at=context.deadline)
        return structured(session, task, dict(status='native_returned_requires_settlement', result=value,
            actual_summary=app._RUN_SUMMARY.get('reclamation')))
    raise ValueError('尚未绑定的任务：' + task)


def binding(task):
    if task == 'spa.badges':
        from stronghold_badges_trial_v1 import run
        return Operation(task,'exploration','badges',('ocr','shot','_maa_install_root')),run
    if task == 'operator.modules':
        from operator_module_queue_v1 import one_module
        return Operation(task,'operators','modules',('ocr','shot','tap','goto_main_menu')),one_module
    if task == 'operator.paradox':
        from paradox_simulation_v1 import one_module
        return Operation(task, 'operators', 'paradox', ('_maa_install_root','ocr','tap','wait','_fetch_prts_json')), one_module
    if task == 'mainline.stage':
        def mainline(session, inputs, context, previous, operation):
            from copy import deepcopy
            app = session.app
            chapter = app._stage_chapter(inputs['stage'])
            if inputs['layer'] != 'normal' or not chapter or chapter >= 10:
                return Result('blocked', '此入口尚未接入该章节的精确难度切换与核验，不以默认难度替代')
            raw = app.mode_mainline(target_stage=inputs['stage'], target_max_attempts=inputs['max_attempts'])
            row = deepcopy(app._RUN_SUMMARY.get('mainline') or {})
            verified = (raw is True and row.get('starting_target') == inputs['stage']
                        and row.get('targeted') is True and row.get('status') == 'completed'
                        and app._maa_task_queue_running() is False
                        and app.verify_stage_cleared(chapter, inputs['stage']) == (True, True))
            evidence = str(app.shot('receiver_mainline_target_result'))
            row.update(target=inputs['stage'], layer=inputs['layer'], game_clear_verified=verified,
                       evidence=evidence, worker_return=raw,
                       marker_verification=deepcopy(getattr(app, '_LAST_STAGE_MARKER_VERIFICATION', {})))
            return Result('succeeded' if verified else 'partial',
                          '点名普通主线已按新图核验完美' if verified else '主线未完美或缺实际核验，保留待办',
                          (evidence,), row)
        return BUSINESS[task], mainline
    """Resolve lazily: listing/validation never imports a GUI/game engine."""
    if task == 'activity.rewards':
        def rewards(session, inputs, context, previous, operation):
            from copy import deepcopy
            from ark_modules.domains.activity import rewards as original
            event = session.event(inputs)
            if not event or event.get('stage_prefix') != 'TL':
                return original(session, inputs, context, previous, operation)
            raw = session.app.claim_event_task_rewards(event)
            row = deepcopy((session.app._RUN_SUMMARY.get('event') or {}).get('task_rewards') or {})
            visits = row.get('tl_visits') or []
            evidence = tuple((visits[-1] if visits else {}).get('evidence') or ())
            ok = raw is True and len(evidence) >= 2 and row.get('status') in ('completed', 'verified_no_claimable')
            if row.get('status') == 'completed':
                ok = ok and row.get('tl_verified_claims', 0) > 0
            return Result('succeeded' if ok else 'partial', row.get('detail', '本期奖励真实结果核验'), evidence, row)
        return BUSINESS[task], rewards
    if task in BUSINESS and task not in ('base.rooms', 'long.roguelike', 'long.reclamation', 'resource.farm'):
        spec = BUSINESS[task]
        return spec, spec.bind()
    if task in PROGRESS:
        spec = PROGRESS[task]
        return spec, spec.bind()
    if task == 'daily.collect':
        old = BUSINESS['daily.exit_tail']
        def collect(session, inputs, context, previous, operation):
            # Each explicit new collection has its own path. Do not reuse an
            # old end-of-day cache after a later user-added operation.
            from ark_modules.exit_tail import ExitTail
            from daily_base_notifications_v3 import collect as notifications
            worker = ExitTail(session.app, session.output / ('collect-' + str(session.sequence)),
                context, owns_control=session.owns_control, clock=session.now)
            first = worker.collect(('Infrast', 'Recruit'), 'collections')
            note = notifications(session.app) if worker.available() else {'complete': False}
            award = worker.collect(('Award',), 'award') if worker.available() else Result('blocked', '队列仍忙')
            ok = first.status == award.status == 'succeeded' and note.get('complete') is True
            return Result('succeeded' if ok else 'partial', '只补新待办，不轮班、不用无人机、不刷关',
                tuple(dict.fromkeys([*first.evidence, *award.evidence])),
                dict(collection=asdict(first), notifications=note, award=asdict(award),
                     daily_full_replayed=False, drone_spent=False, battle_dispatched=False))
        return Operation(task, 'daily', 'exit_tail', old.required), collect
    if task in CHAINS:
        return Operation(task, 'daily', 'chain', BUSINESS['daily.final'].required), chain
    allowed = {'roguelike.explore': ('mode_roguelike',), 'reclamation.run': ('mode_reclamation',),
               'goal.event_farm': ('mode_event',),
               'resource.farm': ('mode_resource',)}.get(task, ())
    return Operation(task, 'receiver', 'extra', legacy_modes=allowed,
                     read_only=task in ('observe', 'tutorial.ai')), extra


class Session(RuntimeSession):
    def execute(self, task, inputs, context, previous=None):
        validate(task, inputs)
        spec, handler = binding(task)
        return self.invoke(spec, handler, inputs, context, previous or {})


def session_tool(task, out, inputs):
    """Existing quote helpers submit to THIS owner, never start another one."""
    if task == 'operator.module.unlock':
        from tools.module_unlock_trial import run
        return run(out)
    if task == 'operator.module.upgrade':
        from tools.module_upgrade_trial import run
        return run(out, inputs['level'])
    if task.startswith('vouchers.red.'):
        from tools.red_catalyst_trial import run
        return run(out, task.rsplit('.', 1)[-1])
    raise ValueError('未知的当前会话报价辅助器')
