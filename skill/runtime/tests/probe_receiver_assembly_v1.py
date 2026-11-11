"""Run the real public V167 assembly down to the selected consumer.

No external processes, sockets, GUI or device I/O are allowed. A test fixture
is local receiver input, not author handoff or a mocked version selector.
"""
from pathlib import Path
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def audit(event, args):
    if event in ('subprocess.Popen', 'os.system', 'socket.connect', 'socket.bind'):
        raise AssertionError('External I/O forbidden in receiver assembly probe: ' + event)


def main(daily=False):
    import receiver_setup_v1 as setup
    from tools.build_receiver_manifest_v1 import build
    old_profile = ROOT / 'config/receiver_profile.json'
    if old_profile.exists():
        old = setup.read(old_profile)
        if old.get('account_key') != 'synthetic-receiver-not-game-fact':
            raise ValueError('not an isolated synthetic receiver; no cleanup or overwrite')
        binding = setup.read(ROOT / setup.BINDING)
        for name, digest in binding['managed_files'].items():
            if setup.sha(setup.local(ROOT, name)) != digest:
                raise ValueError('fixture modified; preserve before retry')
        # Exact generated fixture files only; never a recursive cleanup.
        for name in (*binding['managed_files'], setup.BINDING, setup.PROFILE,
                     'config/game_runtime_target_v1.json', 'config/receiver_fixture_base.json'):
            setup.local(ROOT, name).unlink()
    build()
    # The isolated candidate is the fixture workspace. No source-project
    # configuration is read and no file is added to a public allowlist.
    profile = ROOT / 'config/receiver_profile.json'
    target = ROOT / 'config/game_runtime_target_v1.json'
    base = ROOT / 'config/receiver_fixture_base.json'
    for path in (profile, target, base):
        if path.exists():
            raise ValueError('probe requires a fresh isolated extract; do not overwrite local configs')
    target.write_text(json.dumps(dict(package='com.hypergryph.arknights', created_timestamp='11111', android_version='15.0')), encoding='utf-8')
    base.write_bytes((ROOT / 'config/base_orundum_333_dynamic_v1.example.json').read_bytes())
    data = dict(schema_version=1, account_key='synthetic-receiver-not-game-fact',
        game_package='com.hypergryph.arknights', mumu_root=str(ROOT / 'outputs/fixture-mumu'),
        python=sys.executable, resources=dict(originium=0, medicine=0), base_plan=str(base.relative_to(ROOT)))
    profile.write_text(json.dumps(data), encoding='utf-8')
    setup.initialise(profile)
    checked = setup.configured(profile)[2]
    if daily:
        # Explicit fake MAA installation data, not an installed/user tree.
        # Keep real resource loaders and route wrappers in the exercised path.
        import event_tl_route_v1 as tl
        import maa_series_resource_v1 as series
        installed = ROOT / '.runtime_maa/MAA-App'
        tasks = installed / 'resource/tasks/tasks.json'
        tasks.parent.mkdir(parents=True, exist_ok=True)
        tasks.write_text(json.dumps({'FightSeries-Icon': series.LEGACY_ICON,
            'FightSeries-List-Multiply': series.LEGACY_LIST}), encoding='utf-8')
        gui = installed / 'config/gui.new.json'
        gui.parent.mkdir(parents=True, exist_ok=True)
        gui.write_text(json.dumps({'UseGpu': False, 'Gui': {'GuideStep': 7, 'GuideTutorialVersion': 2},
            'Configurations': {'Default': {'TaskQueue': [{'TaskType': 'Recruit', 'IsEnable': True}]}}}), encoding='utf-8')
        tile = installed / 'resource/Arknights-Tile-Pos'
        tile.mkdir(parents=True, exist_ok=True)
        overview = {}
        for key, row, raw in tl.maps():
            overview[key] = row
            path = tile / row['filename']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (tile / 'overview.json').write_text(json.dumps(overview), encoding='utf-8')
        (installed / 'resource/item_index.json').write_text('{}', encoding='utf-8')
        for name in ('MAA.exe', 'MAA.dll', 'MaaCore.dll'):
            (installed / name).touch()
        (installed / 'resource/tasks/UiTheme').mkdir(parents=True, exist_ok=True)
    sys.addaudithook(audit)
    sys.modules.setdefault('uiautomation', SimpleNamespace(__file__='synthetic-ui-no-actions'))
    hit = []
    with setup.environment(data):
        import local_ocr_v6_small_v2 as ocr
        def selected_consumer(app):
            assert Path(app.BASE).resolve() == ROOT
            assert Path(app.SCRIPT_DIR).resolve() == ROOT
            assert app._DAILY_EXISTING_SANITY_ONLY is True
            assert app._consume_confirmed_red_expiring_potion() is False
            assert app.validate_project_contract()[0] is True
            hit.append(app)
            return 71
        # OCR inference is external I/O. Keep the actual common service router
        # and module consumer; replace only its model process.
        worker = SimpleNamespace(close=lambda: None,
            request=lambda *a, **k: (_ for _ in ()).throw(AssertionError('No inference in wiring probe')))
        with patch.object(ocr, 'Worker', return_value=worker):
            if daily:
                import run_daily
                import arknights_daily_runtime_v12 as app
                import dp_event_route_v26 as obsolete_download
                import dp_resource_integrity_v36 as obsolete_integrity
                # Stop at the real final daily consumer, before external/game
                # actions. The selector/bootstrap/wrappers remain unmocked.
                with ExitStack() as stack:
                    stack.enter_context(patch.object(obsolete_download, 'ensure_dp_resources',
                        return_value={'status': 'synthetic_obsolete_resource_fixture'}))
                    stack.enter_context(patch.object(obsolete_integrity, 'ensure_dp_resources',
                        return_value={'status': 'synthetic_obsolete_resource_fixture'}))
                    stack.enter_context(patch.object(run_daily, 'main', lambda: selected_consumer(app)))
                    with setup.assembled(data, checked) as execute:
                        assert execute() == 71
            else:
                with setup.assembled(data, checked, selected_consumer, operations=('observe',)) as execute:
                    assert execute() == 71
    assert len(hit) == 1, 'real public selector did not reach the exact consumer once'
    print('PASS actual public config -> ' + ('V167 daily wrapper graph -> final daily consumer' if daily else
        'existing shared host services -> exact module consumer; no unrelated maps/full') + '; game actions 0')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--daily', action='store_true')
    main(parser.parse_args().daily)
