"""Read-only Windows lifetime facts; no process termination or scheduling."""
import ctypes
import os
import struct


def current_job_flags():
    if os.name!='nt':return None
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)]
    member=wintypes.BOOL()
    if not kernel.IsProcessInJob(kernel.GetCurrentProcess(),None,ctypes.byref(member)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not member.value:return dict(in_job=False,limit_flags=0,kill_on_close=False)
    kernel.QueryInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,
        wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    # Extended information's first two LARGE_INTEGERs precede LimitFlags.
    buffer=ctypes.create_string_buffer(144 if ctypes.sizeof(ctypes.c_void_p)==8 else 108)
    used=wintypes.DWORD()
    if not kernel.QueryInformationJobObject(None,9,buffer,len(buffer),ctypes.byref(used)):
        raise ctypes.WinError(ctypes.get_last_error())
    flags=struct.unpack_from('<I',buffer.raw,16)[0]
    return dict(in_job=True,limit_flags=flags,kill_on_close=bool(flags&0x2000))
