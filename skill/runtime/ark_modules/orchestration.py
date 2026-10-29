"""Explicit, serial day assembly. No scheduler, global main or hidden fallback.

Facts are supplied by existing observation adapters, never inferred from task
exit codes. Candidate control is separate from the production shadow observer.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

from .core import Dispatcher, Module, Result, Step


OPERATIONS = frozenset({
    'weekly.annihilation', 'activity.stage', 'activity.farm', 'activity.rewards',
    'mainline.stage', 'resource.farm', 'periodic.sss', 'base.prepare',
    'base.rooms', 'base.drones', 'daily.final', 'long.roguelike',
    'long.reclamation', 'observe', 'hold', 'preserve', 'daily.exit_tail',
})


def timestamp(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('timezone-aware time required')
    return value


def valid_proof(row, at, *, require_expiry=True):
    try:
        return (row.get('verified') is True and bool(row.get('evidence'))
                and timestamp(row['observed_at']) <= at
                and (not require_expiry or at < timestamp(row['valid_until'])))
    except (KeyError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class Context:
    run_id: str
    workflow: str
    contract_revision: str
    started_at: str
    deadline: str
    owner: str

    def __post_init__(self):
        if not all((self.run_id, self.workflow, self.contract_revision, self.owner)):
            raise ValueError('run/workflow/contract/owner required')
        if timestamp(self.started_at) >= timestamp(self.deadline):
            raise ValueError('deadline must follow start')


@dataclass(frozen=True)
class Plan:
    context: Context
    scope: str
    steps: tuple[Step, ...]
    close_environment: bool = False
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        if self.scope not in ('daily', 'single'):
            raise ValueError('unknown plan scope')
        if self.scope == 'single' and (len(self.steps) != 1 or self.close_environment):
            raise ValueError('single task cannot append work or close the environment')
        if any(s.module not in OPERATIONS for s in self.steps):
            raise ValueError('unknown operation')


def single(context, operation, inputs=None):
    return Plan(context, 'single', (Step('requested', operation, inputs or {}),))


def continue_plan(previous, context, manifest, reconciled=None):
    """Compile a new admitted run from settled effects, never reopen the old run.

    Pure planning only. The caller still owns admission, live observations and
    the single controller. An uncertain step blocks only its dependants.
    """
    if (context.run_id == previous.context.run_id
            or context.workflow != previous.context.workflow
            or context.contract_revision != previous.context.contract_revision):
        raise ValueError('continuation requires new run and unchanged workflow/contract')
    at = timestamp(context.started_at)
    old_at = timestamp(previous.context.started_at)
    cn = timezone(timedelta(hours=8))
    game_day = lambda t: (t.astimezone(cn)-timedelta(hours=4)).date()
    if at < old_at or game_day(at) != game_day(old_at):
        raise ValueError('same game day required; compile a fresh day instead')
    prior = manifest.get('module_execution') or {}
    digest = sha256(json.dumps(asdict(previous), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if (manifest.get('run_id') != previous.context.run_id
            or prior.get('context') != asdict(previous.context)
            or prior.get('assembly_sha256') != digest):
        raise ValueError('source manifest does not match the original plan')
    rows, reconciled = prior.get('steps', {}), reconciled or {}
    if not set(reconciled) <= {s.key for s in previous.steps}:
        raise ValueError('reconciliation names an unknown step')
    steps, preserved = [], set()
    for step in previous.steps:
        row, evidence = rows.get(step.key), None
        decision = reconciled.get(step.key)
        if decision is not None:
            if (decision.get('source_run_id') != previous.context.run_id
                    or decision.get('operation') != step.module
                    or decision.get('verified') is not True or not decision.get('evidence')
                    or not old_at <= timestamp(decision['observed_at']) <= at
                    or decision.get('outcome') not in ('completed', 'no_effect')):
                raise ValueError('reconciliation evidence mismatch: '+step.key)
        if row and row.get('status') == 'succeeded' and row.get('evidence'):
            if decision and decision['outcome'] == 'no_effect':
                raise ValueError('completed effect contradicts no-effect claim: '+step.key)
            evidence = row['evidence']
        elif decision and decision['outcome'] == 'completed':
            evidence = decision['evidence']
        if evidence:
            preserved.add(step.key)
            steps.append(Step(step.key, 'preserve', {'evidence': evidence,
                'data': dict((row or {}).get('data') or {}) if row and row.get('status') == 'succeeded'
                        else dict((decision or {}).get('data') or {}),
                'reason': '保留已核实完成效果；来源 '+previous.context.run_id}))
        elif (row is None or row.get('status') == 'skipped'
              or (row.get('status') == 'blocked' and (row.get('data') or {}).get('before_action') is True)
              or (decision and decision['outcome'] == 'no_effect')):
            steps.append(step)
        else:
            steps.append(Step(step.key, 'hold', {'reason': '旧步骤效果尚未核实，先对账：'+step.key}))
    pending = any(s.module not in ('preserve', 'hold', 'observe') for s in steps)
    if pending and previous.scope == 'daily':
        # Prior daily chains stay frozen. New work may create fresh rewards,
        # so use the narrow exit-tail instead of replaying those five chains.
        steps = [Step(s.key, 'daily.exit_tail')
                 if s.key in preserved and old.module == 'daily.final' else s
                 for old, s in zip(previous.steps, steps)]
    return Plan(context, previous.scope, tuple(steps), previous.close_environment and pending,
                previous.notes+('同日续接来源：'+previous.context.run_id,))


def compile_day(context, facts, *, include_rooms=True):
    """Compile current observations; unknowns block their domain, not the day.

