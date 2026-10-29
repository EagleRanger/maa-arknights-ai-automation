"""Install environment-dependent finalisation gates AFTER the full adapter graph."""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import os


def execution_identity():
    """Read the effective Windows token; never change ACLs or permissions."""
    if os.name != "nt":
        return {"restricted_token": False, "platform": os.name}
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.IsTokenRestricted.argtypes = [wintypes.HANDLE]
    advapi.IsTokenRestricted.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return {"restricted_token": bool(advapi.IsTokenRestricted(token)), "platform": "nt"}
    finally:
        kernel.CloseHandle(token)


def require_desktop_identity(probe=None):
    result = (probe or execution_identity)()
    if result["restricted_token"]:
        raise RuntimeError("execution_identity_restricted: 当前执行命令使用Windows受限令牌；"
                           "本机已实证进程查询拒绝与MuMu -503。请由用户在执行对话权限设置中"
                           "选择允许桌面运行的配置后重试；脚本不会修改或绕过沙箱。")
    return result


def unavailable(runtime):
    summary = runtime._RUN_SUMMARY
    return (getattr(runtime, "_DAILY_ENVIRONMENT_READY", None) is False
            or (summary.get("environment_startup") or {}).get("status") == "failed")


def install(runtime):
    # No installed flag from an earlier inner wrapper can prove the current
    # callable is still protected. Called exactly once at the engine boundary.
    def guard(name, failure):
        original = getattr(runtime, name)
        @wraps(original)
        def call(*args, **kwargs):
            if unavailable(runtime):
                return failure(*args, **kwargs)
            return original(*args, **kwargs)
        call._environment_final_boundary_v1 = True
        setattr(runtime, name, call)

    def capture(phase, *args, **kwargs):
        observation = {"phase": phase, "verified": False, "value": None,
                       "reason": "environment_not_ready"}
        runtime._RUN_SUMMARY.setdefault("stamina_observations", {})[str(phase)] = observation
        return observation

    guard("_capture_stamina_observation", capture)
    guard("_confirm_daily_chains_complete", lambda *a, **k: False)
    guard("verify_daily_completion", lambda *a, **k: {"当前状态": "environment_unavailable"})
    guard("claim_daily_rewards", lambda *a, **k: False)
    guard("notify_completion", lambda *a, **k: False)
    cleanup = runtime.cleanup_after_task
    def cleanup_without_badges(*args, **kwargs):
        if unavailable(runtime):
            # check_badges is the first argument; avoid a duplicate argument.
            if args:
                args = (False, *args[1:])
            else:
                kwargs["check_badges"] = False
        return cleanup(*args, **kwargs)
    runtime.cleanup_after_task = cleanup_without_badges
    return runtime


@contextmanager
def engine_boundary(runtime):
    original = runtime.main
    @wraps(original)
    def main(*args, **kwargs):
        install(runtime)
        return original(*args, **kwargs)
    runtime.main = main
    try:
        yield
    finally:
        runtime.main = original
