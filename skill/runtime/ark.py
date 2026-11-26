"""Public Arknights command entry. No action is the default action.

list/describe/template/init/check are distinct from run. No GUI, author Loop,
private component registry, guessed function names or generated controller.
"""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import argparse
import json
import subprocess
import sys
import time

import receiver_setup_v1 as setup
from receiver_catalog_v1 import BY_ID, describe, validate
from receiver_goals_v1 import BY_GOAL, describe as describe_goals, compile_goal, goal_steps

ROOT = Path(__file__).resolve().parent


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def output_path(value):
    path = setup.local(ROOT, value)
    path.relative_to((ROOT / 'outputs').resolve())
    return path


def await_tool_frame(out, *, seconds=180, clock=time.monotonic, sleep=time.sleep):
    """A launcher PID is not a ready service port. Keep the same live owner."""
    from tools.ark_cooperation_control import process_alive
    end = clock() + seconds
    while clock() < end:
        identity = out / 'owner_process.json'
        if identity.is_file() and process_alive(setup.read(identity).get('pid')) is not True:
            raise ValueError('原玩法控制器不在，先核原结果，不重启或重放')
        receipt = out / 'receipt.json'
        if receipt.is_file():
            row = setup.read(receipt)
            if row.get('finished_at'):
                raise ValueError('原玩法会话已结束，先核原结果')
            if row.get('frames'):
                if row.get('home_verified') is not True:
                    raise ValueError('原环境已留图等待AI接回；不在未知页启动作战：' + str(out))
                return row
        sleep(.5)
    raise ValueError('原玩法启动尚未就绪，保留该会话供AI处理：' + str(out))


def checked_inputs(task, file=None):
    value = setup.read(file) if file else {}
    validate(task, value)
    return value


def task_files(task):
    return {
        'operator.training': ['runtime_state/operator_training_plan.json'],
        'operator.module.inspect': ['runtime_state/operator_module_plan.json'],
        'operator.module.mission': ['runtime_state/operator_module_plan.json'],
        'operator.module.unlock': ['runtime_state/operator_module_plan.json'],
        'operator.module.upgrade': ['runtime_state/operator_module_plan.json'],
        'vouchers.red.submit': ['runtime_state/red_catalyst_plan.json'],
        'vouchers.red.verify': ['runtime_state/red_catalyst_plan.json'],
        'goal.module': ['runtime_state/operator_module_plan.json'],
        'goal.red_catalyst': ['runtime_state/red_catalyst_plan.json'],
    }.get(task, [])


def check_task(task, inputs, data):
    row = validate(task, inputs)
    if task == 'daily.custom':
        selected = goal_steps(task, inputs)
        checked = [dict(task=step['task'], result=check_task(step['task'], step.get('inputs', {}), data))
                   for step in selected]
        return dict(status='selected_modules_checked', modules=checked)
    missing = [p for p in task_files(task) if not (ROOT / p).is_file()]
    if task in ('base.prepare', 'base.infrast', 'daily.full', 'daily.final', 'goal.base'):
        if not data.get('base_plan') or not setup.local(ROOT, data['base_plan']).is_file():
            missing.append('receiver_profile.base_plan 指向的实际基建配置')
    if missing:
        raise ValueError('只缺本任务的配置，不必重读源码：' + ', '.join(missing))
    if task in ('base.prepare', 'base.infrast', 'daily.full', 'daily.final', 'goal.base'):
        setup.base_plan(data, ROOT)
    if row.route == 'session-tool':
        return dict(status='requires_live_session', task=task,
            next='先用observe开启/读取原会话，再由AI导航至报价页；此任务不会另开游戏')
    return dict(status='task_configuration_checked', task=task, route=row.route)


