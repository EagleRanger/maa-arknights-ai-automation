"""V37: close the DP custom-result and activity-map exit loop."""
from __future__ import annotations

import re

import dp_event_cards_v35 as v35

EVENT_NAME = "逐影集趣"


def _norm(value):
    return re.sub(r"\s+", "", str(value or "").upper())


def _dp_result_stage(items):
    """Return the exact DP stage only on Dolly's custom success receipt."""
    words = [_norm(text) for text, _x, _y in items or []]
    joined = "".join(words)
    if "MISSIONRESULT" not in joined or "挑战成功" not in joined:
        return ""
    if not any("DOLLY" in word for word in words):
        return ""
    candidates = []
    for word in words:
        candidates.extend(re.findall(r"DP-(?:TR-)?\d+", word))
    unique = list(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else ""


def _is_dp_light_map(items):
    """Recognize the real card map even when LOCKED or DP-TR-1 is clipped."""
    words = [_norm(text) for text, _x, _y in items or []]
    codes = {
        code
        for word in words
        for code in re.findall(r"DP-(?:TR-)?\d+", word)
    }
    dolly_card = any("DOLLY" in word or "COMING" in word for word in words)
    return dolly_card and len(codes) >= 2 and any(
        re.fullmatch(r"DP-\d+", code) for code in codes
    )


def install(runtime):
    if getattr(runtime, "_dp_result_navigation_v37_installed", False):
        return runtime
    v35.install(runtime)
    original_state = runtime.get_state
    original_badges = runtime._victory_three_star_status
    original_verify = runtime.verify_event_stage_cleared
    original_main = runtime.goto_main_menu

    def get_state():
        state = original_state()
        if state != "unknown":
            return state
        page = runtime.shot("dp_v37_result_probe")
        stage = _dp_result_stage(runtime.ocr(page))
        if stage:
            runtime._dp_v37_last_result_stage = stage
            runtime.log(f"  [V37结算] 识别{stage}逐影集趣挑战成功页")
            return "victory"
        return state

    def victory_three_star_status(image_path):
        result = original_badges(image_path)
        if result.get("perfect"):
            return result
        stage = _dp_result_stage(runtime.ocr(image_path))
        if not stage:
            return result
        runtime._dp_v37_last_result_stage = stage
        runtime.log(f"  [V37结算] {stage}专用挑战成功页作为本局完美直接证据")
        return {"lit": 3, "ratios": [1.0, 1.0, 1.0], "perfect": True}

    def verify_event_stage_cleared(event, display_name):
        result = original_verify(event, display_name)
        if (
            str((event or {}).get("name") or "") != EVENT_NAME
            or not re.fullmatch(r"DP-\d+", str(display_name or ""))
            or result == (True, True)
            or getattr(runtime, "_dp_v37_last_result_stage", "") != display_name
        ):
            return result
        page = runtime.shot(f"dp_v37_map_receipt_{display_name}")
        if not _is_dp_light_map(runtime.ocr(page)):
            return result
        runtime._dp_v37_last_result_stage = ""
        runtime.log(
            f"  [V37结算] {display_name}挑战成功直接证据 + DP卡片地图回读闭环"
        )
        return True, True

    def goto_main_menu(*args, **kwargs):
        page = runtime.shot("dp_v37_main_escape_probe")
        items = runtime.ocr(page)
        if _is_dp_light_map(items):
            runtime.back()
            runtime.wait(3)
            runtime.log("  [V37卡片] 已从DP卡片地图返回逐影集趣大厅")
            lobby = runtime.shot("dp_v37_lobby_escape_probe")
            if v35._is_dp_event_lobby(runtime.ocr(lobby)):
                runtime.back()
                runtime.wait(3)
                runtime.log("  [V37卡片] 已从逐影集趣大厅返回终端")
        return original_main(*args, **kwargs)

    runtime.get_state = get_state
    runtime._victory_three_star_status = victory_three_star_status
    runtime.verify_event_stage_cleared = verify_event_stage_cleared
    runtime.goto_main_menu = goto_main_menu
    runtime._dp_result_navigation_v37_installed = True
    runtime.log("  [V37] DP专用结算、地图回读与日常前退出闭环已安装")
    return runtime
