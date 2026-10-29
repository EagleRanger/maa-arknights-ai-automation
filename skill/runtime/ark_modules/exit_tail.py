"""Exit-time collections, not a second daily run or an environment closer.

MAA source: InfrastTask always executes InfrastBegin before the facility list;
that process handles InfrastReward. Empty facilities therefore collect without
staff rotation. AutoRecruitTask.hire_all precedes the times loop: MaxTimes=0
collects finished slots without opening new ones. Verify these against the
installed GUI serialization and real pages during natural-run acceptance.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from .core import Dispatcher, Module, ReceiptStore, Result, Step
from .runtime_session import blocked


def collection_config(app, config, chains):
    """Pure configuration; never modifies the accepted 333 production plan."""
    if not chains or not set(chains) <= {'Infrast', 'Recruit', 'Award'}:
        raise ValueError('exit tail permits collections only')
    result = deepcopy(config)
    rows = app._task_queue(result)
    if any(sum(r.get('TaskType') == c for r in rows) != 1 for c in chains):
        raise ValueError('exactly one configured task per selected chain required')
    for row in rows:
        kind = row.get('TaskType')
        row['IsEnable'] = kind in chains
        if kind == 'Infrast' and kind in chains:
            # Preserve GUI's complete room list but disable every facility.
            # Empty lists can be repopulated by GUI migration code.
            rooms = row.get('RoomList')
            if not isinstance(rooms, list): raise ValueError('missing infrastructure room schema')
            row.update(Mode='Normal', UsesOfDrones='_NotUse',
                RoomList=[dict(r, IsEnabled=False) for r in rooms],
                OriginiumShardAutoReplenishment=False, ContinueTraining=False)
        if kind == 'Recruit' and kind in chains:
            row.update(MaxTimes=0, UseExpedited=False, RefreshLevel3=False, ForceRefresh=False)
    return result


def restore_task_settings(app, current, original, chains):
    result = deepcopy(current)
    old = {r['TaskType']: r for r in app._task_queue(original)}
    for row in app._task_queue(result):
        source = old.get(row.get('TaskType'))
        if source is None: continue
        if row['TaskType'] in chains:
            row.clear(); row.update(deepcopy(source))
        elif 'IsEnable' in source:
            row['IsEnable'] = source['IsEnable']
        else:
            row.pop('IsEnable', None)
    return result


class ExitTail:
    def __init__(self, app, output, context, *, owns_control, clock, drone_policy=None, previous_collection=None):
        self.app, self.output, self.context = app, Path(output), context
        self.owns, self.clock = owns_control, clock
        self.drone_policy = drone_policy or {}
        self.previous_collection = previous_collection

    def home(self):
        if getattr(self.app, 'SCRIPT_SCREENSHOT_BACKEND', None) != 'adb':
            return self.app.goto_main_menu() is True
        from .vision import Vision, RuntimeVisionPort, classify_existing, existing_home_transitions
        from uuid import uuid4
        vision = Vision(RuntimeVisionPort(self.app, lambda: self.owns(self.context.owner)),
                        classify_existing, existing_home_transitions())
        frame, _ = vision.read('exit_home_source')
        if frame.kind == 'unknown':
            return self.app.goto_main_menu() is True
        proof = vision.reach('home')
        ReceiptStore(self.output/'navigation'/f'{uuid4().hex}.json').save(asdict(proof))
        return proof.status == 'succeeded'

    def initial_collection(self):
        if not self.previous_collection:
            return self.collect(('Infrast', 'Recruit'), 'collections')
        if not self.available(): return blocked('无法接续已完成领取后的返回导航')
        source = self.previous_collection
        proof = ReceiptStore(source['queue']).load() or {}
        restored = ReceiptStore(source['restoration']).load() or {}
        if (proof.get('run_id') != source['run_id']
                or any((proof.get('chains') or {}).get(c) is not True for c in ('Infrast', 'Recruit'))
                or restored.get('verified') is not True):
            return blocked('前次领取/参数恢复证据不完整，未复用或重跑')
        home = self.home()
        image = str(self.app.shot('exit_resumed_collection_home'))
        return Result('succeeded' if home else 'partial',
            '保留前次基建/招募领取，仅补返回首页' if home else '保留前次领取，返回首页仍未核验',
            (source['queue'], source['restoration'], image),
            {'home_verified': home, 'preserved_previous_collection': True,
             'new_collection_queue_started': False, 'new_recruits_started': 0})

    def available(self):
        from .orchestration import timestamp
        return (self.owns(self.context.owner) is True
                and self.app._maa_task_queue_running() is False
                and self.clock() < timestamp(self.context.deadline))

    def collect(self, chains, label):
        if not self.available(): return blocked('退出收尾未接管：队列/控制权/截止条件不符')
        app = self.app
        if self.home() is not True:
            return Result('partial', '退出收尾未确认首页，未开始领取队列')
        path = str(Path(app.MAA_CONFIG)/'gui.new.json')
        original = app._read_json_file(path, {})
        desired = collection_config(app, original, chains)
        out = self.output/label
        ReceiptStore(out/'configuration.before.json').save(original)
        ReceiptStore(out/'configuration.collection.json').save(desired)
        changed = False
        try:
            if not self.available(): return blocked('领取前控制权或截止条件已变化')
            # A failed write/readback must still attempt restoring the old task
            # parameters while idle. Never leave collect-only in tomorrow's GUI.
            changed = True
            app._atomic_write_json(path, desired)
            if app._read_json_file(path, {}) != desired:
                raise RuntimeError('collection config readback failed')
            if app._maa_process_exists() is True:
                app.reload_maa_after_config_switch('退出前仅领取，不轮班、不刷关')
            if not self.available(): return blocked('尚未启动领取，已到停止边界')
            app._initialize_current_run_evidence_boundary()
            if app.run_maa_daily_tasks(enabled_tasks=set(chains)) is not True:
                return Result('partial', '退出领取队列未确认启动')
            from .orchestration import timestamp
            remaining = int((timestamp(self.context.deadline)-self.clock()).total_seconds())
            if remaining <= 0: return Result('unknown', '已到收尾截止，队列状态待核验')
            completed = app.wait_maa_complete(timeout=min(600, remaining),
                continue_after_chain_error=True, prestarted_boundary=True)
            if app._maa_task_queue_running() is not False:
                return Result('unknown', '收尾队列仍运行，未改配置或强制关闭')
            text = app._get_current_maa_run_log()
            proof = out/'queue.json'
            statuses = {c: app._taskchain_status(text, c).get('ok') is True for c in chains}
            ReceiptStore(proof).save({'run_id': self.context.run_id, 'log': text, 'chains': statuses,
                                     'queue_returned_complete': completed is True})
            home = self.home() is True
            image = str(app.shot('exit_tail_' + label))
            ok = all(statuses.values()) and home
            return Result('succeeded' if ok else 'partial',
                '本次领取检查完成' if ok else '退出领取检查仍有未核验项', (str(proof), image),
                {'chains': statuses, 'home_verified': home, 'collection_only': True,
                 'claim_counts': None, 'changed_roster': False, 'new_recruits_started': 0})
        finally:
            if changed and app._maa_task_queue_running() is False:
                current = app._read_json_file(path, {})
                restored = restore_task_settings(app, current, original, chains)
                app._atomic_write_json(path, restored)
                if app._read_json_file(path, {}) != restored:
                    raise RuntimeError('exit collection configuration restore failed')
                ReceiptStore(out/'restoration.json').save({'verified': True, 'config': path})
                if app._maa_process_exists() is True:
                    app.reload_maa_after_config_switch('退出领取参数已恢复')
            elif changed:
                ReceiptStore(out/'restoration.json').save({'verified': False,
                    'status': 'deferred_queue_running', 'original': str(out/'configuration.before.json')})

    def drones(self):
        if not self.available(): return blocked('当前无法接管无人机收尾')
        from activity_room_plan_v2 import all_rooms_max
        policy = self.drone_policy
        if not all_rooms_max(policy.get('rooms') or [], at=self.clock().isoformat(),
                             rooms_complete=policy.get('rooms_complete') is True):
            from daily_base_333_drones_v1 import open_base, observe
            balance = (observe(self.app, 'exit_reservation') if open_base(self.app) is True
                       else {'verified': False, 'reason': 'base_not_reached'})
            path = self.output/'drone_reservation.json'
            ReceiptStore(path).save({'policy': 'reserve_for_activity_room_upgrades',
                                    'production_acceleration': False, 'rooms_complete_verified': False,
                                    'current_balance': balance})
            return Result('succeeded' if balance.get('verified') is True else 'partial',
                          '已核当前无人机余额，按活动室政策预留' if balance.get('verified') is True
                          else '无人机已保留，当前余额尚未核验',
                          (str(path),), {'reserved': True, 'used_up_verified': False,
                                         'current_balance': balance})
        from .orchestration import valid_proof
        if not policy.get('target') or not valid_proof(policy, self.clock()):
            return blocked('无人机当前加速目标未核验，保留余额，不猜产线')
        from .base import use_drones
        return use_drones(self.app, self.output/'drones', policy['target'], activity_rooms=policy['rooms'],
                          rooms_complete=True, now=self.clock())

    def run(self):
        # Award last: collections/drone assistance can finish additional tasks.
        # No endless until-empty loop: newly generated ongoing production is
        # left for the next normal login, not another farm/daily execution.
        identity_store = ReceiptStore(self.output/'context.json')
        identity = asdict(self.context)
        previous_identity = identity_store.load()
        if previous_identity is not None and previous_identity != identity:
            return blocked('退出收尾目录属于另一轮任务，未复用旧领取结果')
        identity_store.save(identity)
        modules = {
            'collect': Module(lambda _: self.initial_collection()),
            'drones': Module(lambda _: self.drones()),
            'award': Module(lambda _: self.collect(('Award',), 'award')),
        }
        store = ReceiptStore(self.output/'steps.json')
        before = store.load()
        if before and before.get('exit_tail_finished'):
            return Result(**before['exit_tail_finished'])
        results = Dispatcher(modules).run([Step(k, k) for k in modules], store=store)
        ok = all(r.status == 'succeeded' for r in results.values())
        result = Result('succeeded' if ok else 'partial', '退出前收尾检查完成' if ok else '退出收尾尚有未完成项',
            tuple(p for r in results.values() for p in r.evidence),
            {'parts': {k: asdict(r) for k, r in results.items()}, 'sanity_spent': 0,
             'daily_full_executed': False, 'new_recruits_started': 0})
        saved = store.load(); saved['exit_tail_finished'] = asdict(result); store.save(saved)
        return result