Expiry comes from the weekly/periodic/event authority, not a hardcoded date.
Farm selection stays in the inventory worker. No activity failure -> chips.
"""
    at = timestamp(context.started_at)
    steps, notes = [], []
    def add(key, module, inputs=None, requires=()):
        steps.append(Step(key, module, inputs or {}, tuple(requires)))
    def preserve(key, row, reason):
        add(key, 'preserve', {'evidence': row['evidence'], 'reason': reason})
    def hold(key, reason):
        add(key, 'hold', {'reason': reason})

    weekly = facts.get('weekly') or {}
    if weekly.get('state') == 'complete' and valid_proof(weekly, at):
        preserve('weekly', weekly, '本周剿灭已有完整证据，保留不重打')
    else:
        add('weekly', 'weekly.annihilation')  # Reads live cap before spending.
    event = facts.get('event') or {}
    event_known = valid_proof(event, at)
    if event_known and event.get('state') == 'active':
        previous = 'weekly'
        if event.get('scan_complete') is not True:
            hold('activity_catalog', '活动页面覆盖不完整，先补目录及剧情节点核验')
            previous = 'activity_catalog'
        seen = set()
        for stage in event.get('stages', []):
            identity = (stage['id'], stage['layer'])
            if identity in seen:
                raise ValueError('duplicate stage/layer')
            seen.add(identity)
            key = 'event:' + ':'.join(identity)
            state = stage.get('state')
            # Completion requires the actual layer indicator, not a card stamp.
            if state == 'complete' and valid_proof(stage, at, require_expiry=False):
                preserve(key, stage, '该关该层已有完成图证，未重复执行')
            elif state == 'locked':
                try:
                    future = at < timestamp(stage['opens_at'])
                except (KeyError, ValueError, TypeError):
                    future = False
                if future and valid_proof(stage, at, require_expiry=False):
                    notes.append(key + ' 下次既有每日触发到期后重新核验')
                else:
                    hold(key, '阶段已到开放时间或时间未知，需刷新真实目录')
                    previous = key
            elif state == 'pending':
                add(key, 'activity.stage', {'event': event['id'], 'stage': stage['id'],
                    'layer': stage['layer'], 'kind': stage.get('kind', 'battle')}, (previous,))
                previous = key
            else:
                hold(key, '本关本层完成状态未知，不能当已通关')
                previous = key
        if event.get('farm_required') is True:
            dependency = 'weekly' if event.get('farm_after_block_approved') is True else previous
            add('farm', 'activity.farm', {'event': event['id']}, (dependency,))
        elif event.get('farm_required') is False and event.get('no_farm_benefit_verified') is True:
            # E.g. a one-off event without exchange rewards. This is an explicit
            # authority fact, not a fallback inferred from a failed battle.
            _resource_steps(add, hold, facts, at, previous)
        else:
            hold('farm', '活动刷取价值未确认，不擅自转移理智用途')
        add('event_rewards', 'activity.rewards', {'event': event['id']})
    elif event_known and event.get('state') == 'none':
        main = facts.get('mainline') or {}
        if main.get('state') == 'complete' and valid_proof(main, at, require_expiry=False) and not main.get('new_notice'):
            preserve('mainline', main, '主线完成记录有效，无更新通知，不重扫')
            _resource_steps(add, hold, facts, at, 'weekly')
        elif main.get('new_notice') or main.get('explicit_requested'):
            targets = main.get('pending_layers') or []
            previous = 'weekly'
            for i, stage in enumerate(targets):
                key = f'mainline:{i}'
                add(key, 'mainline.stage', dict(stage), (previous,))
                previous = key
            if targets:
                _resource_steps(add, hold, facts, at, previous)
            else:
                hold('mainline', '新主线须先刷新真实层次目录')
        else:
            hold('mainline', '主线状态缺证，不自动重扫已关闭章节')
    else:
        hold('stamina_route', '活动日历/真实入口尚未确认，只暂停依赖它的理智动作')

    sss = facts.get('sss') or {}
    if sss.get('state') == 'complete' and valid_proof(sss, at):
        preserve('sss', sss, '本周期保全奖励已齐，刷新前不再进页面')
    else:
        add('sss', 'periodic.sss')
    add('base', 'base.prepare')
    if include_rooms:
        add('rooms', 'base.rooms')
    drone = facts.get('drones')
    if drone is not None:
        # Current room/target facts are verified again by the drone worker at
        # execution time. This optional module never gates the other dailies.
        add('drones', 'base.drones', dict(drone))
    # Infrast preparation may fail without blocking the other daily chains.
    # This split is handled ONLY by daily_tasks.run_tasks, not a second policy.
    add('daily', 'daily.final')
    return Plan(context, 'daily', tuple(steps), True, tuple(notes))


def _resource_steps(add, hold, facts, at, dependency):
    route = facts.get('resource') or {}
    if valid_proof(route, at) and route.get('stage') and route.get('policy_admitted') is True:
        add('farm', 'resource.farm', dict(route), (dependency,))
    else:
        hold('farm', '无当前有效库存资源方案，不默认插入芯片或其它关卡')


class RunStore:
    """Namespace inside the existing run manifest, not a second state system."""
    def __init__(self, store, context):
        self.store, self.context = store, asdict(context)

    def _root(self):
        value = self.store.load() or {'run_id': self.context['run_id']}
        if value.get('run_id') != self.context['run_id']:
            raise ValueError('wrong run manifest')
        return value

    def load(self):
        value = self._root().get('module_execution')
        if value is not None and value.get('context') != self.context:
            raise ValueError('module receipt context changed; reconcile, do not replay')
        return value

    def save(self, value):
        root = self._root()
        root['module_execution'] = dict(value, context=self.context)
        self.store.save(root)


class Runner:
    """One lease-owning caller supplies narrow operations and explicit cleanup.

