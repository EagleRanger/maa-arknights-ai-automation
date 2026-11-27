"""Public receiver configuration. No author registry, history or game facts.

Package integrity is not live verification. The existing selected_scope seam
adapts the legacy development selector only after these local checks succeed.
"""
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import os
import sys

ROOT = Path(__file__).resolve().parent
PROFILE = 'config/receiver_profile.json'
ENTRY = 'run_daily_v167.py --mode full'
COMPONENT = 'ARK-PUBLIC-DAILY-V125'
HANDOFF = '.project-reasoning/AUTOMATION_HANDOFF.json'
BINDING = 'config/receiver_binding_v1.json'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def local(root, relative):
    path = (Path(root) / relative).resolve()
    path.relative_to(Path(root).resolve())
    return path


def profile(path=None, root=ROOT):
    path = Path(path or Path(root) / PROFILE).resolve()
    data = read(path)
    if data.get('schema_version') != 1:
        raise ValueError('本机配置 schema_version 必须为 1')
    for name in ('account_key', 'game_package', 'mumu_root', 'python'):
        if not isinstance(data.get(name), str) or not data[name].strip():
            raise ValueError('请填写本机配置字段：' + name)
    if data['game_package'] not in ('com.hypergryph.arknights', 'com.hypergryph.arknights.bilibili'):
        raise ValueError('当前公开接入支持国服官服/B服；其它渠道需要对应适配')
    resources = data.get('resources') or {}
    if resources.get('originium', 0) != 0 or resources.get('medicine', 0) != 0:
        raise ValueError('本版公共入口只使用现有理智，不使用源石或药剂')
    attempts = data.get('max_attempts', 5)
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise ValueError('max_attempts 应为 1 到 5')
    target = read(Path(root) / 'config/game_runtime_target_v1.json')
    if target.get('package') != data['game_package']:
        raise ValueError('本机配置与 MuMu 目标配置的游戏包不一致')
    if not all(str(target.get(k, '')).strip() for k in ('created_timestamp', 'android_version')):
        raise ValueError('请从本机 MuMu info 结果填写 created_timestamp 和 android_version')
    return data, path, target


def integrity(root=ROOT):
    root = Path(root)
    manifest = read(root / 'SOURCE_MANIFEST.json')
    rows = manifest.get('files')
    if manifest.get('kind') != 'source-integrity-only' or not isinstance(rows, list) or not rows:
        raise ValueError('发布源码清单缺失或格式错误')
    seen = set()
    for row in rows:
        name = row['path']
        if name in seen:
            raise ValueError('源码清单有重复路径：' + name)
        seen.add(name)
        if sha(local(root, name)) != row['sha256'].upper():
            raise ValueError('源码已改变，请合并并重新建立本地基线：' + name)
    required = {'ark.py', 'arknights_auto.py', 'receiver_setup_v1.py', 'receiver_catalog_v1.py',
                'receiver_session_v1.py', 'receiver_operations_v1.py', 'receiver_goals_v1.py',
                'receiver_sss_formation_v1.py', 'run_daily_v167.py'}
    if not required <= seen:
        raise ValueError('发布清单漏了统一入口：' + ', '.join(sorted(required - seen)))
    return dict(kind='source_integrity_verified', files_checked=len(rows),
                manifest_sha256=sha(root / 'SOURCE_MANIFEST.json'), live_verified=False)


