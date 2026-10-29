"""V35: adapt the DP light-play card carousel without weakening generic stage OCR."""
from __future__ import annotations

import re
import dp_tutorial_v34 as v34


def _norm(value):
    value = str(value or "").upper().replace(" ", "")
    return re.sub(r"[‐‑‒–—―－]", "-", value)


def _clipped_dp1_position(items, display_name):
    """Recover DP-1 only from the verified first-card geometry.

    The 2026-09-22 frame reads the card as ``DP-`` while the adjacent tutorial
    card remains the exact ``DP-TR-1``.  Both anchors and their disjoint ROIs
    are required so this tolerance cannot turn another clipped stage into DP-1.
    """
    if _norm(display_name) != "DP-1":
        return None
    tutorial = any(
        _norm(text) == "DP-TR-1" and 600 <= x <= 1120 and 650 <= y <= 850
        for text, x, y in items or []
    )
    if not tutorial:
        return None
    for text, x, y in items or []:
        if _norm(text) == "DP-" and 1200 <= x <= 1580 and 540 <= y <= 720:
            return x, y
    return None


def _is_dp_light_map(items):
    normalized = [(_norm(text), x, y) for text, x, y in items or []]
    if any(text == "DP-TR-1" and 500 <= x <= 1200 for text, x, _y in normalized):
        return True
    has_locked = any(text.startswith("LOC") and "ED" in text for text, _x, _y in normalized)
    has_dp_unlock = any(re.search(r"DP-[1-6]", text) for text, _x, _y in normalized)
    return has_locked and has_dp_unlock


def _is_dp_event_lobby(items):
    words = {_norm(text) for text, _x, _y in items or []}
    return "AMUSE" in words and any("DOLLY" in word for word in words)


def install(runtime):
    if getattr(runtime, "_dp_event_cards_v35_installed", False):
        return runtime
    v34.install(runtime)
    original_position = runtime._event_stage_position
    original_main = runtime.goto_main_menu

    def event_stage_position(items, display_name):
        position = original_position(items, display_name)
        if position:
            return position
        recovered = _clipped_dp1_position(items, display_name)
        if recovered:
            runtime.log(f"  [V35卡片] DP-TR-1邻卡将截断OCR DP- 恢复为DP-1 @{recovered}")
        return recovered

    def goto_main_menu(*args, **kwargs):
        page = runtime.shot("dp_v35_main_escape_probe")
        items = runtime.ocr(page)
        if _is_dp_light_map(items):
            runtime.back()
            runtime.wait(3)
            runtime.log("  [V35卡片] 已从轻游卡片地图返回活动大厅")
            lobby = runtime.shot("dp_v35_lobby_escape_probe")
            lobby_items = runtime.ocr(lobby)
            if _is_dp_event_lobby(lobby_items):
                runtime.back()
                runtime.wait(3)
                runtime.log("  [V35卡片] 已从逐影集趣大厅返回终端")
        return original_main(*args, **kwargs)

    runtime._event_stage_position = event_stage_position
    runtime.goto_main_menu = goto_main_menu
    runtime._dp_event_cards_v35_installed = True
    runtime.log("  [V35] DP轻游卡片截断OCR定位与有界退出已安装")
    return runtime