def long_packet(data, inputs, out):
    """Compile the old V9 packet from this user's explicit choices only."""
    end = datetime.fromisoformat(inputs['deadline'])
    now = datetime.now(timezone.utc)
    if end.tzinfo is None or now >= end:
        raise ValueError('肉鸽截止须带时区且尚未到达')
    for name in ('core_char', 'squad', 'roles'):
        if not isinstance(inputs[name], str) or not inputs[name].strip():
            raise ValueError('肉鸽需用户选定：' + name)
    existing = setup.read(ROOT / setup.HANDOFF)
    old = existing.get('current_roguelike_progress') or {}
    if old.get('status') == 'active':
        old_output = setup.local(ROOT, setup.read(setup.local(ROOT, old['handoff']))['output'])
        checkpoint = old_output / 'checkpoint.json'
        if not checkpoint.is_file() or not setup.read(checkpoint).get('finished_at'):
            raise ValueError('已有长期肉鸽任务，先核原owner/结果，不创建第二个')
    if out.exists() and any(out.iterdir()):
        raise ValueError('原运行目录已有记录，先核原结果')
    run_id = 'sami-' + now.strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8]
    manifest = setup.read(ROOT / 'SOURCE_MANIFEST.json')
    packet = dict(run_id=run_id, workflow='ARK-SAMI-PROGRESS-V9', theme='Sami',
        authority='当前用户通过公共入口下达的肉鸽任务', not_before=now.isoformat(), deadline=end.isoformat(),
        daily_replay=False, recording=False, output=str(out.relative_to(ROOT)).replace('\\', '/'),
        exploration=dict(core_char=inputs['core_char'], squad=inputs['squad'], roles=inputs['roles'],
                         difficulty='highest_unlocked'),
        artifacts={r['path']: r['sha256'].upper() for r in manifest['files']})
    directory = ROOT / 'outputs/continuations'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (run_id + '.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(packet, stream, ensure_ascii=False, indent=2)
    existing['current_roguelike_progress'] = dict(status='active', workflow=packet['workflow'],
        handoff=str(path.relative_to(ROOT)).replace('\\', '/'), handoff_sha256=setup.sha(path))
    # Only update an unchanged binding created by init, never somebody's file.
    binding = setup.read(ROOT / setup.BINDING)
    if setup.sha(ROOT / setup.HANDOFF) != binding['managed_files'][setup.HANDOFF]:
        raise ValueError('本地任务绑定已被修改，保留并交AI合并')
    from ark_modules.core import ReceiptStore
    ReceiptStore(ROOT / setup.HANDOFF).save(existing)
    binding['managed_files'][setup.HANDOFF] = setup.sha(ROOT / setup.HANDOFF)
    ReceiptStore(ROOT / setup.BINDING).save(binding)
    return path


def run_task(args, *, internal=False):
    if internal:
        task = args.task
        inputs = checked_inputs(task, args.inputs)
        goal = None
    else:
        goal_inputs = player_inputs(args)
        task, inputs = compile_goal(args.task, goal_inputs)
        validate(task, inputs)
        goal = dict(id=args.task, requested=goal_inputs)
    row = BY_ID[task]
    if row.route == 'offline':
        if task in ('module.list','module.add'):
            from player_module_v1 import offline
            import os
            emit(offline(Path(os.environ.get('ARKNIGHTS_AUTO_BASE') or ROOT),task,inputs))
            return 0
        from voucher_exchange_plan_v1 import service
        emit(service(ROOT))
        return 0
    if row.route == 'session-tool':
        from receiver_operations_v1 import session_tool
        if not args.output:
            raise ValueError('此任务须指向正在运行的原会话 --output')
        check_task(task, inputs, {})
        result = session_tool(task, output_path(args.output), inputs)
        emit(dict(status='helper_returned_not_business_completion', task=task, result=result))
        return 0
    data, target, checked = setup.configured(args.profile)
    data = dict(data, _source_manifest_sha256=checked['manifest_sha256'])
    if goal is not None:
        data = dict(data, current_goal=goal)
    check_task(task, inputs, data)
    if row.route == 'session' and goal is not None:
        pointer = ROOT / 'runtime_state/public_receiver_owner.json'
        if pointer.exists():
            active = setup.read(pointer)
            from tools.ark_cooperation_control import process_alive
            if process_alive(active.get('controller_pid')) is True:
                if (active.get('account_key') != data['account_key'] or
                        active.get('game_package') != data['game_package'] or
                        active.get('source_manifest_sha256') != checked['manifest_sha256']):
                    raise ValueError('现有控制器不属于当前账号/版本，不自动接管')
                if args.output and output_path(args.output) != output_path(active['output']):
                    raise ValueError('已有原会话，请使用其返回的目录，不另开或静默换目录')
                from receiver_session_v1 import submit
                receipt_path=output_path(active['output'])/'receipt.json'
                if not receipt_path.is_file():raise ValueError('原控制器没有可核实的回执，不追加或重开')
                receipt=setup.read(receipt_path)
                if receipt.get('run_id')!=active.get('run_id') or receipt.get('controller_pid')!=active.get('controller_pid'):
                    raise ValueError('控制器与回执不一致，不追加或重开')
                from receiver_resume_v1 import decision
                last=receipt.get('goal') or {}
                if last.get('id') and compile_goal(last['id'],last.get('requested') or {})==(task,inputs):
                    emit(dict(output=active['output'],**decision(receipt)));return 0
                if decision(receipt)['next'] not in ('finish',):
                    raise ValueError('原目标未结清。先看 status；用户明确改目标时才用 continue。')
                emit(submit(output_path(active['output']), dict(action='goal', goal=goal['id'], inputs=goal['requested'])))
                return 0
    default_name = ('spa-trial-' if task == 'spa.trial' else 'goal-') + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8]
    out = output_path(args.output or 'outputs/' + default_name) if row.route != 'daily' else None
    if out is not None:
        emit(dict(status='goal_started_not_completed', goal=goal, output=str(out)))
    with setup.environment(data):
        checked.update(setup.preflight(data, target))
        if row.route == 'tool':
            if task == 'spa.trial':
                if not out.name.startswith('spa-trial-'):
                    raise ValueError('卫戍目录名须以spa-trial-开头')
                tool = str(ROOT / row.implementation)
                # Resource sync/preflight is preparation, not a native battle.
                subprocess.run([data['python'], tool, '--output', str(out), '--prepare'], cwd=ROOT, check=True)
                launched = subprocess.call([data['python'], tool, '--output', str(out)], cwd=ROOT)
                if launched:
                    return launched
                # Human goal means start the cycle, not merely open a worker
                # waiting for the caller to discover a second service command.
                await_tool_frame(out)
                return subprocess.call([data['python'], tool, '--output', str(out), '--action', 'service'], cwd=ROOT)
            path = long_packet(data, inputs, out)
            return subprocess.call([data['python'], str(ROOT / row.implementation), '--handoff', str(path)], cwd=ROOT)
        if row.route == 'daily':
            with setup.assembled(data, checked) as execute:
                result = execute()
            emit(dict(status='daily_returned_read_actual_manifest', exit_code=result,
                      evidence_directory=str(ROOT / 'outputs/run_manifests')))
            return int(result or 0)
        from receiver_session_v1 import serve
        rows = goal_steps(task, inputs)
        with setup.assembled(data, checked, lambda app: serve(app, rows, out, data, deadline=args.deadline),
                             operations=[r['task'] for r in rows]) as execute:
            return int(execute() or 0)


