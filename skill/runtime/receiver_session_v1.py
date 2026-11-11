"""A public single owner for named modules and AI recovery, never daily full.

The existing common host installs dependencies without the daily business
bootstrap, so unrelated event maps cannot block a reward-only request.
"""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import nullcontext
from uuid import uuid4
import json
import os
import re
import time

from receiver_catalog_v1 import BY_ID, validate
from receiver_setup_v1 import local, read


def steps(rows, prior_keys=()):
    if not isinstance(rows, list) or not rows:
        raise ValueError('需要明确的任务清单；不默认执行整日日常')
    seen = set(prior_keys)
    for row in rows:
        key, task = row.get('key'), row.get('task')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', key) or key in seen:
            raise ValueError('步骤 key 须唯一且不是路径')
        selected = validate(task, row.get('inputs', {}))
        if selected.route not in ('session',):
            raise ValueError('该任务应使用自身明确入口，不放入模块会话：' + task)
        if not set(row.get('requires', [])) <= seen:
            raise ValueError('依赖只能指向之前的明确步骤')
        seen.add(key)
    return rows


def serve(app, rows, out, data, *, deadline=None, clock=time.time, sleep=time.sleep):
    from ark_host.environment import EnvironmentOwner
    from ark_modules.core import ReceiptStore
    from ark_modules.orchestration import Context
    from receiver_operations_v1 import Session
    from operator_optional_inspection_v1 import frame
    out = Path(out)
    steps(rows)
    sink = ReceiptStore(out / 'receipt.json')
    if sink.load() is not None:
        raise ValueError('原运行结果保留；先读 status，不换目录盲目重放未知动作')
    now = datetime.now(timezone.utc)
    end = datetime.fromisoformat(deadline) if deadline else now + timedelta(hours=4)
    if end.tzinfo is None or end <= now:
        raise ValueError('截止时间须带时区且晚于当前时间')
    run_id = 'receiver-' + now.strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8]
    context = Context(run_id, 'ARK-PUBLIC-MODULES-V1', 'receiver-v1', now.isoformat(), end.isoformat(), run_id)
    owner = EnvironmentOwner(app, owner=run_id, clock=clock, deadline=end.timestamp())
    state = dict(schema_version=1, run_id=run_id, status='preparing', context=asdict(context),
        goal=data.get('current_goal'),
        controller_pid=os.getpid(), account_key=data['account_key'], client=app.PKG,
        frames=[], actions=[], module_results=[], results={}, daily_invoked=False,
        cleanup_verified=False, finished_at=None)
    sink.save(state)
    commands = out / 'commands'
    commands.mkdir(exist_ok=True)
    events = []
    session = Session(app, out / 'modules', owns_control=owner.owns, events=events)

    def capture(tag):
        row = frame(app, out / 'frames', str(len(state['frames']) + 1) + '-' + tag)
        row.update(seq=len(state['frames']) + 1, path=row['screenshot'])
        state['frames'].append(row)
        sink.save(state)
        print('ARK_FRAME ' + json.dumps(dict(seq=row['seq'], screenshot=row['path']), ensure_ascii=False), flush=True)
        return row

    def perform(selected):
        steps(selected, state['results'])
        prior = {}
        for row in selected:
            key, task, inputs = row['key'], row['task'], row.get('inputs', {})
            if key in state['results']:
                raise ValueError('该步骤已有结果，请核原效果后只提交新步骤：' + key)
            if any(state['results'].get(dep, {}).get('status') != 'succeeded' for dep in row.get('requires', [])):
                raise ValueError('前置步骤未核验，只暂停其依赖：' + key)
            if clock() >= owner.deadline or not owner.owns() or app._maa_task_queue_running() is not False:
                raise ValueError('控制权/截止/队列不允许开始下一模块')
            if inputs.get('event') and inputs['event'] not in session.events:
                tip = app.save_maa_daily_stage_tip()
                event = app.discover_event(inputs['event'], tip.get('active_side_stories'), app.MAA_ROOT)
                if not event:
                    raise ValueError('当前活动尚未确认，请执行AI核页面/公告')
                session.events[event['name']] = event
            from ark import check_task
            check_task(task, inputs, data)
            scope = nullcontext()
            if task.startswith('base.') or task == 'goal.base':
                from receiver_setup_v1 import base_scope
                scope = base_scope(app)
            with scope:
                result = session.execute(task, inputs, context, prior)
            prior[key] = result
            state['results'][key] = dict(asdict(result), task=task)
            state['module_results'].append(dict(task=task, result=asdict(result)))
            sink.save(state)
            if result.status in ('unknown', 'interrupted'):
                raise ValueError('本模块效果未知，请AI先对账，不继续依赖动作')
        state['status'] = 'awaiting_ai'
        state.pop('error', None)
        capture('returned')
        print('ARK_MODULE_RETURN ' + json.dumps(dict(run_id=run_id, results=state['results']), ensure_ascii=False), flush=True)

    try:
        owner.acquire()
        pointer = ReceiptStore(Path(app.BASE) / 'runtime_state/public_receiver_owner.json')
        pointer.save(dict(run_id=run_id, controller_pid=os.getpid(), output=str(out),
            account_key=data['account_key'], game_package=data['game_package'],
            source_manifest_sha256=data.get('_source_manifest_sha256')))
        app._initialize_current_run_evidence_boundary()
        app._DAILY_EXISTING_SANITY_ONLY = True
        try:
            if not owner.start():
                raise RuntimeError('环境未就绪，保留现场交AI')
            if app._ensure_execution_plan('full') is None:
                raise RuntimeError('本机任务/资源计划未通过')
            capture('start')
            perform(rows)
        except Exception as exc:
            state.update(status='awaiting_ai', error=str(exc))
            try:
                capture('needs_ai')
            except Exception as frame_error:
                state['capture_error'] = str(frame_error)
            sink.save(state)
            print('ARK_NEEDS_AI ' + json.dumps(dict(run_id=run_id, error=str(exc), receipt=str(sink.path)), ensure_ascii=False), flush=True)
        while clock() < owner.deadline:
            pending = [p for p in sorted(commands.glob('*.json'))
                       if not p.name.endswith(('.ack.json', '.result.json')) and not p.with_suffix('.ack.json').exists()]
            if not pending:
                sleep(.25)
                continue
            path = pending[0]
            ack = ReceiptStore(path.with_suffix('.ack.json'))
            ack.save(dict(status='dispatched'))
            try:
                command = read(path)
                action = command.get('action')
                if command.get('run_id', run_id) != run_id:
                    raise ValueError('命令不属于本次会话')
                if app._maa_task_queue_running() is not False:
                    raise ValueError('MAA仍在操作，不抢控制')
                if action in ('finish_goal', 'finish', 'end'):
                    key = command.get('collection_key')
                    if action == 'finish_goal':
                        key = 'finish_collect_' + uuid4().hex[:8]
                        perform([dict(key=key, task='daily.collect')])
                    row = state['results'].get(key, {})
                    if row.get('task') != 'daily.collect' or row.get('status') != 'succeeded':
                        raise ValueError('新增待办未核验，保留游戏；修复后再次finish，不重跑日常')
                    after = False
                    for name, result in state['results'].items():
                        if name == key:
                            after = True
                        elif after and result.get('task') not in ('observe', 'navigation.home'):
                            raise ValueError('补领之后又执行了新任务，请重新daily.collect，不重用旧收尾结果')
                    app.cleanup_after_task(check_badges=False)
                    remaining = app._running_process_images(('MAA.exe', 'MuMuNxMain.exe', 'MuMuNxDevice.exe', 'MuMuVMMHeadless.exe'))
                    state.update(status='closed' if not remaining else 'cleanup_partial', cleanup_verified=not remaining,
                                 remaining=remaining)
                    ack.save(dict(status='returned', result=state['status']))
                    break
                if action == 'goal':
                    from receiver_goals_v1 import compile_goal, goal_steps
                    goal_inputs = command.get('inputs', {})
                    task, params = compile_goal(command['goal'], goal_inputs)
                    if BY_ID[task].route != 'session':
                        raise ValueError('该目标使用独立已有宿主；先结束本会话，再用run，不抢控制')
                    if not owner.ready:
                        raise ValueError('当前环境尚未恢复，先由AI处理页面后prepare')
                    state['goal'] = dict(id=command['goal'], requested=goal_inputs)
                    state.setdefault('goals', []).append(state['goal'])
                    perform(goal_steps(task, params, prefix='goal_' + uuid4().hex[:12]))
                elif action == 'run':
                    if not owner.ready:
                        raise ValueError('先完成环境恢复并发送 prepare；不重新启动另一控制器')
                    perform(command['steps'])
                elif action == 'prepare':
                    if not app._runtime_dependencies_ready() or app.goto_main_menu() is not True:
                        raise ValueError('当前环境/首页仍未核验')
                    owner.ready = True
                    capture('prepared')
                elif action in ('observe', 'tap', 'back', 'swipe', 'home', 'wait'):
                    if action in ('tap', 'swipe'):
                        current = state['frames'][-1]['seq'] if state['frames'] else None
                        if command.get('seq') != current:
                            raise ValueError('截图已变化，重新看新图后操作，不用旧截图序号')
                    if action == 'tap':
                        point = command['point']
                        if len(point) != 2 or any(type(n) is not int for n in point) or not (0 <= point[0] < 1920 and 0 <= point[1] < 1080):
                            raise ValueError('点击坐标必须在1920x1080原图内')
                        app.tap(*point)
                    elif action == 'back':
                        app.back()
                    elif action == 'swipe':
                        a, b = command['start'], command['end']
                        if any(len(p) != 2 or any(type(n) is not int for n in p) or not (0 <= p[0] < 1920 and 0 <= p[1] < 1080) for p in (a, b)):
                            raise ValueError('拖动坐标必须在原图内')
                        app.swipe(*a, *b, 700)
                    elif action == 'home':
                        app.goto_main_menu()
                    app.wait(min(10, max(.5, float(command.get('wait', 1)))))
                    capture(action)
                else:
                    raise ValueError('未知会话动作，不回退到整日日常')
                state['actions'].append(dict(command=command, status='returned'))
                ack.save(dict(status='returned', latest_seq=state['frames'][-1]['seq'] if state['frames'] else None))
            except Exception as exc:
                state.update(status='awaiting_ai', error=str(exc))
                ack.save(dict(status='needs_ai', error=str(exc)))
            sink.save(state)
        if state['status'] not in ('closed', 'cleanup_partial'):
            state['status'] = 'deadline_reached_environment_preserved'
    finally:
        state['controller_released'] = owner.release()
        state['finished_at'] = datetime.now(timezone.utc).isoformat()
        sink.save(state)
        pointer_path = Path(app.BASE) / 'runtime_state/public_receiver_owner.json'
        if state['controller_released'] and pointer_path.exists() and read(pointer_path).get('run_id') == run_id:
            pointer_path.unlink()
    return 0 if state.get('cleanup_verified') else 2


