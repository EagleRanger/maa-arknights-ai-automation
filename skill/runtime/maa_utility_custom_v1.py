"""One serial native Custom task for specifically admitted utility flows.

Uses the same official MaaCore ABI/connection as the existing roguelike
adapter. No navigation replacement, environment boot, daily or combat.
"""
import ctypes
import json
import os
from pathlib import Path
import threading
import time

TASKS={'committee':'MiniGame@WartimePressCommittee@Begin',
       'green':'GreenTicket@Store@Begin','yellow':'YellowTicket@Store@Begin'}


def run(app,kind,output,*,timeout=180):
    if kind not in TASKS:raise ValueError('unsupported utility')
    if app._maa_task_queue_running() is not False:raise ValueError('MAA queue owns device')
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    if (out/'callbacks.json').exists():raise ValueError('existing native run preserved')
    app._close_maacore_screenshot_bridge()
    app._stop_idle_maa_for_update()
    root=app._maa_install_root()
    events=[];done=threading.Event();complete=threading.Event();error=threading.Event()
    core=None;handle=None;cookie=None;timed_out=False
    try:
        cookie=os.add_dll_directory(root)
        core=ctypes.WinDLL(str(Path(root)/'MaaCore.dll'))
        callback_type=ctypes.WINFUNCTYPE(None,ctypes.c_int32,ctypes.c_char_p,ctypes.c_void_p)
        signatures={
            'AsstSetUserDir':([ctypes.c_char_p],ctypes.c_uint8),
            'AsstLoadResource':([ctypes.c_char_p],ctypes.c_uint8),
            'AsstCreateEx':([callback_type,ctypes.c_void_p],ctypes.c_void_p),
            'AsstDestroy':([ctypes.c_void_p],None),
            'AsstSetConnectionExtras':([ctypes.c_char_p,ctypes.c_char_p],None),
            'AsstConnect':([ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char_p,ctypes.c_char_p],ctypes.c_uint8),
            'AsstAppendTask':([ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char_p],ctypes.c_int32),
            'AsstStart':([ctypes.c_void_p],ctypes.c_uint8),
            'AsstStop':([ctypes.c_void_p],ctypes.c_uint8),
            'AsstRunning':([ctypes.c_void_p],ctypes.c_uint8)}
        for name,(args,result) in signatures.items():
            call=getattr(core,name);call.argtypes=args;call.restype=result
        def callback(msg,raw,_):
            try:detail=json.loads(raw.decode('utf-8')) if raw else {}
            except (ValueError,UnicodeError):detail={}
            events.append(dict(msg=int(msg),details=detail,at=time.time()))
            if msg==3:done.set()
            if detail.get('taskchain')=='Custom':
                if msg==10002:complete.set()
                if msg in (10000,10004):error.set()
        cb=callback_type(callback)
        user=out/'user';user.mkdir()
        if not core.AsstSetUserDir(os.fsencode(user)) or not core.AsstLoadResource(os.fsencode(root)):
            raise RuntimeError('native utility resources unavailable')
        handle=core.AsstCreateEx(cb,None)
        if not handle:raise RuntimeError('native utility controller unavailable')
        core.AsstSetConnectionExtras(b'MuMuEmulator12',app._maa_mumu_core_extras().encode('utf-8'))
        if not core.AsstConnect(handle,os.fsencode(app.ADB),app.DEVICE.encode('utf-8'),b'MuMuEmulator12'):
            raise RuntimeError('native utility connection failed')
        payload=json.dumps(dict(task_names=[TASKS[kind]])).encode('utf-8')
        task=core.AsstAppendTask(handle,b'Custom',payload)
        if task<=0 or not core.AsstStart(handle):raise RuntimeError('native utility start failed')
        deadline=time.monotonic()+min(300,max(30,timeout))
        while not done.is_set() and time.monotonic()<deadline and core.AsstRunning(handle):time.sleep(.2)
        timed_out=not done.is_set() and bool(core.AsstRunning(handle))
        return dict(status='native_completed_effect_pending' if done.is_set() and complete.is_set() and not error.is_set()
                    else 'native_unverified',taskid=task,kind=kind,timed_out=timed_out,
                    callbacks=str(out/'callbacks.json'),game_effect_verified=False)
    finally:
        if handle:
            if core.AsstRunning(handle):
                core.AsstStop(handle)
                deadline=time.monotonic()+15
                while core.AsstRunning(handle) and time.monotonic()<deadline:time.sleep(.1)
            if core.AsstRunning(handle):raise RuntimeError('native utility stop unverified; preserve controller')
            core.AsstDestroy(handle)
        (out/'callbacks.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
        if cookie:cookie.close()