def player_inputs(args):
    v=setup.read(args.inputs) if args.inputs else {}
    for attr,key in [('operator','operator'),('branch','branch'),('level','target_level'),('action','action')]:
        value=getattr(args,attr,None)
        if value is not None:
            if args.task!='module' or key in v:raise ValueError('模组专用参数不能重复或用于其他目标')
            v[key]=value
    return v


def main(argv=None):
    parser = argparse.ArgumentParser(description='明日方舟公共接口；不带子命令只显示帮助，不启动游戏')
    subs = parser.add_subparsers(dest='command')
    subs.add_parser('list', help='列出所有功能、实际入口和成熟度')
    p = subs.add_parser('describe', help='查看业务目标、参数和支持范围')
    p.add_argument('task', choices=tuple(BY_GOAL))
    p = subs.add_parser('template', help='输出目标参数模板；不会执行')
    p.add_argument('task', choices=tuple(BY_GOAL))
    p = subs.add_parser('init', help='按本机配置生成可运行绑定；不覆盖用户修改、不启动游戏')
    p.add_argument('--profile')
    p = subs.add_parser('check', help='只检查配置/源码；--probe附加本机环境检查，不开游戏')
    p.add_argument('--profile'); p.add_argument('--task', choices=tuple(BY_GOAL))
    p.add_argument('--inputs'); p.add_argument('--probe', action='store_true')
    p = subs.add_parser('run', help='执行用户业务目标；内部步骤由脚本安排')
    p.add_argument('task', choices=tuple(BY_GOAL)); p.add_argument('--profile')
    p.add_argument('--inputs'); p.add_argument('--output'); p.add_argument('--deadline')
    p = subs.add_parser('sequence', help='高级配套：内部步骤清单，不是正常调用必经步骤')
    p.add_argument('--plan', required=True); p.add_argument('--profile'); p.add_argument('--output', required=True)
    p.add_argument('--deadline')
    p = subs.add_parser('status', help='读原会话结果、截图和待处理动作，不重复启动')
    p.add_argument('--output', required=True)
    p = subs.add_parser('action', help='向原会话提交AI按实图决定的操作，不开第二个控制器')
    p.add_argument('--output', required=True); p.add_argument('--json', required=True, help='命令JSON文件')
    p = subs.add_parser('append', help='向原会话添加明确模块，只补未完/新增项')
    p.add_argument('--output', required=True); p.add_argument('--plan', required=True)
    p = subs.add_parser('finish', help='结束本次任务：内部补收新待办后关闭，不重跑日常')
    p.add_argument('--output', required=True); p.add_argument('--collection-key')
    p = subs.add_parser('continue', help='在原会话继续一个业务目标，不手工拼内部步骤')
    p.add_argument('task', choices=tuple(BY_GOAL)); p.add_argument('--output', required=True); p.add_argument('--inputs')
    p = subs.add_parser('debug', help='异常接回/研发配套，不是用户业务目标')
    p.add_argument('operation', choices=('list', 'describe', 'run'))
    p.add_argument('task', nargs='?', choices=tuple(BY_ID)); p.add_argument('--profile')
    p.add_argument('--inputs'); p.add_argument('--output'); p.add_argument('--deadline')
    p=subs.add_parser('plan',help='预览玩家请求将执行的目标；不配置账号、不操作游戏')
    p.add_argument('task',choices=tuple(BY_GOAL));p.add_argument('--inputs')
    for n in ('plan','run','continue'):
        cmd=subs.choices[n]
        cmd.add_argument('--operator');cmd.add_argument('--branch');cmd.add_argument('--level',type=int)
        cmd.add_argument('--action',choices=('list','add','next','develop','inspect'))
    p=subs.add_parser('resume',help='按原会话回执续一个未执行的步骤；不重放已完成或不明操作')
    p.add_argument('--output',required=True);p.add_argument('--check-only',action='store_true')
    args = parser.parse_args(argv)
    if args.command=='plan':
        task,v=compile_goal(args.task,player_inputs(args));validate(task,v)
        emit(dict(task=task,inputs=v,game_actions=0));return 0
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == 'list':
        emit(describe_goals()); return 0
    if args.command == 'describe':
        emit(describe_goals(args.task)[0]); return 0
    if args.command == 'template':
        emit(BY_GOAL[args.task].template); return 0
    if args.command == 'debug':
        if args.operation == 'list':
            emit(describe()); return 0
        if not args.task:
            raise ValueError('调试配套须明确内部操作，不自动选择业务')
        if args.operation == 'describe':
            emit(describe(args.task)[0]); return 0
        return run_task(args, internal=True)
    if args.command == 'init':
        emit(setup.initialise(args.profile)); return 0
    if args.command == 'check':
        data, target, checked = setup.configured(args.profile)
        if args.task:
            task, inputs = compile_goal(args.task, setup.read(args.inputs) if args.inputs else {})
            checked['goal'] = args.task
            checked['task'] = check_task(task, inputs, data)
        if args.probe:
            with setup.environment(data):
                checked.update(setup.preflight(data, target))
        emit(dict(checked, game_actions=0)); return 0
    if args.command == 'run':
        return run_task(args)
    out = output_path(args.output)
    if args.command in ('status','resume'):
        receipt = setup.read(out / 'receipt.json')
        from receiver_resume_v1 import decision
        from tools.ark_cooperation_control import process_alive
        preview=args.command=='resume' and args.check_only
        # A portable dry run only interprets this saved receipt. No OS
        # process query is needed. Real dispatch still checks PID and owner.
        if preview:
            advice=decision(receipt,alive=True)
            advice.update(owner_check='not_performed_preview_only',game_actions=0,
                          dispatch='须在实际续跑时匹配原控制器；预览不会提交')
        else:
            advice=decision(receipt,alive=process_alive(receipt.get('controller_pid')) is True)
        if args.command=='resume' and not args.check_only and advice['next']=='continue_remaining':
            from receiver_session_v1 import submit
            active=setup.read(ROOT/'runtime_state/public_receiver_owner.json')
            if active.get('run_id')!=receipt.get('run_id') or output_path(active['output'])!=out:
                raise ValueError('归属变化，不续跑')
            emit(submit(out,dict(action='resume_remaining')));return 0
        emit(dict(advice,goal=receipt.get('goal'),error=receipt.get('error'),cleanup_verified=receipt.get('cleanup_verified')))
        return 0
    if args.command == 'sequence':
        from receiver_session_v1 import steps, serve
        rows = steps(setup.read(args.plan))
        data, target, checked = setup.configured(args.profile)
        for row in rows:
            check_task(row['task'], row.get('inputs', {}), data)
        with setup.environment(data):
            checked.update(setup.preflight(data, target))
            with setup.assembled(data, checked, lambda app: serve(app, rows, out, data, deadline=args.deadline),
                                 operations=[r['task'] for r in rows]) as execute:
                return int(execute() or 0)
    from receiver_session_v1 import submit
    if args.command == 'continue':
        emit(submit(out, dict(action='goal', goal=args.task, inputs=player_inputs(args))))
    elif args.command == 'action':
        emit(submit(out, setup.read(args.json)))
    elif args.command == 'append':
        emit(submit(out, dict(action='run', steps=setup.read(args.plan))))
    elif args.command == 'finish':
        emit(submit(out, dict(action='finish', collection_key=args.collection_key) if args.collection_key
                        else dict(action='finish_goal')))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        emit(dict(status='needs_configuration_or_ai', error=str(exc), game_completion_claimed=False))
        raise SystemExit(2)