def contract(data):
    ids = ('AUTH', 'WEEKLY', 'EVENT', 'MAINLINE', 'DAILY', 'REPORT', 'SSS', 'LONG')
    goals = [dict(id='G-' + name + '-001', status='active', target='接收方当前明确任务：' + name,
                  resource_policy=dict(existing_sanity_only=True, medicine=0, stone=0)) for name in ids]
    actions = ['annihilation', 'event_farm', 'event_task_claim', 'mainline', 'daily',
               'depot_maintain', 'orundum_rock_farm']
    if data.get('enable_sss_in_daily') is True:
        actions.append('security')
    return dict(schema_version=1, project='Arknights receiver: ' + data['account_key'],
        active_goals=goals,
        governance=dict(assistant_inference_may_change_goal=False, goal_change_requires_user_approval=True,
                        unknown_transition='pause_and_report'),
        hard_constraints=dict(unapproved_resource_fallback=False, difficulty_downgrade=False,
            max_mainline_attempts=5, max_event_attempts=5, unknown_cli_argument='fatal'),
        goal_memory=dict(revision='receiver-v1', time_classes=[dict(kind='current_user_task',
            goal_ids=[g['id'] for g in goals])],
            daily_clock=dict(long_term_cleanup_deadline='11:30', daily_automation_start='12:00',
                single_control_owner=True,
                note='旧引擎兼容字段，不创建定时任务；实际运行截止由调用参数决定'),
            transition_guards=dict(new_goal_insertion='current_explicit_user_instruction_then_recompile',
                insert_between_final_daily_and_cleanup='forbidden'),
            ordered_daily_flow=[dict(order=i + 1, action=a) for i, a in enumerate(actions)]),
        mode_actions={name: list(actions) for name in ('full', 'daily', 'event_today', 'event_first_clear',
            'mainline', 'annihilation', 'resource', 'event', 'event_verify', 'roguelike', 'reclamation', 'security')})


def initialise(path=None, root=ROOT):
    """Create only missing local bindings; never overwrite another installation."""
    root = Path(root)
    data, source, target = profile(path, root)
    checked = integrity(root)
    selected = dict(status='active', entrypoint=ENTRY, module='run_daily_v167',
                    component_id=COMPONENT, sha256=sha(root / 'run_daily_v167.py'), launcher_artifacts={})
    sink = root / BINDING
    if sink.exists():
        old = read(sink)
        if old.get('profile_sha256') != sha(source):
            raise ValueError('本机配置已修改；保留原绑定，请先检查差异，不覆盖本地修改')
        for name, value in old['managed_files'].items():
            if sha(local(root, name)) != value:
                raise ValueError('本机生成配置已被用户修改，保留并交 AI 合并：' + name)
        if old.get('source_manifest_sha256') != checked['manifest_sha256']:
            raise ValueError('已安装代码版本改变；请通过对话合并升级，不自动覆盖旧绑定')
        return dict(status='already_initialised', game_actions=0, binding=str(sink))
    files = {
        'PROJECT_CONTRACT.json': contract(data),
        'BUSINESS_RULES.json': dict(schema_version=1,
            origin='public-receiver-generated-not-author-history', business_rules=[
                dict(id='PUBLIC-SCOPE', rule='保留任务范围、实时理智和单控制者检查', severity='fatal',
                    check_type='code_pattern', changes_execution_flow=True, goal_refs=['G-AUTH-001'],
                    required_patterns=[r'_plan_allows\(', r'_capture_stamina_observation\(', r'acquire_single_instance\('])],
            ai_behavior_rules=[dict(id='PUBLIC-EVIDENCE', rule='只报告当前游戏真实效果，不重放未知提交')]),
        HANDOFF: dict(schema_version=1, status='active', handoff_id='receiver-' + uuid4().hex,
            origin='local_user_configuration', account_key=data['account_key'], daily_runtime=selected,
            entrypoint=ENTRY, production_snapshot_sha256=selected['sha256'],
            workflow_binding=dict(contract_goal_revision='receiver-v1'))}
    pending = root / 'config/receiver_init_pending.json'
    if pending.exists():
        saved = read(pending)
        if saved.get('profile_sha256') != sha(source) or saved.get('manifest_sha256') != checked['manifest_sha256']:
            raise ValueError('中断初始化的配置/源码已改变，保留现状交AI合并')
        if set(saved.get('files', {})) != set(files):
            raise ValueError('中断初始化记录格式不符，不覆盖文件')
        files = saved['files']
    else:
        for name in files:
            if local(root, name).exists():
                raise ValueError('已有工程配置不覆盖；继续使用原入口或由 AI 合并：' + name)
        pending.parent.mkdir(parents=True, exist_ok=True)
        with pending.open('x', encoding='utf-8') as stream:
            json.dump(dict(profile_sha256=sha(source), manifest_sha256=checked['manifest_sha256'],
                           files=files), stream, ensure_ascii=False, indent=2)
    # A partial initialisation resumes only exact generated bytes, not user edits.
    written = {}
    for name, value in files.items():
        dest = local(root, name)
        text = json.dumps(value, ensure_ascii=False, indent=2)
        expected = hashlib.sha256(text.encode('utf-8')).hexdigest().upper()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if sha(dest) != expected:
                raise ValueError('中断初始化后文件已修改，保留并交AI合并：' + name)
        else:
            with dest.open('x', encoding='utf-8', newline='') as stream:
                stream.write(text)
        written[name] = sha(dest)
    sink.parent.mkdir(parents=True, exist_ok=True)
    with sink.open('x', encoding='utf-8') as stream:
        json.dump(dict(schema_version=1, profile=str(source), profile_sha256=sha(source),
            source_manifest_sha256=checked['manifest_sha256'], managed_files=written,
            account_key=data['account_key'], live_verified=False), stream, ensure_ascii=False, indent=2)
    pending.unlink()
    return dict(status='initialised', game_actions=0, binding=str(sink), live_verified=False)


