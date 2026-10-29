"""Reuse the daily checked MuMu launch in standalone VEC processes.

Does not start anything on installation. A failed launch is recorded at the
environment boundary, not reclassified as missing files or a battle failure.
"""
from daily_environment_gate_v22 import (
    EnvironmentStartupAbort, _launch_and_require_ready,
)


def install(runtime):
    if getattr(runtime, "_vector_environment_startup_v1_installed", False):
        return runtime
    original_run = runtime._run_mumu
    original_ensure = runtime.ensure_env

    def checked_run(*args, timeout=30):
        normalized = tuple(str(value) for value in args)
        if "control" not in normalized or "launch" not in normalized:
            return original_run(*args, timeout=timeout)
        # The old facade uses -v, while the reusable gate expects --vmindex.
        normalized = tuple("--vmindex" if value == "-v" else value
                           for value in normalized)
        return _launch_and_require_ready(
            runtime, original_run, normalized, timeout=timeout)

    def checked_ensure():
        try:
            ready = original_ensure()
        except EnvironmentStartupAbort as exc:
            runtime._RUN_SUMMARY["environment_startup"] = {
                "status": "failed", "reason": exc.reason, "detail": exc.detail,
                "business_started": False,
            }
            runtime.log(f"环境启动失败：{exc.reason}: {exc.detail}", "ERROR")
            return False
        runtime._RUN_SUMMARY["environment_startup"] = {
            "status": "ready" if ready else "failed",
            "device": runtime.DEVICE,
            "reason": None if ready else "legacy_environment_not_ready",
        }
        return ready

    runtime._run_mumu = checked_run
    runtime.ensure_env = checked_ensure
    runtime._vector_environment_startup_v1_installed = True
    return runtime
