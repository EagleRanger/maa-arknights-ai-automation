"""V29 DP-TR-1 tutorial adapter with fragmented-OCR phrase support.

The first live V28 run proved that RapidOCR can split the rendered button
``开始行动`` into two neighbouring items (``开始`` and ``行动``).  V28 joined
items with spaces and then required the unsplit phrase, so it rejected a page
which visibly contained Amiya, Ceobe and the start button.  V29 normalises the
page text for identity checks and reconstructs a button centre only from
neighbouring lower-right OCR fragments.
"""

from __future__ import annotations

import re
import time


EVENT_NAME = "逐影集趣"
TUTORIAL = "DP-TR-1"


def _is_target(event, stage, mode):
    return (
        str((event or {}).get("name") or "").replace(" ", "") == EVENT_NAME
        and str((stage or {}).get("display") or "").upper() == TUTORIAL
        and mode == "normal"
    )


def _compact_text(items):
    return re.sub(r"\s+", "", "".join(str(item[0]) for item in items))


def _find_fragmented_phrase(items, phrase, *, y_min=0):
    """Return a safe phrase centre for either one OCR item or adjacent parts."""
    direct = [
        (int(cx), int(cy))
        for text, cx, cy in items
        if int(cy) >= y_min and phrase in re.sub(r"\s+", "", str(text))
    ]
    if direct:
        return max(direct, key=lambda p: p[1])
    if phrase != "开始行动":
        return None
    starts = [
        (int(cx), int(cy)) for text, cx, cy in items
        if int(cy) >= y_min and "开始" in re.sub(r"\s+", "", str(text))
    ]
    actions = [
        (int(cx), int(cy)) for text, cx, cy in items
        if int(cy) >= y_min and "行动" in re.sub(r"\s+", "", str(text))
    ]
    pairs = []
    for sx, sy in starts:
        for ax, ay in actions:
            if abs(sy - ay) <= 90 and abs(sx - ax) <= 360:
                pairs.append(((sx + ax) // 2, (sy + ay) // 2, abs(sy - ay) + abs(sx - ax)))
    if not pairs:
        return None
    x, y, _distance = min(pairs, key=lambda p: p[2])
    return x, y


def _confirm_dp1_unlocked(runtime, event):
    if not runtime.goto_event_map(event):
        return False
    _path, _items, pos = runtime._locate_event_stage("DP-1", event=event)
    return bool(pos)


def clear_dp_tutorial(runtime, event, stage, *, force_replay=False):
    if runtime._event_mode_has_trusted_clear_evidence(EVENT_NAME, TUTORIAL, "normal"):
        runtime.log("  [V29教程] DP-TR-1已有可信断点，直接跳过")
        return True

    entered = runtime._enter_event_stage(
        event, TUTORIAL, mode="normal", force_replay=force_replay,
    )
    if isinstance(entered, tuple) and entered[0] == "already_cleared":
        return True
    if entered != TUTORIAL:
        runtime.log(f"⛔ [V29教程] 未进入DP-TR-1固定编队页: {entered}", "ERROR")
        return False

    formation = runtime.shot("dp_tr1_fixed_formation")
    formation_items = runtime.ocr(formation)
    compact = _compact_text(formation_items)
    start_action = _find_fragmented_phrase(formation_items, "开始行动", y_min=760)
    if not all(marker in compact for marker in ("阿米娅", "刻俄柏", "开始行动")) or not start_action:
        runtime.log(
            f"⛔ [V29教程] 固定编队身份未闭环: OCR={compact[:180]}", "ERROR"
        )
        return False
    runtime.tap(*start_action)
    runtime.log(f"  [V29教程] 固定编队确认后点击开始行动 @{start_action}")
    runtime.wait(4)

    tutorial_start = time.time()
    amiya_seen = False
    operation_started = False
    for step in range(35):
        page = runtime.shot(f"dp_tr1_opening_{step}")
        items = runtime.ocr(page)
        compact = _compact_text(items)
        start_battle = _find_fragmented_phrase(items, "开始作战", y_min=700)
        if start_battle and (amiya_seen or "刻俄柏" in compact):
            runtime.tap(*start_battle)
            runtime.log(f"  [V29教程] 自动选择刻俄柏后点击开始作战 @{start_battle}")
            operation_started = True
            runtime.wait(4)
            break
        if "阿米娅" in compact or "AMIYA" in compact.upper():
            if not amiya_seen:
                runtime.log("  [V29教程] 已出现阿米娅头像，等待游戏自动跳过并选择刻俄柏")
            amiya_seen = True
            runtime.wait(3)
            continue
        state = runtime.get_state()
        if state == "formation":
            runtime.log("⛔ [V29教程] 点击开始行动后仍停在编队页", "ERROR")
            return False
        runtime.tap(1780, 930)
        runtime.wait(1)
    if not operation_started:
        runtime.log(
            f"⛔ [V29教程] {int(time.time()-tutorial_start)}秒内未形成阿米娅→刻俄柏→开始作战闭环",
            "ERROR",
        )
        return False

    deadline = time.time() + 360
    entered_battle = False
    while time.time() < deadline:
        runtime.wait(5)
        state = runtime.get_state()
        if state == "battle":
            entered_battle = True
            continue
        if state == "story":
            runtime.skip_story()
            continue
        if state == "defeat":
            runtime.log("⛔ [V29教程] DP-TR-1显示失败", "ERROR")
            return False
        if state == "victory":
            runtime.tap(*runtime.POS_DISMISS)
            runtime.wait(3)
        if state in ("victory", "reward", "chapter_map", "unknown"):
            if _confirm_dp1_unlocked(runtime, event):
                runtime._update_event_progress(
                    EVENT_NAME, TUTORIAL, "cleared",
                    "V29脚本教程闭环后真实地图已显示DP-1", mode="normal",
                )
                runtime.log("✅ [V29教程] DP-TR-1完成，DP-1已在真实地图解锁")
                return True
            if state == "unknown" and not entered_battle:
                runtime.log("⛔ [V29教程] 尚未确认进入战斗且页面未知", "ERROR")
                return False
    runtime.log("⛔ [V29教程] 真实战斗未在6分钟内进入可验证终态", "ERROR")
    return False


def install(runtime):
    if getattr(runtime, "_dp_tutorial_v29_installed", False):
        return runtime
    original = runtime.clear_event_stage

    def clear_event_stage(event, stage, mode="normal", max_attempts=None, force_replay=False):
        if _is_target(event, stage, mode):
            return clear_dp_tutorial(runtime, event, stage, force_replay=force_replay)
        return original(
            event, stage, mode=mode, max_attempts=max_attempts,
            force_replay=force_replay,
        )

    clear_event_stage._dp_tutorial_v29 = True
    runtime.clear_event_stage = clear_event_stage
    runtime._dp_tutorial_v29_installed = True
    runtime.log("  [V29] DP-TR-1支持OCR拆字按钮，并继续要求DP-1真实解锁")
    return runtime