def configured(path=None, root=ROOT):
    data, source, target = profile(path, root)
    binding = read(Path(root) / BINDING)
    if binding.get('profile_sha256') != sha(source) or binding.get('account_key') != data['account_key']:
        raise ValueError('本机账号/配置与绑定不同，请检查配置差异')
    checked = integrity(root)
    if binding.get('source_manifest_sha256') != checked['manifest_sha256']:
        raise ValueError('本机绑定不属于当前代码版本，请先合并更新')
    for name, value in binding['managed_files'].items():
        if sha(local(root, name)) != value:
            raise ValueError('本机配置改变，需要合并而不是覆盖：' + name)
    return data, target, checked


def base_plan(data, root=ROOT):
    """Validate the published dynamic-333 policy's real input, not any JSON.

    Other layouts need their corresponding policy; never silently rewrite one
    into this account's/source author's layout.
    """
    value = data.get('base_plan')
    if not value:
        raise ValueError('请配置本账号的base_plan；当前动态生产接口使用四档333格式')
    path = local(root, value)
    plans = read(path).get('plans') or []
    if len(plans) != 4 or any(len((p.get('rooms') or {}).get('manufacture') or []) != 3 or
            len((p.get('rooms') or {}).get('trading') or []) != 3 for p in plans):
        raise ValueError('当前动态基建接口需要四档333排班；其它布局保留原方案，由本机AI接入对应策略，不强改')
    return path


@contextmanager
def environment(data, root=ROOT):
    """Resolve paths before importing the legacy runtime; no launch here."""
    from unittest.mock import patch
    values = {'ARKNIGHTS_MUMU_ROOT': data['mumu_root'], 'ARKNIGHTS_PYTHON': data['python'],
        'ARKNIGHTS_GAME_PACKAGE': data['game_package'], 'ARKNIGHTS_DEVICE': data.get('device', '127.0.0.1:0'),
        'ARKNIGHTS_MAA_ROOT': str(Path(root) / '.runtime_maa/MAA-App'),
        'ARKNIGHTS_MAA_PATH': str(Path(root) / '.runtime_maa/MAA-App/MAA.exe'),
        'ARKNIGHTS_AUTO_PROJECT_ROOT': str(root),
        'ARKNIGHTS_AUTO_BASE': str(root), 'ARK_SCRIPT_SCREENSHOT_BACKEND': 'adb'}
    with patch.dict(os.environ, values):
        yield


