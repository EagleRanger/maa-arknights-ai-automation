"""独立显示自动化结果弹窗；读取UTF-8 JSON，失败时留下可审计错误。"""

import ctypes
import json
import os
import sys
import traceback


def configure_dpi_awareness(winapi=None):
    """Render native dialog text at monitor DPI, not bitmap-scaled 96 DPI.

    This helper runs in the independent popup process, before any window exists.
    A thread override also handles hosts whose process awareness is already set.
    Older Windows APIs are fallbacks only; unavailable APIs never lose a report.
    """
    if winapi is None:
        winapi = getattr(ctypes, "windll", None)
    if winapi is None:
        return "unavailable"
    calls = (
        ("user32", "SetProcessDpiAwarenessContext", ctypes.c_void_p,
         ctypes.c_int, -4, "per_monitor_v2_process"),
        ("user32", "SetThreadDpiAwarenessContext", ctypes.c_void_p,
         ctypes.c_void_p, -4, "per_monitor_v2_thread"),
        ("shcore", "SetProcessDpiAwareness", ctypes.c_int,
         ctypes.c_long, 2, "per_monitor_v1_process"),
        ("user32", "SetProcessDPIAware", None,
         ctypes.c_int, None, "system_aware"),
    )
    for library, name, argtype, restype, value, mode in calls:
        try:
            function = getattr(getattr(winapi, library), name)
            function.argtypes = [] if argtype is None else [argtype]
            function.restype = restype
            result = function() if argtype is None else function(value)
            success = result == 0 if name == "SetProcessDpiAwareness" else bool(result)
            if success:
                return mode
        except (AttributeError, OSError):
            continue
    return "unavailable"


def main():
    payload_path = os.path.abspath(sys.argv[1])
    error_path = os.path.splitext(payload_path)[0] + ".error.log"
    try:
        with open(payload_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        title = str(payload.get("title") or "明日方舟自动化结果")
        message = str(payload.get("message") or "没有可显示的结果。")
        configure_dpi_awareness()
        # 2026-09-20: remove MB_TOPMOST(0x40000). The result dialog must stop
        # floating above everything and jumping when focus changes.
        flags = 0x00010000 | 0x00000040
        ctypes.windll.user32.MessageBoxW(0, message, title, flags)
        try:
            os.unlink(payload_path)
        except OSError:
            pass
        return 0
    except Exception:
        with open(error_path, "w", encoding="utf-8") as handle:
            traceback.print_exc(file=handle)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
