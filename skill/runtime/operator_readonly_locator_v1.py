"""Use native OperProgress's name/role-only plan to open a character page.

Verified v6.21.1 parser accepts an absent development target; its process still
locates the operator but skips elite/skill/mastery actions. No inferred goals.
"""
import ctypes
import json
import os
from pathlib import Path
import threading
import time


def params(name,role):
    if not isinstance(name,str) or not name.strip() or role not in {
        'Warrior','Pioneer','Medic','Tank','Sniper','Caster','Support','Special'}:
        raise ValueError('explicit known operator and role required')
    return {'plans':[{'name':name,'role':role}]}


def run(app,name,role,output,timeout=180):
    payload=params(name,role)
    if app._maa_task_queue_running() is not False:raise ValueError('MAA owns device')
    app._close_maacore_screenshot_bridge();app._stop_idle_maa_for_update()
    root=app._maa_install_root();out=Path(output);out.mkdir(parents=True,exist_ok=True)
    if (out/'callbacks.json').exists():raise ValueError('existing locator evidence preserved')
    events=[];done=threading.Event();complete=threading.Event();error=threading.Event()
    core=None;handle=None;cookie=None;summary=None
    try:
        cookie=os.add_dll_directory(root);core=ctypes.WinDLL(str(Path(root)/'MaaCore.dll'))
        cbtype=ctypes.WINFUNCTYPE(None,ctypes.c_int32,ctypes.c_char_p,ctypes.c_void_p)
        signatures={
            'AsstSetUserDir':([ctypes.c_char_p],ctypes.c_uint8),'AsstLoadResource':([ctypes.c_char_p],ctypes.c_uint8),
            'AsstCreateEx':([cbtype,ctypes.c_void_p],ctypes.c_void_p),'AsstDestroy':([ctypes.c_void_p],None),
            'AsstSetConnectionExtras':([ctypes.c_char_p,ctypes.c_char_p],None),
            'AsstConnect':([ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char_p,ctypes.c_char_p],ctypes.c_uint8),
            'AsstAppendTask':([ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char_p],ctypes.c_int32),
            'AsstStart':([ctypes.c_void_p],ctypes.c_uint8),'AsstStop':([ctypes.c_void_p],ctypes.c_uint8),
            'AsstRunning':([ctypes.c_void_p],ctypes.c_uint8)}
        for name_,(arguments,result) in signatures.items():
            call=getattr(core,name_);call.argtypes=arguments;call.restype=result
        def callback(msg,raw,_):
            nonlocal summary
            try:row=json.loads(raw.decode('utf-8')) if raw else {}
            except (ValueError,UnicodeError):row={}
            events.append(dict(msg=int(msg),details=row))
            if msg==3:done.set()
            if row.get('taskchain')=='OperProgress':
                if msg==10002:complete.set()
                if msg in (10000,10004):error.set()
                if msg==20003 and row.get('what')=='OperProgressSummary':summary=row.get('details')
        cb=cbtype(callback);user=out/'user';user.mkdir()
        if not core.AsstSetUserDir(os.fsencode(user)) or not core.AsstLoadResource(os.fsencode(root)):
            raise RuntimeError('locator resources unavailable')
        handle=core.AsstCreateEx(cb,None)
        if not handle:raise RuntimeError('locator handle unavailable')
        core.AsstSetConnectionExtras(b'MuMuEmulator12',app._maa_mumu_core_extras().encode('utf-8'))
        if not core.AsstConnect(handle,os.fsencode(app.ADB),app.DEVICE.encode('utf-8'),b'MuMuEmulator12'):
            raise RuntimeError('locator connection failed')
        task=core.AsstAppendTask(handle,b'OperProgress',json.dumps(payload,ensure_ascii=False).encode('utf-8'))
        if task<=0 or not core.AsstStart(handle):raise RuntimeError('locator submission failed')
        deadline=time.monotonic()+timeout
        while core.AsstRunning(handle) and not done.is_set() and time.monotonic()<deadline:time.sleep(.2)
        ok=done.is_set() and complete.is_set() and not error.is_set() and summary is not None and summary.get('failed')==0
        return dict(status='operator_page_located' if ok else 'locator_unverified',name=name,role=role,
                    development_actions_requested=False,summary=summary,evidence=str(out/'callbacks.json'))
    finally:
        if handle:
            if core.AsstRunning(handle):
                core.AsstStop(handle);deadline=time.monotonic()+15
                while core.AsstRunning(handle) and time.monotonic()<deadline:time.sleep(.1)
            if core.AsstRunning(handle):raise RuntimeError('locator stop unverified')
            core.AsstDestroy(handle)
        (out/'callbacks.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
        if cookie:cookie.close()