def preflight(data, target, *, probe=True, root=ROOT):
    checked = integrity(root)
    if not Path(data['python']).is_file():
        raise ValueError('配置的 Python 不存在')
    cli = Path(data['mumu_root']) / 'nx_main/mumu-cli.exe'
    if not cli.is_file():
        raise ValueError('配置的 MuMu CLI 不存在：' + str(cli))
    if not probe:
        return dict(checked, status='configuration_checked', game_actions=0, environment_probed=False)
    from daily_portable_bootstrap_v1 import preflight as maa_check
    from local_ocr_v6_small_v1 import preflight as ocr_check
    from daily_environment_final_boundary_v1 import require_desktop_identity
    from daily_runtime_target_v1 import inventory
    return dict(checked, status='PASS', game_actions=0, environment_probed=True,
        maa=maa_check(), ocr_model=ocr_check()['model'], execution_identity=require_desktop_identity(),
        target=inventory(cli, target))


@contextmanager
def base_scope(app):
    """Reuse existing verified base adapter in a reversible single-step scope."""
    from unittest.mock import patch
    from ark_host.runtime_services_v3 import boundary
    import daily_base_333_verified_execution_v1 as verified
    names = ('_apply_dynamic_333_infrast_config', 'run_maa_daily_tasks', 'wait_maa_complete',
             '_daily_base_333_verified_execution_v1_installed', '_base333_active_maa_scope')
    missing = object()
    old = {name: getattr(app, name, missing) for name in names}
    with boundary(app, base_policies=True), patch.object(verified, 'ACTIVE_CONFIG',
            Path(app.BASE) / 'runtime_state/base_333_active_single_plan.json'):
        try:
            verified.install(app)
            yield
        finally:
            for name, value in old.items():
                if value is missing:
                    if hasattr(app, name):
                        delattr(app, name)
                else:
                    setattr(app, name, value)


@contextmanager
def verified_event_scope(app, *, single=False):
    """Shared receiver wiring; no account facts or extra module execution."""
    from contextlib import ExitStack
    from unittest.mock import patch
    from os_reopen_route_v1 import boundary as reruns
    from event_map_reuse_v1 import boundary as maps
    from funded_activity_v1 import boundary as farm
    from scan_retry_v1 import boundary as scan
    with ExitStack() as stack:
        for ctx in (reruns(app),farm(app),scan(app),maps(app)):
            stack.enter_context(ctx)
        if single:
            from operator_training_return_v1 import boundary as training_return
            import event_layout_cooperation_v1 as layout
            from event_farm_evidence_v2 import configure
            stack.enter_context(training_return(app))
            stack.enter_context(patch.object(app,'_configure_new_event_farm_from_live_inventory',
                                             lambda ev:layout.configure(configure,app,ev)))
        yield