def submit(out, command):
    """A small command file, not a new owner or a completion receipt."""
    from ark_modules.core import ReceiptStore
    out = Path(out)
    state = read(out / 'receipt.json')
    if state.get('finished_at') or state.get('status') in ('closed', 'cleanup_partial'):
        raise ValueError('该会话已结束，不能向旧控制器提交')
    from tools.ark_cooperation_control import process_alive
    if process_alive(state.get('controller_pid')) is not True:
        raise ValueError('原控制器不在；先核已有业务效果，不盲目重跑')
    if command.get('action') == 'run':
        steps(command['steps'], state.get('results', {}))
    if command.get('action') == 'goal':
        from receiver_goals_v1 import compile_goal
        task, params = compile_goal(command['goal'], command.get('inputs', {}))
        validate(task, params)
        if BY_ID[task].route != 'session':
            raise ValueError('该目标需要独立宿主；先正常结束原会话再run')
    command = dict(command, run_id=state['run_id'])
    if command.get('action') in ('tap', 'swipe') and 'seq' not in command:
        raise ValueError('点按/拖动须提供刚看过的截图 seq')
    directory = out / 'commands'
    directory.mkdir(exist_ok=True)
    for ack in directory.glob('*.ack.json'):
        if read(ack).get('status') == 'dispatched':
            raise ValueError('前一动作尚未返回，先检查结果')
    name = directory / (str(time.time_ns()) + '-' + uuid4().hex[:8] + '.json')
    with name.open('x', encoding='utf-8') as stream:
        json.dump(command, stream, ensure_ascii=False, indent=2)
    return dict(status='submitted_not_completed', command=str(name), run_id=state['run_id'])
