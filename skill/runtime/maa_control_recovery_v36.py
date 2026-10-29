"""V36 MAA control-state hardening.

The GUI log is append-only across launches.  A stale historical Infrast start
must not be treated as a live queue when the current MAA window exposes no
enabled Stop action.  This adapter keeps the existing semantic log checks but
adds the current UI control-state proof required for any live-queue claim.
"""
from __future__ import annotations


def _enabled_stop_control(runtime) -> bool:
    try:
        import uiautomation as ua

        maa = runtime._find_real_maa_window(ua)
        if not maa:
            return False
        for node in runtime._uia_descendants(maa):
            if getattr(node, "ControlTypeName", "") != "ButtonControl":
                continue
            if str(getattr(node, "Name", "") or "").strip() != "停止":
                continue
            if not bool(getattr(node, "IsEnabled", False)):
                continue
            if runtime._uia_control_visible(node):
                return True
    except Exception:
        return False
    return False


def _resource_damage_dialog(runtime, maa):
    try:
        nodes = [maa] + runtime._uia_descendants(maa)
    except Exception:
        return None
    texts = [str(getattr(node, "Name", "") or "") for node in nodes]
    has_error = any(text.strip() == "错误" for text in texts)
    has_damage = any("资源损坏" in text and "完整包" in text for text in texts)
    if not (has_error and has_damage):
        return None
    return next((
        node for node in nodes
        if getattr(node, "ControlTypeName", "") == "ButtonControl"
        and str(getattr(node, "Name", "") or "").strip() == "退出"
        and bool(getattr(node, "IsEnabled", False))
    ), None)


def install(runtime):
    if getattr(runtime, "_maa_control_recovery_v36_installed", False):
        return runtime
    original_running = runtime._maa_task_queue_running
    original_daily = runtime._maa_daily_queue_running
    original_prepare = runtime._prepare_maa_copilot_page
    warned = {"stale": False}

    def task_queue_running():
        if not original_running():
            return False
        if _enabled_stop_control(runtime):
            return True
        if not warned["stale"]:
            runtime.log(
                "  [V36 MAA] GUI日志有历史running标记，但当前无可用停止按钮；按空闲/启动失败处理",
                "WARN",
            )
            warned["stale"] = True
        return False

    def daily_queue_running():
        return task_queue_running() and original_daily()

    def prepare_copilot_page(ua, maa, attempts=6):
        exit_button = _resource_damage_dialog(runtime, maa)
        if exit_button:
            runtime.log(
                "  ❌ MAA仍报告资源损坏；V36已拒绝把禁用控件误判为自动战斗页",
                "ERROR",
            )
            runtime._RUN_SUMMARY["maa_resource_gate"] = {
                "status": "resource_damage_dialog",
                "control_state": "copilot_disabled",
            }
            return maa, None
        return original_prepare(ua, maa, attempts=attempts)

    runtime._maa_task_queue_running = task_queue_running
    runtime._maa_daily_queue_running = daily_queue_running
    runtime._prepare_maa_copilot_page = prepare_copilot_page
    runtime._maa_control_recovery_v36_installed = True
    runtime.log("  [V36 MAA] 实时停止按钮门与资源损坏显式分类已安装")
    return runtime