@contextmanager
def assembled(data, checked, main=None, root=ROOT, operations=()):
    """Reuse the shipped V167 graph and original public selected_scope seam.

    Replace the author-only development admission with package/config checks,
    not a made-up verified component history. All game gates remain installed.
    """
    from contextlib import ExitStack
    from unittest.mock import patch
    import arknights_daily_runtime_v12 as app
    if main is not None:
        # Single modules do not install the full daily bootstrap (which checks
        # unrelated current-event maps). Use the existing common host services.
        from ark_host.runtime_services_v3 import boundary as services
        from daily_runtime_target_v1 import boundary as target
        from daily_game_update_v1 import boundary as update
        from daily_login_supply_v4 import boundary as supply
        from event_daily_reward_chain_v1 import boundary as reward_chain
        from operator_home_labels_v1 import boundary as home
        from ocr_tolerance_v1 import boundary as tolerance
        import event_tl_task_rewards_v1 as task1
        import event_tl_task_rewards_v2 as task2
        import event_tl_task_rewards_v3 as task3
        import daily_client_update_gate_v1 as update_gate
        original_compile = app.compile_execution_plan
        def compile_plan(mode, **kwargs):
            kwargs['max_attempts'] = min(kwargs.get('max_attempts', 5), data.get('max_attempts', 5))
            return original_compile(mode, **kwargs)
        with ExitStack() as stack:
            stack.enter_context(patch.object(app, 'compile_execution_plan', compile_plan))
            stack.enter_context(patch.object(app, '_foreground_mumu_display', return_value=True))
            stack.enter_context(patch.object(app, '_consume_confirmed_red_expiring_potion', return_value=False, create=True))
            stack.enter_context(patch.object(app, 'ENABLE_SSS_IN_FULL', data.get('enable_sss_in_daily') is True))
            if data.get('base_plan'):
                stack.enter_context(patch.object(app, 'DYNAMIC_333_CONFIG', str(local(root, data['base_plan']))))
            stack.enter_context(patch.object(app, '_PUBLIC_TASK_MAX_ATTEMPTS', data.get('max_attempts', 5), create=True))
            # Base policies are entered only when that goal actually executes.
            # A later base goal must work even if this session began as rewards.
            if (data.get('current_goal') or {}).get('id')=='paradox':
                from daily_home_state_v1 import boundary as corrected_home
                stack.enter_context(corrected_home(app))
            for context in (target(app), services(app, base_policies=False),
                            update(app), home(app), tolerance(app), reward_chain(),
                            task1.boundary(app), task2.boundary(), task3.boundary(app)):
                stack.enter_context(context)
            stack.enter_context(patch.object(update_gate, 'BASE', supply))
            app._DAILY_EXISTING_SANITY_ONLY = True
            from poll_frames_v1 import boundary as frames
            from startup_transition_v1 import boundary as startup
            stack.enter_context(frames(app));stack.enter_context(startup(app))
            stack.enter_context(verified_event_scope(app,single=True))
            yield lambda: main(app)
        return
    from daily_dispatch_v1 import resolve, selected_scope
    import daily_resource_balance_v2 as balance
    import run_daily
    import run_daily_v167 as entry
    selected = resolve(read(Path(root) / HANDOFF))
    previous = list(sys.argv)
    try:
        with selected_scope(selected, checked), ExitStack() as stack:
            original_main = run_daily.main
            def final_consumer(*a, **k):
                # Execute after all legacy wrappers have rebuilt argv/hooks.
                app._DAILY_EXISTING_SANITY_ONLY = True
                if '--existing-sanity-only' not in sys.argv:
                    sys.argv.append('--existing-sanity-only')
                original_compile = app.compile_execution_plan
                def compile_plan(mode, **kwargs):
                    kwargs['max_attempts'] = min(kwargs.get('max_attempts', 5), data.get('max_attempts', 5))
                    return original_compile(mode, **kwargs)
                from operator_module_queue_v1 import daily as optional_modules
                from poll_frames_v1 import boundary as frames
                from startup_transition_v1 import boundary as startup
                with frames(app), startup(app), verified_event_scope(app), optional_modules(app), patch.object(app, 'compile_execution_plan', compile_plan), \
                     patch.object(app, '_foreground_mumu_display', return_value=True), \
                     patch.object(app, '_consume_confirmed_red_expiring_potion', return_value=False, create=True):
                    if main is not None:
                        return main(app)
                    with patch.object(run_daily, 'ENGINE_SHA256', sha(Path(root) / run_daily.ENGINE_FILE)):
                        return original_main(*a, **k)
            stack.enter_context(patch.object(run_daily, 'main', final_consumer))
            stack.enter_context(patch.object(app, 'ENABLE_SSS_IN_FULL', data.get('enable_sss_in_daily') is True))
            if data.get('base_plan'):
                selected_base = base_plan(data, root)
                stack.enter_context(patch.object(app, 'DYNAMIC_333_CONFIG', str(selected_base)))
                # Legacy bootstrap reads this source before the runtime global.
                # It must consume the recipient's actual plan, not a missing
                # author-side default or merely the display path above.
                stack.enter_context(patch.object(balance, 'SOURCE_CONFIG', selected_base))
            stack.enter_context(patch.object(app, '_foreground_mumu_display', return_value=True))
            sys.argv = [str(Path(root) / 'run_daily.py'), '--mode', 'full', '--existing-sanity-only']
            yield lambda: entry.full()
    finally:
        sys.argv = previous
