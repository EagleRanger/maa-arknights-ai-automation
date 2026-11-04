"""Initial MAA startup may update; active daily work defers OTA until next day."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import json
import time
from ark_host.cooperation_v1 import atomic_json, read_message


def game_day():
    return (datetime.now().astimezone() - timedelta(hours=4)).date().isoformat()


def update_dialog(ua, app, accept):
    from maa_window_handle_v2 import inventory
    for row in inventory(app.MAA_PATH):
        if not row['visible'] or not row['enabled'] or '更新' not in row['title']:
            continue
        root = ua.ControlFromHandle(row['hwnd'])
        nodes = [root] + app._uia_descendants(root, max_depth=8)
        text = ''.join(str(getattr(n, 'Name', '')) for n in nodes)
        if '是否立即更新' not in text or 'MAA' not in text:
            continue
        names = {'确认', '是', '确定', 'OK', 'Yes'} if accept else {'稍后', '否', '取消', 'No', 'Later'}
        buttons = [n for n in nodes if getattr(n, 'ControlTypeName', '') == 'ButtonControl'
                   and str(getattr(n, 'Name', '')).strip() in names
                   and getattr(n, 'IsEnabled', False) and not getattr(n, 'IsOffscreen', True)]
        if len(buttons) == 1:
            buttons[0].GetInvokePattern().Invoke()
            return True
    return False


@contextmanager
def boundary(app):
    original_launch, original_wait = app._launch_maa_for_background_control, app.wait
    deferred = Path(app.OUTPUT_DIR) / 'maa_update_policy' / 'deferred.json'
    saved_at_entry = read_message(deferred)
    state = dict(phase='daily_active' if saved_at_entry.get('game_day') == game_day()
                 else 'initial_startup', deferred=False)
    last_poll = [0.0]

    def config():
        p = Path(app.MAA_CONFIG) / 'gui.new.json'
        return p, json.loads(p.read_text('utf-8-sig'))

    def launch():
        app._RUN_SUMMARY['maa_update_policy'] = state
        p, cfg = config()
        upd = cfg.setdefault('Update', {})
        saved = read_message(deferred)
        if state['phase'] == 'initial_startup':
            for key, value in (saved.get('settings') or {}).items():
                upd[key] = value
            if saved.get('package') and saved.get('game_day') != game_day():
                package = Path(app.MAA_ROOT) / saved['package']
                if package.is_file():
                    upd['UpdatePackage'] = saved['package']
                    atomic_json(deferred, dict(saved, restored_for_startup=True))
            app._atomic_write_json(str(p), cfg)
        else:
            saved.setdefault('settings', {k: upd.get(k) for k in (
                'AutoInstallUpdatePackage', 'AutoDownloadUpdatePackage', 'CheckOnStartup', 'DoNotShowUpdate')})
            saved.update(game_day=game_day(), reason='finish_daily_before_maa_update')
            if upd.get('UpdatePackage'):
                saved.update(package=upd['UpdatePackage'], target=upd.get('Name'))
                upd['UpdatePackage'] = ''
            atomic_json(deferred, saved)
            upd['AutoInstallUpdatePackage'] = False
            # Do not download a new OTA into a process that will be reloaded
            # between Depot/Fight and the final daily queue.
            upd['AutoDownloadUpdatePackage'] = False
            upd['CheckOnStartup'] = False
            upd['DoNotShowUpdate'] = True
            app._atomic_write_json(str(p), cfg)
        return original_launch()

    def settle_initial():
        app._RUN_SUMMARY['maa_update_policy'] = state
        if state['phase'] != 'initial_startup':
            return
        import uiautomation as ua
        # Only an actual startup prompt is accepted; no unrelated confirmation.
        for attempt in range(3):
            if update_dialog(ua, app, True):
                state['accepted_at_initial_startup'] = True
                original_wait(3)
                break
            if attempt < 2:
                original_wait(1)
        state['phase'] = 'daily_active'
        state['next_update_window'] = 'next_daily_startup'
        # Persist the daily phase even when the first GUI process stays alive.
        p, cfg = config()
        saved = read_message(deferred)
        saved.setdefault('settings', {k: cfg.get('Update', {}).get(k) for k in (
            'AutoInstallUpdatePackage', 'AutoDownloadUpdatePackage', 'CheckOnStartup', 'DoNotShowUpdate')})
        saved['game_day'] = game_day()
        atomic_json(deferred, saved)

    def wait(seconds):
        result = original_wait(seconds)
        if state['phase'] == 'daily_active' and time.monotonic() - last_poll[0] >= 5:
            last_poll[0] = time.monotonic()
            import uiautomation as ua
            if update_dialog(ua, app, False):
                state['deferred'] = True
                app.log('[MAA更新] 日常进行中已选稍后；剩余流程继续，下次日常启动再更新')
        return result

    with patch.object(app, '_launch_maa_for_background_control', launch), \
         patch.object(app, 'wait', wait), \
         patch.object(app, '_maa_daily_settle_initial_update', settle_initial, create=True):
        yield
