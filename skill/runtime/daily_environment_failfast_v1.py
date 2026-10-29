"""Stop daily finalisation from probing an environment that never started.

The legacy runtime correctly returns when ``ensure_env`` fails, but its
``finally`` block still performs reward, screenshot, sanity and notification
steps.  Those steps can spend several minutes talking to a missing ADB device
and can also recover stale same-day evidence.  This adapter records the gate
result and turns only those game-dependent finalisers into explicit no-ops;
cleanup and report generation are intentionally left intact.
"""

from __future__ import annotations

from datetime import datetime


def install(runtime):
    if getattr(runtime, "_daily_environment_failfast_v1_installed", False):
        return runtime

    original_ensure = runtime.ensure_env
    original_confirm = runtime._confirm_daily_chains_complete
    original_verify = runtime.verify_daily_completion
    original_capture = runtime._capture_stamina_observation
    original_claim = runtime.claim_daily_rewards
    original_notify = runtime.notify_completion

    def environment_ready():
        return getattr(runtime, "_DAILY_ENVIRONMENT_READY", None) is not False

    def ensure_env():
        ok = original_ensure()
        runtime._DAILY_ENVIRONMENT_READY = ok is True
        if ok is not True:
            runtime._RUN_SUMMARY["environment_gate"] = {
                "status": "failed_before_game_action",
                "verified": True,
                "checked_at": datetime.now().astimezone().isoformat(),
                "game_actions": 0,
                "finalisation_policy": "cleanup_and_report_only",
            }
            runtime.log(
                "⛔ 环境未就绪：跳过领奖、截图、理智读取和完成弹窗，仅执行清理与失败报告",
                "ERROR",
            )
        return ok

    def confirm_daily_chains_complete(*args, **kwargs):
        if not environment_ready():
            return False
        return original_confirm(*args, **kwargs)

    def verify_daily_completion(*args, **kwargs):
        if not environment_ready():
            runtime.log("  [环境失败快速收口] 跳过日常截图验证")
            return {"当前状态": "environment_unavailable"}
        return original_verify(*args, **kwargs)

    def capture_stamina_observation(*args, **kwargs):
        if not environment_ready():
            phase = args[0] if args else kwargs.get("phase", "unknown")
            result = {
                "phase": phase,
                "verified": False,
                "value": None,
                "reason": "environment_not_ready",
            }
            runtime._RUN_SUMMARY.setdefault("stamina_observations", {})[phase] = result
            runtime.log(f"  [环境失败快速收口] 跳过{phase}理智读取")
            return result
        return original_capture(*args, **kwargs)

    def claim_daily_rewards(*args, **kwargs):
        if not environment_ready():
            runtime.log("  [环境失败快速收口] 跳过手动领奖")
            return False
        return original_claim(*args, **kwargs)

    def notify_completion(*args, **kwargs):
        if not environment_ready():
            runtime.log("  [环境失败快速收口] 不弹出可能误导的完成窗口")
            return False
        return original_notify(*args, **kwargs)

    runtime.ensure_env = ensure_env
    runtime._confirm_daily_chains_complete = confirm_daily_chains_complete
    runtime.verify_daily_completion = verify_daily_completion
    runtime._capture_stamina_observation = capture_stamina_observation
    runtime.claim_daily_rewards = claim_daily_rewards
    runtime.notify_completion = notify_completion
    runtime._daily_environment_failfast_v1_installed = True
    return runtime
