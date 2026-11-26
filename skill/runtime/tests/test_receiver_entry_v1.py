"""Public entry regressions. All external operations are forbidden/faked I/O."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import ast
import hashlib
import importlib
import json
import sys
import unittest
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ark
import receiver_catalog_v1 as catalogue
import receiver_goals_v1 as goals
import receiver_setup_v1 as setup
import receiver_session_v1 as host


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def fixture(root):
    names = ('ark.py', 'arknights_auto.py', 'receiver_setup_v1.py', 'receiver_catalog_v1.py',
             'receiver_session_v1.py', 'receiver_operations_v1.py', 'receiver_goals_v1.py',
             'receiver_sss_formation_v1.py', 'run_daily_v167.py')
    for name in names:
        (root / name).write_text('# isolated integrity fixture\n', encoding='utf-8')
    save(root / 'SOURCE_MANIFEST.json', dict(kind='source-integrity-only', files=[
        dict(path=n, sha256=setup.sha(root / n)) for n in names]))
    save(root / 'config/game_runtime_target_v1.json',
         dict(package='com.hypergryph.arknights', created_timestamp='11111', android_version='15.0'))
    data = dict(schema_version=1, account_key='recipient-fixture', game_package='com.hypergryph.arknights',
                mumu_root='fixture-only', python=sys.executable, resources=dict(originium=0, medicine=0))
    path = root / setup.PROFILE
    save(path, data)
    return path, data


class PublicEntryTests(unittest.TestCase):
    def test_daily_choices_keep_order_and_disabled_modules_never_become_full(self):
        selected = {'modules': ['base', {'task': 'annihilation', 'enabled': False}, 'recruit', 'mall', 'award']}
        task, params = goals.compile_goal('daily', selected)
        self.assertEqual(task, 'daily.custom')
        rows = goals.goal_steps(task, params)
        self.assertEqual([r['task'] for r in rows], ['goal.base', 'daily.recruit', 'daily.mall', 'daily.award'])
        self.assertEqual(len({r['key'] for r in rows}), 4)
        self.assertNotIn('daily.full', [r['task'] for r in rows])
        self.assertEqual(goals.compile_goal('daily', {}), ('daily.full', {}))
        host.steps(rows)

    def test_daily_module_parameters_are_forwarded_or_explicitly_rejected(self):
        task, params = goals.compile_goal('daily', {'modules': [
            {'task': 'farm', 'inputs': {'kind': 'resource', 'stage': '1-7', 'times': 10}},
            {'task': 'base', 'inputs': {'action': 'drones', 'target': {'room': 'manufacture', 'index': 1}}}]})
        rows = goals.goal_steps(task, params)
        self.assertEqual(rows[0]['task'], 'resource.farm')
        self.assertEqual(rows[0]['inputs'], {'stage': '1-7', 'times': 10})
        self.assertEqual(rows[1]['task'], 'base.drones')
        for value in ({'modules': []}, {'modules': [{'task': 'mall', 'enabled': False}]},
                      {'modules': [{'task': 'recruit', 'inputs': {'select': [5]}}]},
                      {'modules': ['not-real']}, {'unknown': True}):
            with self.assertRaises(ValueError):
                goals.compile_goal('daily', value)

    def test_custom_daily_only_checks_dependencies_of_selected_modules(self):
        self.assertEqual(ark.check_task('daily.custom', {'modules': ['recruit', 'award']}, {})['status'],
                         'selected_modules_checked')
        with self.assertRaisesRegex(ValueError, 'base_plan'):
            ark.check_task('daily.custom', {'modules': ['base', 'award']}, {})

    def test_custom_daily_cli_reaches_original_module_host_instead_of_full(self):
        from contextlib import contextmanager, nullcontext
        app = object()
        observed = []
        @contextmanager
        def assembled(data, checked, main=None, root=None, operations=()):
            self.assertIsNotNone(main, 'custom daily must not select legacy full')
            observed.extend(operations)
            yield lambda: main(app)
        with TemporaryDirectory() as directory, patch.object(ark, 'ROOT', Path(directory)):
            source = Path(directory) / 'daily.json'
            save(source, {'modules': ['mall', 'recruit', 'award']})
            data = dict(account_key='fixture', game_package='fixture.game', python=sys.executable)
            with patch.object(setup, 'configured', return_value=(data, {}, {'manifest_sha256': 'fixture'})), \
                 patch.object(setup, 'environment', return_value=nullcontext()), \
                 patch.object(setup, 'preflight', return_value={}), \
                 patch.object(setup, 'assembled', assembled), patch.object(host, 'serve', return_value=0) as serve, \
                 patch('builtins.print'):
                self.assertEqual(ark.main(['run', 'daily', '--inputs', str(source)]), 0)
            self.assertEqual(observed, ['daily.mall', 'daily.recruit', 'daily.award'])
            self.assertIs(serve.call_args.args[0], app)
            self.assertEqual([r['task'] for r in serve.call_args.args[1]], observed)

    def test_public_choices_are_discoverable_and_stronghold_never_drops_user_parameters(self):
        row = goals.describe('daily')[0]
        self.assertIn('recruit', row['selectable_modules'])
        self.assertIn('--inputs', row['custom_command'])
        for params in ({'operators': ['维什戴尔']}, {'difficulty': 2}):
            with self.assertRaisesRegex(ValueError, '不丢弃'):
                goals.compile_goal('stronghold', params)

    def test_base_scope_reuses_verified_adapter_and_restores_only_its_hooks(self):
        from contextlib import nullcontext
        import daily_base_333_verified_execution_v1 as verified
        original = lambda *a, **k: True
        app = SimpleNamespace(BASE=Path('isolated-fixture'), run_maa_daily_tasks=original,
            wait_maa_complete=original, _apply_dynamic_333_infrast_config=original, log=lambda *a: None)
        active = verified.ACTIVE_CONFIG
        with patch('ark_host.runtime_services_v3.boundary', return_value=nullcontext()):
            with setup.base_scope(app):
                self.assertTrue(app._daily_base_333_verified_execution_v1_installed)
                self.assertTrue(getattr(app.wait_maa_complete, '_daily_base_333_verified_execution_v1', False))
                self.assertEqual(verified.ACTIVE_CONFIG, app.BASE / 'runtime_state/base_333_active_single_plan.json')
        self.assertIs(app.wait_maa_complete, original)
        self.assertIs(app._apply_dynamic_333_infrast_config, original)
        self.assertFalse(hasattr(app, '_daily_base_333_verified_execution_v1_installed'))
        self.assertEqual(verified.ACTIVE_CONFIG, active)

    def test_mainline_reads_actual_native_summary_and_new_map_not_fictional_fields(self):
        from receiver_operations_v1 import binding
        calls = []
        app = SimpleNamespace(_stage_chapter=lambda _: 3, _RUN_SUMMARY={},
            _maa_task_queue_running=lambda: False, shot=lambda _: 'new-map.png',
            verify_stage_cleared=lambda ch, stage: calls.append(('verify', ch, stage)) or (True, True))
        def execute(**kwargs):
            calls.append(kwargs)
            app._RUN_SUMMARY['mainline'] = dict(starting_target='3-4', targeted=True, status='completed')
            return True
        app.mode_mainline = execute
        _, handler = binding('mainline.stage')
        session = SimpleNamespace(app=app)
        row = handler(session, dict(stage='3-4', layer='normal', max_attempts=5), None, {}, None)
        self.assertEqual(row.status, 'succeeded')
        self.assertEqual(row.evidence, ('new-map.png',))
        self.assertEqual(calls[-1], ('verify', 3, '3-4'))
        calls.clear()
        row = handler(session, dict(stage='3-4', layer='hard', max_attempts=5), None, {}, None)
        self.assertEqual(row.status, 'blocked')
        self.assertFalse(calls)

    def test_mainline_true_return_for_shelved_is_never_success(self):
        from receiver_operations_v1 import binding
        app = SimpleNamespace(_stage_chapter=lambda _: 3,
            _RUN_SUMMARY={'mainline': dict(starting_target='3-4', targeted=True, status='shelved')},
            mode_mainline=lambda **kwargs: True, shot=lambda _: 'pending.png')
        _, handler = binding('mainline.stage')
        row = handler(SimpleNamespace(app=app), dict(stage='3-4', layer='normal', max_attempts=5), None, {}, None)
        self.assertEqual(row.status, 'partial')

    def test_base_policy_input_is_real_and_does_not_rewrite_other_layout(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = {'plans': [{'rooms': {'manufacture': [{}] * 2, 'trading': [{}] * 4}}]}
            path = root / 'own.json'
            save(path, original)
            with self.assertRaises(ValueError):
                setup.base_plan({'base_plan': 'own.json'}, root)
            self.assertEqual(setup.read(path), original)
            own = setup.read(ROOT / 'config/base_orundum_333_dynamic_v1.example.json')
            save(path, own)
            self.assertEqual(setup.base_plan({'base_plan': 'own.json'}, root), path)

    def test_stronghold_goal_dispatches_cycle_not_just_empty_worker(self):
        from contextlib import nullcontext
        with TemporaryDirectory() as directory, patch.object(ark, 'ROOT', Path(directory)):
            data = dict(account_key='own', game_package='own.game', python=sys.executable)
            args = SimpleNamespace(task='stronghold', inputs=None, profile=None, output=None, deadline=None)
            with patch.object(setup, 'configured', return_value=(data, {}, {'manifest_sha256': 'own'})), \
                 patch.object(setup, 'environment', return_value=nullcontext()), patch.object(setup, 'preflight', return_value={}), \
                 patch.object(ark.subprocess, 'run') as prepare, \
                 patch.object(ark.subprocess, 'call', return_value=0) as invoke, \
                 patch.object(ark, 'await_tool_frame') as ready, patch('builtins.print'):
                self.assertEqual(ark.run_task(args), 0)
                self.assertIn('--prepare', prepare.call_args.args[0])
                self.assertEqual(len(invoke.call_args_list), 2)
                self.assertNotIn('--action', invoke.call_args_list[0].args[0])
                self.assertEqual(invoke.call_args_list[1].args[0][-2:], ['--action', 'service'])
                ready.assert_called_once()

    def test_standalone_goal_waits_for_actual_frame_not_only_launcher_pid(self):
        with TemporaryDirectory() as directory:
            out = Path(directory)
            save(out / 'owner_process.json', {'pid': 123})
            save(out / 'receipt.json', {'status': 'preparing', 'frames': []})
            slept = []
            def sleep(_):
                slept.append(1)
                save(out / 'receipt.json', {'home_verified': True, 'frames': [{'seq': 1}]})
            with patch('tools.ark_cooperation_control.process_alive', return_value=True):
                self.assertTrue(ark.await_tool_frame(out, sleep=sleep)['home_verified'])
                self.assertEqual(len(slept), 1)
                save(out / 'receipt.json', {'home_verified': False, 'frames': [{'seq': 2}]})
                with self.assertRaisesRegex(ValueError, '未知页'):
                    ark.await_tool_frame(out, sleep=sleep)

    def test_finish_and_continue_take_goals_not_step_lists(self):
        with TemporaryDirectory() as directory, patch.object(ark, 'ROOT', Path(directory)), \
             patch.object(host, 'submit', return_value={'status': 'submitted_not_completed'}) as submit, \
             patch('builtins.print'):
            self.assertEqual(ark.main(['finish', '--output', 'outputs/original']), 0)
            self.assertEqual(submit.call_args.args[1], {'action': 'finish_goal'})
            self.assertEqual(ark.main(['continue', 'base', '--output', 'outputs/original']), 0)
            self.assertEqual(submit.call_args.args[1], {'action': 'goal', 'goal': 'base', 'inputs': {}})

    def test_reuse_current_account_session_without_new_environment(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save(root / 'runtime_state/public_receiver_owner.json', dict(controller_pid=123,run_id='live',
                output=str(root / 'outputs/original'), account_key='own', game_package='own.game',
                source_manifest_sha256='own-version'))
            save(root/'outputs/original/receipt.json',dict(run_id='live',controller_pid=123,
                requested_steps=[dict(key='prior',task='daily.mall')],environment_ready=True,
                results={'prior':dict(status='succeeded',evidence=['checked'])}))
            args = SimpleNamespace(task='activity-rewards', inputs=None, profile=None, output=None, deadline=None)
            data = dict(account_key='own', game_package='own.game')
            with patch.object(ark, 'ROOT', root), \
                 patch.object(setup, 'configured', return_value=(data, {}, {'manifest_sha256': 'own-version'})), \
                 patch('tools.ark_cooperation_control.process_alive', return_value=True), \
                 patch.object(host, 'submit', return_value={'status': 'submitted_not_completed'}) as submit, \
                 patch.object(setup, 'preflight', side_effect=AssertionError('no second environment')), \
                 patch('builtins.print'):
                self.assertEqual(ark.run_task(args), 0)
                self.assertEqual(submit.call_args.args[0], root / 'outputs/original')
                self.assertEqual(submit.call_args.args[1]['goal'], 'activity-rewards')
                args.output = 'outputs/different'
                with self.assertRaises(ValueError):
                    ark.run_task(args)

    def test_goal_finish_collects_internally_and_failed_collection_keeps_environment(self):
        from ark_modules.core import Result
        from contextlib import contextmanager
        for collect_ok in (True, False):
            with self.subTest(collect_ok=collect_ok), TemporaryDirectory() as directory:
                root = Path(directory)
                out = root / 'outputs/test'
                calls = []
                app = SimpleNamespace(BASE=root, PKG='own.game', _RUN_SUMMARY={},
                    _initialize_current_run_evidence_boundary=lambda: None,
                    _ensure_execution_plan=lambda _: object(), _maa_task_queue_running=lambda: False,
                    cleanup_after_task=lambda **_: calls.append('close'),
                    _running_process_images=lambda _: [])
                class Owner:
                    def __init__(self, app, *, owner, clock, deadline):
                        self.deadline, self.ready = deadline, False
                    def acquire(self): return True
                    def owns(self, *a): return True
                    def start(self): self.ready = True; return True
                    def release(self): return True
                class Session:
                    def __init__(self, app, output, **kw): self.events = {}
                    def execute(self, task, inputs, context, previous):
                        calls.append(task)
                        return Result('succeeded' if task != 'daily.collect' or collect_ok else 'partial',
                                      'synthetic-result', ('synthetic-frame',))
                loops = []
                def sleep(_):
                    if not loops:
                        save(out / 'commands/finish.json', {'action': 'finish_goal'})
                        loops.append(1)
                    else:
                        raise RuntimeError('test end after retained failed collection')
                with patch('ark_host.environment.EnvironmentOwner', Owner), \
                     patch('receiver_operations_v1.Session', Session), patch.object(ark, 'check_task'), \
                     patch('operator_optional_inspection_v1.frame', return_value={'screenshot': 'synthetic-frame'}), \
                     patch('builtins.print'):
                    if collect_ok:
                        self.assertEqual(host.serve(app, [dict(key='requested', task='roguelike.rewards',
                            inputs={'theme': 'Sami'})], out, dict(account_key='own', game_package='own.game'), sleep=sleep), 0)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'test end'):
                            host.serve(app, [dict(key='requested', task='roguelike.rewards', inputs={'theme': 'Sami'})],
                                out, dict(account_key='own', game_package='own.game'), sleep=sleep)
                self.assertEqual(calls[:2], ['roguelike.rewards', 'daily.collect'])
                self.assertEqual('close' in calls, collect_ok)
                self.assertNotIn('daily.full', calls)
                self.assertFalse((root / 'runtime_state/public_receiver_owner.json').exists())

    def test_activity_reward_goal_does_not_hide_pending_signin(self):
        from receiver_operations_v1 import extra
        from ark_modules.core import Result
        app = SimpleNamespace(get_active_event=lambda: {'name': 'own event'}, ACTIVE_EVENTS=[])
        session = SimpleNamespace(app=app, output=Path('unused'), sequence=1, events={},
            execute=lambda *a: Result('succeeded', 'rewards verified', ('synthetic-frame',)))
        with patch('event_signin_discovery_v6.service', return_value={'status': 'pending'}):
            result = extra(session, {}, None, {}, 'goal.activity_rewards')
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.data['signin']['status'], 'pending')

    def test_module_dependency_can_use_an_already_finished_step(self):
        row = dict(key='collect_new', task='daily.collect', requires=['earlier_reward'])
        self.assertEqual(host.steps([row], {'earlier_reward'}), [row])
        with self.assertRaises(ValueError):
            host.steps([row], {'collect_new'})

    def test_partial_init_resumes_own_exact_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path, _ = fixture(root)
            original_open = Path.open
            def interrupted(self, mode='r', *a, **kw):
                if self == root / 'BUSINESS_RULES.json' and mode == 'x':
                    raise OSError('synthetic interruption')
                return original_open(self, mode, *a, **kw)
            with patch.object(Path, 'open', interrupted), self.assertRaises(OSError):
                setup.initialise(path, root)
            self.assertTrue((root / 'PROJECT_CONTRACT.json').exists())
            self.assertFalse((root / setup.BINDING).exists())
            self.assertEqual(setup.initialise(path, root)['status'], 'initialised')
            self.assertFalse((root / 'config/receiver_init_pending.json').exists())

    def test_explicit_resource_repeat_is_not_replaced_by_99(self):
        from receiver_operations_v1 import extra
        app = SimpleNamespace(_RUN_SUMMARY={}, mode_resource=lambda **kw: kw,
                              shot=lambda *a: 'current.png')
        session = SimpleNamespace(app=app, output=Path('unused'), sequence=1)
        result = extra(session, dict(stage='1-7', times=3), None, {}, 'resource.farm')
        self.assertEqual(result.data['result']['times'], 3)
        self.assertNotEqual(result.status, 'succeeded')

    def test_tl_empty_reward_is_verified_not_new_claim(self):
        from receiver_operations_v1 import binding
        _, call = binding('activity.rewards')
        row = dict(status='verified_no_claimable', tl_visits=[dict(evidence=['a.png', 'b.png'])])
        app = SimpleNamespace(_RUN_SUMMARY={'event': {'task_rewards': row}}, claim_event_task_rewards=lambda e: True)
        session = SimpleNamespace(app=app, event=lambda i: {'stage_prefix': 'TL'})
        result = call(session, {}, None, {}, 'activity.rewards')
        self.assertEqual(result.status, 'succeeded')
        self.assertEqual(result.data.get('tl_verified_claims', 0), 0)

    def test_collection_has_no_drone_or_rotation_branch(self):
        from receiver_operations_v1 import binding
        from ark_modules.core import Result
        _, call = binding('daily.collect')
        good = Result('succeeded', 'collection', ('current.png',))
        worker = SimpleNamespace(collect=lambda *a: good, available=lambda: True,
            run=lambda: (_ for _ in ()).throw(AssertionError('broad exit-tail forbidden')))
        session = SimpleNamespace(app=object(), output=Path('unused'), sequence=1,
                                  owns_control=lambda x: True, now=lambda: None)
        with patch('ark_modules.exit_tail.ExitTail', return_value=worker), \
             patch('daily_base_notifications_v3.collect', return_value={'complete': True}):
            result = call(session, {}, None, {}, 'daily.collect')
        self.assertEqual(result.status, 'succeeded')
        self.assertFalse(result.data['drone_spent'])

    def test_no_default_game_action(self):
        with patch('builtins.print'), patch.object(setup, 'configured', side_effect=AssertionError('must not prepare')):
            self.assertEqual(ark.main([]), 0)
            self.assertEqual(ark.main(['list']), 0)
            for task in goals.BY_GOAL:
                self.assertEqual(ark.main(['describe', task]), 0)
                self.assertEqual(ark.main(['template', task]), 0)

    def test_public_menu_is_human_goals_not_mechanical_steps(self):
        self.assertNotIn('observe', goals.BY_GOAL)
        self.assertNotIn('navigation.home', goals.BY_GOAL)
        self.assertNotIn('daily.collect', goals.BY_GOAL)
        task, inputs = goals.compile_goal('roguelike', dict(theme='Sami', mode='rewards'))
        self.assertEqual(task, 'roguelike.rewards')
        self.assertEqual(inputs, {'theme': 'Sami'})
        task, inputs = goals.compile_goal('sss', {})
        self.assertEqual(task, 'periodic.sss')
        self.assertEqual(inputs, {})
        self.assertNotIn('formation_only', goals.BY_GOAL['sss'].template)
        self.assertEqual(goals.compile_goal('daily', {})[0], 'daily.full')

    def test_sss_public_goal_calls_complete_existing_service_internal_formation_stays_available(self):
        from receiver_operations_v1 import binding
        from ark_modules.core import Result
        called = []
        task, params = goals.compile_goal('sss', {})
        spec, handler = binding(task)
        app = SimpleNamespace(mode_security=lambda: called.append('complete_security_service'), _RUN_SUMMARY={})
        session = SimpleNamespace(app=app,
            proof=lambda ok, detail, data, tag: Result('succeeded' if ok else 'partial', detail, data=data))
        with patch('receiver_sss_formation_v1.prepare', side_effect=AssertionError('public goal must not stop at formation')):
            result = handler(session, params, None, {}, task)
        self.assertEqual(called, ['complete_security_service'])
        self.assertEqual(result.status, 'partial')  # dispatch alone is not game completion
        self.assertIn('sss.formation', catalogue.BY_ID)
        internal, method = binding('sss.formation')
        self.assertEqual(internal.name, 'sss.formation')
        self.assertTrue(callable(method))
        with self.assertRaises(ValueError):
            goals.compile_goal('sss', {'formation_only': True})
        self.assertEqual(goals.compile_goal('sss', {'formation_only': False}), ('periodic.sss', {}))

    def test_catalogue_entries_really_exist(self):
        for row in catalogue.TASKS:
            path, _, member = row.implementation.partition(':')
            source = ROOT / (path if path.endswith('.py') else path.replace('.', '/') + '.py')
            self.assertTrue(source.is_file(), (row.id, source))
            if member:
                names = {n.name for n in ast.walk(ast.parse(source.read_text('utf-8-sig')))
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                self.assertIn(member, names, row.id)

    def test_all_callable_tasks_have_real_binding_or_explicit_route(self):
        from receiver_operations_v1 import binding
        for row in catalogue.TASKS:
            if row.route == 'session':
                spec, method = binding(row.id)
                self.assertEqual(spec.name, row.id)
                self.assertTrue(callable(method))
            else:
                self.assertIn(row.route, ('daily', 'offline', 'tool', 'extension', 'session-tool'))

    def test_no_invented_task_or_implicit_full(self):
        for task, value in [('nonexistent', {}), ('daily.full', {'stage': '1-7'}), ('roguelike.rewards', {})]:
            with self.assertRaises(ValueError):
                catalogue.validate(task, value)
        with self.assertRaises(ValueError):
            host.steps([dict(key='one', task='daily.full')])
        with self.assertRaises(ValueError):
            host.steps([dict(key='../bad', task='observe')])
        with self.assertRaises(ValueError):
            host.steps([dict(key='one', task='observe', requires=['not-before'])])

    def test_binding_generated_without_author_history_or_fake_live_record(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path, data = fixture(root)
            result = setup.initialise(path, root)
            self.assertFalse(result['live_verified'])
            self.assertEqual(result['game_actions'], 0)
            self.assertFalse((root / '.project-reasoning/COMPONENTS.json').exists())
            handoff = setup.read(root / setup.HANDOFF)
            self.assertEqual(handoff['daily_runtime']['entrypoint'], setup.ENTRY)
            self.assertNotIn('current_validation', handoff)
            self.assertEqual(setup.initialise(path, root)['status'], 'already_initialised')
            self.assertEqual(setup.configured(path, root)[0], data)

    def test_existing_or_modified_files_never_overwritten(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path, _ = fixture(root)
            save(root / 'PROJECT_CONTRACT.json', {'user': 'original'})
            with self.assertRaises(ValueError):
                setup.initialise(path, root)
            self.assertEqual(setup.read(root / 'PROJECT_CONTRACT.json'), {'user': 'original'})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path, _ = fixture(root)
            setup.initialise(path, root)
            save(root / 'BUSINESS_RULES.json', {'user': 'edited'})
            with self.assertRaises(ValueError):
                setup.configured(path, root)

    def test_source_account_package_and_resource_conflicts_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path, data = fixture(root)
            setup.initialise(path, root)
            (root / 'run_daily_v167.py').write_text('# changed', encoding='utf-8')
            with self.assertRaises(ValueError):
                setup.configured(path, root)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path, data = fixture(root)
            data['game_package'] = 'com.hypergryph.arknights.bilibili'
            save(path, data)
            with self.assertRaises(ValueError):
                setup.initialise(path, root)
            data['resources']['medicine'] = 1
            save(path, data)
            with self.assertRaises(ValueError):
                setup.initialise(path, root)

    def test_contract_passes_actual_legacy_validator(self):
        tree = ast.parse((ROOT / 'arknights_daily_runtime_v12.py').read_text('utf-8-sig'))
        definition = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'validate_project_contract')
        namespace = {}
        exec(compile(ast.Module(body=[definition], type_ignores=[]), '<actual-validator>', 'exec'), namespace)
        ok, errors = namespace['validate_project_contract'](setup.contract({'account_key': 'fixture'}))
        self.assertTrue(ok, errors)

    def test_progress_only_cannot_start_exploration(self):
        from receiver_operations_v1 import Session
        from ark_modules.orchestration import Context
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        context = Context('fixture', 'fixture', 'fixture', now.isoformat(),
                          (now + timedelta(minutes=1)).isoformat(), 'fixture')
        app = SimpleNamespace(_maa_task_queue_running=lambda: False,
                              shot=lambda *a: 'current.png', ocr=lambda p: [], tap=lambda *p: None,
                              swipe=lambda *a: None)
        row = dict(ok=True, status='verified_no_claimable', home_confirmed_after=True,
                   pages=[dict(screenshot='current.png')])
        with TemporaryDirectory() as directory, patch('permanent_progress_modules_v1.run', return_value=row) as operation:
            session = Session(app, directory, owns_control=lambda _: True)
            result = session.execute('roguelike.rewards', {'theme': 'Sami'}, context)
            self.assertEqual(result.status, 'succeeded')
            self.assertEqual(operation.call_args.args[1:3], ('Sami', 'rewards'))

    def test_formation_only_calls_no_battle_or_daily(self):
        from receiver_operations_v1 import extra
        from ark_modules.core import Result
        app = SimpleNamespace(SSS_FORMATION_PROFILES={}, _configure_sss_formation=lambda region, job: True,
            _validate_sss_formation_profile=lambda *a: (True, 'fixture'), _maa_task_queue_running=lambda: False,
            shot=lambda *a: 'current.png', ocr=lambda _: [('首批作战小队选任', 900, 200)])
        session = SimpleNamespace(app=app, output=Path('unused'), sequence=1,
            proof=lambda ok, detail, data, tag: Result('succeeded', detail, ('fixture.png',), data))
        with TemporaryDirectory() as directory:
            job = Path(directory) / 'job.json'
            save(job, {'stage_name': 'fixture'})
            result = extra(session, dict(region='fixture', job=str(job), profile={}), None, {}, 'sss.formation')
        self.assertEqual(result.status, 'succeeded')
        self.assertFalse(result.data['battle_invoked'])
        self.assertEqual(app.SSS_FORMATION_PROFILES, {})

    def test_sss_formation_goal_navigates_home_to_formation_without_battle(self):
        from receiver_sss_formation_v1 import prepare
        state, calls = ['home'], []
        def enter(): state[0] = 'list'; calls.append('goto_sss_page'); return True
        def select(region): state[0] = 'detail'; calls.append('select_' + region); return True
        def tap(*a): state[0] = 'formation'; calls.append('enter_preparation')
        def bridge(*a): calls.append('existing_maa_formation'); return True
        words = {'home': '终端', 'list': '保全平台列表', 'detail': '开始保全作战', 'formation': '首批作战小队选任'}
        app = SimpleNamespace(_validate_sss_formation_profile=lambda *a: (True, 'fixture'),
            _maa_task_queue_running=lambda: False, shot=lambda *a: state[0],
            ocr=lambda path: [(words[path], 900, 200)], goto_sss_page=enter, select_sss_region=select,
            _sss_region_entry_confirmed=lambda text: text == '开始保全作战',
            _sss_main_page_visible=lambda text: text == '保全平台列表',
            find_text=lambda items, word, **kw: (900, 200) if any(r[0] == word for r in items) else None,
            tap=tap, wait=lambda *a: None, _configure_sss_formation=bridge)
        row = prepare(app, 'user-region', {})
        self.assertTrue(row['formation_confirmed'])
        self.assertEqual(calls, ['goto_sss_page', 'select_user-region', 'enter_preparation', 'existing_maa_formation'])
        self.assertFalse(row['battle_invoked'])
        self.assertEqual(len(row['pages']), 4)

    def test_sss_formation_never_deploys_or_ends_existing_commission(self):
        from receiver_sss_formation_v1 import prepare
        for text in ('开始部署', '暂停任务 结束委托'):
            app = SimpleNamespace(_validate_sss_formation_profile=lambda *a: (True, 'fixture'),
                _maa_task_queue_running=lambda: False, shot=lambda *a: 'current.png',
                ocr=lambda _: [(text, 900, 200)])
            row = prepare(app, 'user-region', {})
            self.assertFalse(row['formation_confirmed'])
            self.assertFalse(row['actions'])
            self.assertFalse(row['battle_invoked'])

    def test_sss_navigation_cannot_end_commission_discovered_after_leaving_home(self):
        from receiver_sss_formation_v1 import prepare
        state, ended = ['home'], []
        app = SimpleNamespace(_validate_sss_formation_profile=lambda *a: (True, 'fixture'),
            _maa_task_queue_running=lambda: False, shot=lambda *a: state[0],
            ocr=lambda path: [('终端' if path == 'home' else '结束委托', 900, 200)],
            _sss_region_entry_confirmed=lambda _: False, _sss_main_page_visible=lambda _: False,
            _leave_sss_intermediate=lambda *a: ended.append(True))
        def original_navigation():
            state[0] = 'existing_commission'
            return app._leave_sss_intermediate('existing_commission', 'sss_entry_leave')
        app.goto_sss_page = original_navigation
        row = prepare(app, 'user-region', {})
        self.assertEqual(row['reason'], 'existing_commission_preserved_no_abort')
        self.assertFalse(ended)
        self.assertFalse(row['formation_confirmed'])


if __name__ == '__main__':
    unittest.main()
