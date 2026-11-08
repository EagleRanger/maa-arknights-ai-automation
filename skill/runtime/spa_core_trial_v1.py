"""One official SPA farming cycle; the caller retains game/AI ownership."""
import ctypes
import json
import os
from pathlib import Path
import threading
import time
from ark_host.cooperation_v1 import atomic_json
from maa_spa_resources_v1 import verify


ENTRIES = ('Begin', 'Goliath', 'CustomOpersConfirm', 'LoopWaitStart')


def is_lobby_event(msg, details):
    # Real Core callbacks strip the resource namespace; accept both forms.
    task = (details.get('details') or {}).get('task', '')
    return msg == 20002 and task in ('ReturnHome', 'MiniGame@SPA@ReturnHome')


def run(app, output, resource_output, deadline, *, entry_task='Begin'):
    if entry_task not in ENTRIES:
        raise ValueError('unsupported SPA resume entry')
    if app._maa_task_queue_running() is not False:
        raise ValueError('device owned by MAA queue')
    record = verify(resource_output)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    (output / 'submitted.claim').open('x').close()
    app._close_maacore_screenshot_bridge()
    app._stop_idle_maa_for_update()
    root = app._maa_install_root()
    handle = None; events = []; completed = threading.Event(); failed = threading.Event()
    saw_lobby = threading.Event()
    with os.add_dll_directory(str(root)):
        core = ctypes.WinDLL(str(Path(root) / 'MaaCore.dll'))
        cbtype = ctypes.WINFUNCTYPE(None, ctypes.c_int32, ctypes.c_char_p, ctypes.c_void_p)
        signatures = {
            'AsstSetUserDir': ([ctypes.c_char_p], ctypes.c_uint8),
            'AsstLoadResource': ([ctypes.c_char_p], ctypes.c_uint8),
            'AsstCreateEx': ([cbtype, ctypes.c_void_p], ctypes.c_void_p),
            'AsstDestroy': ([ctypes.c_void_p], None),
            'AsstSetConnectionExtras': ([ctypes.c_char_p, ctypes.c_char_p], None),
            'AsstConnect': ([ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p], ctypes.c_uint8),
            'AsstAppendTask': ([ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int32),
            'AsstStart': ([ctypes.c_void_p], ctypes.c_uint8),
            'AsstStop': ([ctypes.c_void_p], ctypes.c_uint8),
            'AsstRunning': ([ctypes.c_void_p], ctypes.c_uint8)}
        for name, (args, result) in signatures.items():
            getattr(core, name).argtypes = args; getattr(core, name).restype = result
        stream = (output / 'callbacks.jsonl').open('a', encoding='utf-8')
        def callback(msg, raw, _):
            try:
                details = json.loads(raw.decode('utf-8')) if raw else {}
                event = dict(msg=msg, details=details, at=time.time())
                events.append(event); stream.write(json.dumps(event, ensure_ascii=False)+'\n'); stream.flush()
                if is_lobby_event(msg, details):
                    saw_lobby.set()
                if details.get('taskchain') == 'Custom':
                    if msg == 10002: completed.set()
                    if msg in (10000, 10004) and not completed.is_set(): failed.set()
            except Exception:
                failed.set()
        cb = cbtype(callback)
        try:
            user = output / 'user'; user.mkdir()
            if not (core.AsstSetUserDir(os.fsencode(user)) and core.AsstLoadResource(os.fsencode(root))
                    and core.AsstLoadResource(os.fsencode(record['overlay']))):
                raise RuntimeError('SPA resource load failed')
            handle = core.AsstCreateEx(cb, None)
            if not handle: raise RuntimeError('SPA controller creation failed')
            app._spa_core_owned = True
            core.AsstSetConnectionExtras(b'MuMuEmulator12', app._maa_mumu_core_extras().encode())
            if not core.AsstConnect(handle, os.fsencode(app.ADB), app.DEVICE.encode(), b'MuMuEmulator12'):
                raise RuntimeError('SPA device connection failed')
            payload = dict(task_names=['MiniGame@SPA@'+entry_task])
            atomic_json(output / 'parameters.json', payload)
            if core.AsstAppendTask(handle, b'Custom', json.dumps(payload).encode()) <= 0 or not core.AsstStart(handle):
                raise RuntimeError('SPA task not started')
            while core.AsstRunning(handle) and not completed.is_set() and not failed.is_set() and time.time()<deadline:
                time.sleep(.25)
            result = dict(status='native_cycle_returned' if completed.is_set() and saw_lobby.is_set() and not failed.is_set()
                          else 'needs_ai', native_completed=completed.is_set(), lobby_action=saw_lobby.is_set(),
                          error=failed.is_set(), timed_out=time.time()>=deadline, game_reward_verified=False,
                          callbacks=str(output/'callbacks.jsonl'), environment_cleanup=False)
            atomic_json(output / 'result.json', result)
            return result
        finally:
            if handle:
                if core.AsstRunning(handle): core.AsstStop(handle)
                until=time.monotonic()+15
                while core.AsstRunning(handle) and time.monotonic()<until: time.sleep(.1)
                if core.AsstRunning(handle): raise RuntimeError('SPA controller still running; preserve owner')
                core.AsstDestroy(handle)
                app._spa_core_owned = False
            stream.close()
