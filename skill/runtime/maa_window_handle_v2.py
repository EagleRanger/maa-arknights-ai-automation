"""Filter native MAA windows before invoking a UIA provider; never desktop-scan."""
from pathlib import Path


def choose(rows):
    usable=[r for r in rows if r['visible'] and r['enabled'] and not r['owner']
            and r['title'].startswith('MAA') and r['width']>=500 and r['height']>=300]
    if not usable:return None
    usable.sort(key=lambda r:r['width']*r['height'],reverse=True)
    if len(usable)>1 and usable[0]['pid']!=usable[1]['pid']:
        raise RuntimeError('multiple portable MAA owners')
    return usable[0]


def inventory(executable):
    import ctypes
    from ctypes import wintypes as w
    import psutil
    target=Path(executable).resolve()
    pids=set()
    for proc in psutil.process_iter(['pid','name','exe']):
        try:
            if proc.info['name'].lower()=='maa.exe' and Path(proc.info['exe']).resolve()==target:
                pids.add(proc.pid)
        except (OSError,psutil.Error,TypeError):pass
    u=ctypes.windll.user32
    u.GetWindow.restype=w.HWND
    u.GetWindow.argtypes=[w.HWND,w.UINT]
    u.IsWindowVisible.argtypes=[w.HWND];u.IsWindowEnabled.argtypes=[w.HWND]
    u.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    u.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
    u.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
    rows=[]
    callback=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    @callback
    def collect(hwnd,_):
        pid=w.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value not in pids:return True
        name=ctypes.create_unicode_buffer(512);cls=ctypes.create_unicode_buffer(256);rect=w.RECT()
        u.GetWindowTextW(hwnd,name,512);u.GetClassNameW(hwnd,cls,256);u.GetWindowRect(hwnd,ctypes.byref(rect))
        rows.append(dict(hwnd=int(hwnd),pid=pid.value,title=name.value,class_name=cls.value,
                         visible=bool(u.IsWindowVisible(hwnd)),enabled=bool(u.IsWindowEnabled(hwnd)),
                         owner=int(u.GetWindow(hwnd,4) or 0),width=rect.right-rect.left,height=rect.bottom-rect.top))
        return True
    u.EnumWindows(collect,0)
    return rows


def find(ua,executable,trace=lambda **kw:None):
    rows=inventory(executable);row=choose(rows)
    trace(phase='native_window_inventory',windows=rows,selected=row)
    if row is None:return None
    # Bind only the selected main HWND, not hidden HwndWrapper/IME providers.
    trace(phase='uia_bind_selected_main',selected=row)
    control=ua.ControlFromHandle(row['hwnd'])
    trace(phase='uia_validate_owner',selected=row)
    if int(control.ProcessId)!=row['pid']:raise RuntimeError('MAA window owner changed')
    trace(phase='uia_window_ready',selected=row)
    return control
