"""V30 DP-TR-1 adapter: advance verified dialogue before waiting for selection."""

from __future__ import annotations

import re
import time

import dp_tutorial_v29 as v29


EVENT_NAME = v29.EVENT_NAME
TUTORIAL = v29.TUTORIAL
_is_target = v29._is_target
_compact_text = v29._compact_text
_confirm_dp1_unlocked = v29._confirm_dp1_unlocked


def _find_fragmented_phrase(items, phrase, *, y_min=0):
    direct = [
        (int(cx), int(cy)) for text, cx, cy in items
        if int(cy) >= y_min and phrase in re.sub(r"\s+", "", str(text))
    ]
    if direct:
        return max(direct, key=lambda p: p[1])
    fragments = {
        "开始行动": ("开始", "行动"),
        "开始作战": ("开始", "作战"),
    }.get(phrase)
    if not fragments:
        return None
    left = [
        (int(cx), int(cy)) for text, cx, cy in items
        if int(cy) >= y_min and fragments[0] in re.sub(r"\s+", "", str(text))
    ]
    right = [
        (int(cx), int(cy)) for text, cx, cy in items
        if int(cy) >= y_min and fragments[1] in re.sub(r"\s+", "", str(text))
    ]
    pairs = []
    for lx, ly in left:
        for rx, ry in right:
            if abs(ly - ry) <= 90 and abs(lx - rx) <= 360:
                pairs.append(((lx + rx) // 2, (ly + ry) // 2, abs(ly - ry) + abs(lx - rx)))
    if not pairs:
        return None
    x, y, _distance = min(pairs, key=lambda p: p[2])
    return x, y


def clear_dp_tutorial(runtime, event, stage, *, force_replay=False):
    if runtime._event_mode_has_trusted_clear_evidence(EVENT_NAME, TUTORIAL, "normal"):
        runtime.log("  [V30教程] DP-TR-1已有可信断点，直接跳过")
        return True
    entered = runtime._enter_event_stage(
        event, TUTORIAL, mode="normal", force_replay=force_replay,
    )
    if isinstance(entered, tuple) and entered[0] == "already_cleared":
        return True
    if entered != TUTORIAL:
        runtime.log(f"⛔ [V30教程] 未进入DP-TR-1固定编队页: {entered}", "ERROR")
        return False

    formation = runtime.shot("dp_tr1_fixed_formation")
    formation_items = runtime.ocr(formation)
    compact = _compact_text(formation_items)
    start_action = _find_fragmented_phrase(formation_items, "开始行动", y_min=760)
    if not all(marker in compact for marker in ("阿米娅", "刻俄柏", "开始行动")) or not start_action:
        runtime.log(f"⛔ [V30教程] 固定编队身份未闭环: OCR={compact[:180]}", "ERROR")
        return False
    runtime.tap(*start_action)
    runtime.log(f"  [V30教程] 固定编队确认后点击开始行动 @{start_action}")
    runtime.wait(4)

    # Live V29 evidence proved that OCR text "阿米娅" was only the speaker name
    # inside a dialogue box, not the top-left selectable operator portrait from
    # the author note.  A visible LOG anchor identifies that verified dialogue;
    # advance its explicit lower-right arrow and only wait once the dialogue is
    # gone.  This remains bounded and tutorial-specific.
    operation_started = False
    amiya_dialogue_seen = False
    dialogue_taps = 0
    for step in range(60):
        page = runtime.shot(f"dp_tr1_v30_opening_{step}")
        items = runtime.ocr(page)
        compact = _compact_text(items)
        start_battle = _find_fragmented_phrase(items, "开始作战", y_min=700)
        if start_battle:
            runtime.tap(*start_battle)
            runtime.log(f"  [V30教程] 教程选择完成后点击开始作战 @{start_battle}")
            operation_started = True
            runtime.wait(4)
            break
        state = runtime.get_state()
        if state == "battle":
            runtime.log("  [V30教程] 游戏已直接进入教程战斗")
            operation_started = True
            break
        if "阿米娅" in compact:
            amiya_dialogue_seen = True
        if "LOG" in compact.upper():
            runtime.tap(1550, 1018)
            dialogue_taps += 1
            runtime.wait(1)
            continue
        runtime.wait(2)
    if not operation_started:
        runtime.log(
            f"⛔ [V30教程] 对白推进{dialogue_taps}次后未出现开始作战/战斗；"
            f"阿米娅对白={amiya_dialogue_seen}",
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
            runtime.log("⛔ [V30教程] DP-TR-1显示失败", "ERROR")
            return False
        if state == "victory":
            runtime.tap(*runtime.POS_DISMISS)
            runtime.wait(3)
        if state in ("victory", "reward", "chapter_map"):
            if _confirm_dp1_unlocked(runtime, event):
                runtime._update_event_progress(
                    EVENT_NAME, TUTORIAL, "cleared",
                    "V30对话教程闭环后真实地图已显示DP-1", mode="normal",
                )
                runtime.log("✅ [V30教程] DP-TR-1完成，DP-1已在真实地图解锁")
                return True
    runtime.log(
        f"⛔ [V30教程] 已点击开始作战但6分钟内无可验证终态；进入战斗={entered_battle}",
        "ERROR",
    )
    return False


def install(runtime):
    if getattr(runtime, "_dp_tutorial_v30_installed", False):
        return runtime
    original = runtime.clear_event_stage

    def clear_event_stage(event, stage, mode="normal", max_attempts=None, force_replay=False):
        if _is_target(event, stage, mode):
            return clear_dp_tutorial(runtime, event, stage, force_replay=force_replay)
        return original(event, stage, mode=mode, max_attempts=max_attempts, force_replay=force_replay)

    clear_event_stage._dp_tutorial_v30 = True
    runtime.clear_event_stage = clear_event_stage
    runtime._dp_tutorial_v30_installed = True
    runtime.log("  [V30] DP-TR-1按LOG对白箭头推进，不再把说话人姓名当头像")
    return runtime
