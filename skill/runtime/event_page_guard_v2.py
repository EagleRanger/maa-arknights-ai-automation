"""Event-navigation identities shared by the next daily entry candidate.

This module is deliberately read-only with respect to the game.  It closes a
gap exposed by the 2026-09-17 live run: the generic unknown-page watchdog did
not share the already verified funeral-hall identity and therefore reported a
perfectly valid vertical SR-EX map as an unknown page.
"""

from __future__ import annotations

import re


_SR_EX = re.compile(r"SR\s*[-—–]?\s*EX\s*[-—–]?\s*\d+", re.I)


def _compact(value: object) -> str:
    return "".join(str(value or "").split()).upper()


def is_sr_special_hall(text: object) -> bool:
    """Recognise any viewport of the validated 殡仪堂 vertical stage strip.

    The list can legitimately show SR-EX-1..5 or SR-EX-4..8 after scrolling.
    Stage numbers are therefore evidence of the page identity, never a fixed
    whitelist for one viewport.
    """
    value = _compact(text)
    return "要去哪里" in value and _SR_EX.search(value) is not None


def navigation_identity(state: object, ocr_text: object) -> str:
    """Classify only the safe, semantically explicit navigation identities."""
    if is_sr_special_hall(ocr_text):
        return "sr_special_hall"
    if str(state or "") in {
        "main_menu", "reward", "victory", "chapter_map", "stage_detail",
        "quick_nav_overlay", "announcement", "terminal_list",
    }:
        return "known_runtime_page"
    return "unknown"


def install_unknown_navigation_guard(runtime) -> None:
    """Install the V2 watcher without modifying the frozen runtime artifact.

    A recognised special-map is a known back-stack page when ``goto_main_menu``
    calls the watcher.  With MAA idle, the pre-existing safe action is one Back
    followed by a new loop.  With MAA active, no input is ever sent.
    """
    if getattr(runtime, "_event_page_guard_v2_installed", False):
        return

    def wait_unknown_navigation_page():
        observations = []
        for index in range(3):
            if runtime._maa_task_queue_running():
                runtime.log("  [页面观察V2] MAA仍运行，不干预游戏", "WARN")
                return False
            state = runtime.get_state()
            path = runtime.shot("unknown_navigation_probe")
            text = runtime.ocr_text(path)
            identity = navigation_identity(state, text)
            observations.append({
                "screenshot": path, "ocr": text, "state": state,
                "identity": identity,
            })
            if identity == "sr_special_hall":
                runtime.log("  [页面观察V2] 已确认殡仪堂SR-EX纵向地图，按已知返回链退出", "WARN")
                runtime.back()
                runtime.wait(3)
                return True
            if identity == "known_runtime_page":
                return True
            if index < 2:
                runtime.wait(15)
        return runtime._event_page_attention(
            "unknown_page_no_verified_progress_30s", observations=observations
        )

    runtime._wait_unknown_navigation_page = wait_unknown_navigation_page
    runtime._event_page_guard_v2_installed = True