The caller has already used the existing project admission and controller lock.
No method here starts an app, steals a lease, or invokes legacy full/main.
"""
    def __init__(self, port):
        self.port = port

    def run(self, plan, store, *, finalise=None):
        if plan.close_environment and finalise is None:
            raise ValueError('daily caller must explicitly provide its finaliser')
        scoped = RunStore(store, plan.context)
        results = {}
        def invoke(step):
            if step.module == 'hold':
                return Result('blocked', step.inputs['reason'], data={'before_action': True})
            if step.module == 'preserve':
                proof = step.inputs['evidence']
                return Result('succeeded', step.inputs['reason'],
                    (proof,) if isinstance(proof, str) else tuple(proof),
                    dict(step.inputs.get('data') or {}, reused_previous_effect=True, new_effects=0))
            if timestamp(self.port.now()) < timestamp(plan.context.started_at):
                return Result('blocked', '尚未到本轮开始时间，未启动模块', data={'before_action': True})
            if timestamp(self.port.now()) >= timestamp(plan.context.deadline):
                return Result('blocked', '已到本轮截止，仅收口、不启动下一模块', data={'before_action': True})
            if self.port.owns_control(plan.context.owner) is not True or self.port.queue_idle() is not True:
                return Result('blocked', '当前控制权或队列未空闲，未点击或停止任务', data={'before_action': True})
            result = self.port.execute(step.module, dict(step.inputs), plan.context, dict(results))
            if not isinstance(result, Result):
                raise TypeError('module result required')
            # A blocked result is retryable only when no game action was sent.
            if result.status == 'blocked' and result.data.get('before_action') is not True:
                return Result('unknown', result.detail, result.evidence,
                              dict(result.data, reconciliation_required=True))
            return result
        modules = {}
        # Dispatcher persists before action. Dependencies/results are provided
        # through this one serial invocation, never via a global task registry.
        for step in plan.steps:
            def call(inputs, step=step):
                result = invoke(step)
                results[step.key] = result
                return result
            modules[step.key] = Module(call, read_only=step.module in ('observe', 'hold', 'preserve'))
        mapped = tuple(Step(s.key, s.key, s.inputs, s.requires) for s in plan.steps)
        # Include actual operation names so a changed target cannot reuse a
        # receipt merely because its displayed step key stayed the same.
        operation_hash = sha256(json.dumps(asdict(plan), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        old = scoped.load()
        if old and old.get('assembly_sha256') != operation_hash:
            raise ValueError('assembly changed; needs a reconciled continuation')
        if old and old.get('finalisation') is not None:
            # Finalisation seals this run, including previously unattempted
            # steps. A new admitted continuation may reuse proven effects; a
            # closed run must never reopen business before reusing its popup.
            saved = old.get('steps', {})
            for step in plan.steps:
                row = saved.get(step.key)
                if row and row.get('status') == 'succeeded':
                    results[step.key] = Result('succeeded', row['detail'], tuple(row['evidence']),
                        dict(row.get('data', {}), reused_previous_effect=True))
                elif row and row.get('status') in ('running', 'interrupted', 'unknown'):
                    results[step.key] = Result('unknown', '旧运行已收口，本项先对账、不重放',
                        data={'previous': row, 'reconciliation_required': True})
                else:
                    results[step.key] = Result('skipped', '旧运行已收口，未完项由新续接计划处理',
                        data={'previous': row, 'before_action': True})
            return results, dict(old['finalisation'], reused=True, sealed=True)
        class AssemblyStore:
            def load(self): return scoped.load()
            def save(self, value): scoped.save(dict(value, assembly_sha256=operation_hash))
        # Publish reused/skipped results immediately as well as executed ones.
        # Dispatcher owns dependency semantics; the port can reread the persisted
        # prior proofs for daily-tail reuse after process recovery.
        runner = Dispatcher(modules)
        outcome = runner.run(mapped, store=AssemblyStore(), on_result=lambda key, result: results.update({key: result}))
        results.update(outcome)
        final = None
        if plan.close_environment:
            receipt = scoped.load()
            prior = receipt.get('finalisation')
            if prior is not None:
                final = dict(prior, reused=True)
            elif self.port.owns_control(plan.context.owner) is not True or self.port.queue_idle() is not True:
                final = {'status': 'deferred', 'reason': 'controller_or_queue_busy', 'cleanup_verified': False}
                # Do not persist a deferred no-action as permanent finalisation.
            else:
                receipt['finalisation'] = {'status': 'running'}
                scoped.save(receipt)
                try:
                    final = finalise(outcome)
                    if not isinstance(final, dict): raise TypeError('finalisation receipt required')
                except Exception as exc:
                    final = {'status': 'unknown', 'detail': str(exc), 'needs_reconciliation': True}
                receipt['finalisation'] = final
                scoped.save(receipt)
        return outcome, final
