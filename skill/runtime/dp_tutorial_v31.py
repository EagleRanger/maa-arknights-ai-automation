"""V31 DP-TR-1 adapter: use the verified in-battle tutorial skip control."""

from __future__ import annotations

import time

import dp_tutorial_v30 as v30

EVENT_NAME = v30.EVENT_NAME
TUTORIAL = v30.TUTORIAL
_is_target = v30._is_target
_compact_text = v30._compact_text
_find_fragmented_phrase = v30._find_fragmented_phrase
_confirm_dp1_unlocked = v30._confirm_dp1_unlocked


def _find_lowest(items, keywords, *, y_min=0):
    hits = []
    for text, cx, cy in items:
        compact = str(text).replace(" ", "")
        if int(cy) >= y_min and any(word in compact for word in keywords):
            hits.append((int(cx), int(cy)))
    return max(hits, key=lambda p: p[1]) if hits else None


def _confirm_skip_dialog(runtime):
    page = runtime.shot("dp_tr1_skip_confirm")
    items = runtime.ocr(page)
    compact = _compact_text(items)
    if not any(marker in compact for marker in ("跳过", "教学", "教程")):
        return False
    confirm = _find_lowest(items, ("确认", "确定", "跳过"), y_min=430)
    if not confirm:
        return False
    runtime.tap(*confirm)
    runtime.log(f"  [V31教程] 确认跳过教学 @{confirm}")
    runtime.wait(4)
    return True


def clear_dp_tutorial(runtime, event, stage, *, force_replay=False):
    if runtime._event_mode_has_trusted_clear_evidence(EVENT_NAME, TUTORIAL, "normal"):
        runtime.log("  [V31教程] DP-TR-1已有可信断点，直接跳过")
        return True
    entered = runtime._enter_event_stage(event, TUTORIAL, mode="normal", force_replay=force_replay)
    if isinstance(entered, tuple) and entered[0] == "already_cleared":
        return True
    if entered != TUTORIAL:
        runtime.log(f"⛔ [V31教程] 未进入DP-TR-1固定编队页: {entered}", "ERROR")
        return False

    formation = runtime.shot("dp_tr1_fixed_formation")
    items = runtime.ocr(formation)
    compact = _compact_text(items)
    start_action = _find_fragmented_phrase(items, "开始行动", y_min=760)
    if not all(marker in compact for marker in ("阿米娅", "刻俄柏", "开始行动")) or not start_action:
        runtime.log(f"⛔ [V31教程] 固定编队身份未闭环: OCR={compact[:180]}", "ERROR")
        return False
    runtime.tap(*start_action)
    runtime.log(f"  [V31教程] 固定编队确认后点击开始行动 @{start_action}")
    runtime.wait(4)

    skip_requested = False
    dialogue_taps = 0
    for step in range(70):
        page = runtime.shot(f"dp_tr1_v31_opening_{step}")
        items = runtime.ocr(page)
        compact = _compact_text(items)
        if "选择逐影先锋" in compact and ("0/1" in compact or "O/1" in compact):
            skip = _find_lowest(items, ("跳过",), y_min=0)
            if not skip:
                runtime.log("⛔ [V31教程] 已确认逐影先锋0/1页但未识别跳过控件", "ERROR")
                return False
            runtime.tap(*skip)
            runtime.log(f"  [V31教程] 逐影先锋0/1页点击右上跳过 @{skip}")
            runtime.wait(2)
            # Some versions show a confirmation, others skip immediately.
            _confirm_skip_dialog(runtime)
            skip_requested = True
            break
        start_battle = _find_fragmented_phrase(items, "开始作战", y_min=700)
        if start_battle:
            runtime.tap(*start_battle)
            runtime.log(f"  [V31教程] 点击开始作战 @{start_battle}")
            skip_requested = True
            runtime.wait(4)
            break
        if "LOG" in compact.upper():
            runtime.tap(1550, 1018)
            dialogue_taps += 1
            runtime.wait(1)
            continue
        runtime.wait(2)
    if not skip_requested:
        runtime.log(f"⛔ [V31教程] 推进对白{dialogue_taps}次仍未到逐影先锋/开始作战", "ERROR")
        return False

    deadline = time.time() + 180
    while time.time() < deadline:
        runtime.wait(5)
        state = runtime.get_state()
        if state == "story":
            runtime.skip_story()
            continue
        if state == "defeat":
            runtime.log("⛔ [V31教程] DP-TR-1显示失败", "ERROR")
            return False
        if state == "victory":
            runtime.tap(*runtime.POS_DISMISS)
            runtime.wait(3)
        if state in ("victory", "reward", "chapter_map"):
            if _confirm_dp1_unlocked(runtime, event):
                runtime._update_event_progress(
                    EVENT_NAME, TUTORIAL, "cleared",
                    "V31跳过教学后真实地图已显示DP-1", mode="normal",
                )
                runtime.log("✅ [V31教程] DP-TR-1完成，DP-1已在真实地图解锁")
                return True
    runtime.log("⛔ [V31教程] 点击跳过后3分钟内未形成结算→DP-1闭环", "ERROR")
    return False


def install(runtime):
    if getattr(runtime, "_dp_tutorial_v31_installed", False):
        return runtime
    original = runtime.clear_event_stage
    def clear_event_stage(event, stage, mode="normal", max_attempts=None, force_replay=False):
        if _is_target(event, stage, mode):
            return clear_dp_tutorial(runtime, event, stage, force_replay=force_replay)
        return original(event, stage, mode=mode, max_attempts=max_attempts, force_replay=force_replay)
    clear_event_stage._dp_tutorial_v31 = True
    runtime.clear_event_stage = clear_event_stage
    runtime._dp_tutorial_v31_installed = True
    runtime.log("  [V31] DP-TR-1逐影先锋0/1页使用可见跳过教学控件")
    return runtime
