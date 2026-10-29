"""Prevent an unfinished zero-sanity DP event from diverting sanity to resources.

V26 safely returns to the home screen after an incompatible EX job, but then
calls the inventory resource route even for a deferred event.  Keep its
verified navigation and reward handling; gate only the stamina consumer.
"""

from __future__ import annotations


EVENT_NAME = "逐影集趣"
DEFERRED = {"deferred_event_job", "deferred_ex_job"}


def may_farm_after_event(event_run: dict | None) -> bool:
    """An active DP event never silently diverts sanity to ordinary resources."""
    if not isinstance(event_run, dict):
        return True
    if str(event_run.get("name") or "").replace(" ", "") != EVENT_NAME:
        return True
    return False


def install(runtime):
    if getattr(runtime, "_dp_event_priority_v50_installed", False):
        return runtime

    original_depot = runtime.mode_depot_resource_fallback
    original_rock = runtime.mode_orundum_rock_fallback

    def guarded_call(original):
        event_run = runtime._RUN_SUMMARY.get("event")
        if may_farm_after_event(event_run):
            return original()
        reason = event_run.get("first_clear_result")
        event_run["stamina_diversion_forbidden"] = True
        event_run["stamina_policy"] = "活动开放期间理智只用于活动；无活动理智关或推进受阻时等待用户决策"
        runtime._RUN_SUMMARY.setdefault("remaining_sanity_use", {}).update({
            "status": "awaiting_event_stamina_decision",
            "detail": f"逐影集趣开放、首通状态={reason}；不转刷芯片/1-7/AP-5，保留理智并继续安全尾链",
            "source": "dp_event_priority_v50",
        })
        if hasattr(runtime, "_block_stamina_flow"):
            runtime._block_stamina_flow("活动开放期间不能擅自转刷普通理智资源关", source="dp_event_priority_v50")
        runtime.log("  [V50] 活动开放，阻止普通理智资源兜底；等待用户决策")
        return False

    def guarded_depot():
        return guarded_call(original_depot)

    def guarded_rock():
        return guarded_call(original_rock)

    runtime.mode_depot_resource_fallback = guarded_depot
    runtime.mode_orundum_rock_fallback = guarded_rock
    runtime._dp_event_priority_v50_installed = True
    return runtime
