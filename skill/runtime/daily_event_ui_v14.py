"""V14 adapters for SR activity navigation proven on 2026-09-17.

The frozen daily runtime has two independent entry paths: its normal
``goto_main_menu`` back-stack loop and the cold-start branch in ``mode_daily``.
The latter used to treat an unclassified, but running, SR-EX map as if the game
had not launched, waited 240 seconds, and then started MAA on that map.  V14
keeps the frozen runtime intact while installing the same visual identity at
that earlier decision point.
"""

from __future__ import annotations


def _recover_sr_special_map_before_daily(runtime):
    """Return ``True`` when no V14 recovery is needed or it was verified.

    ``False`` is deliberately terminal for this daily invocation: a recognised
    SR special map is not a valid page for MAA's StartUp chain, so failing to
    return to the real main menu must block that chain rather than retrying it
    on the wrong page.  A running MAA queue remains entirely hands-off.
    """
    if runtime._maa_daily_queue_running() or runtime._maa_task_queue_running():
        return True
    state = runtime.get_state()
    if state != "unknown":
        return True
    path = runtime.shot("daily_sr_special_entry_probe")
    text = runtime.ocr_text(path)
    from event_page_guard_v2 import is_sr_special_hall

    if not is_sr_special_hall(text):
        return True
    runtime.log("→ 日常V14确认SR-EX纵向地图；先走已验证返回主页链，禁止原地启动MAA")
    if not runtime.goto_main_menu():
        runtime._RUN_SUMMARY["daily_ui_handoff"] = {
            "status": "blocked",
            "reason": "sr_special_hall_return_main_menu_unverified",
            "screenshot": str(path),
            "ocr": text,
        }
        runtime.log("⛔ SR-EX地图未能核验返回主页；拒绝启动MAA日常链", "ERROR")
        return False
    runtime._RUN_SUMMARY["daily_ui_handoff"] = {
        "status": "main_menu_verified_from_sr_special_hall",
        "screenshot": str(path),
    }
    runtime.log("✅ 日常V14已从SR-EX地图核验返回主页")
    return True


def install(runtime) -> None:
    """Install only additive V14 classifiers over the frozen daily runtime."""
    from event_badge_v2 import install_normal_badge_detector
    from event_page_guard_v2 import install_unknown_navigation_guard

    install_unknown_navigation_guard(runtime)
    install_normal_badge_detector(runtime)
    if not getattr(runtime, "_daily_event_ui_v14_installed", False):
        original_mode_daily = runtime.mode_daily

        def mode_daily_v14(*args, **kwargs):
            if not _recover_sr_special_map_before_daily(runtime):
                return False
            return original_mode_daily(*args, **kwargs)

        runtime.mode_daily = mode_daily_v14
        runtime._daily_event_ui_v14_installed = True
    if not getattr(runtime, "_event_page_guard_v2_installed", False):
        raise RuntimeError("V14 navigation guard was not installed")
    if not getattr(runtime, "_event_badge_v2_installed", False):
        raise RuntimeError("V14 normal-badge detector was not installed")
    if not getattr(runtime, "_daily_event_ui_v14_installed", False):
        raise RuntimeError("V14 daily SR special-map handoff was not installed")
