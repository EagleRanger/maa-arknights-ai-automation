"""V33: after skipping dialogue, select fixed-team Ceobe and start battle."""
from __future__ import annotations
import dp_tutorial_v31 as v31


def _confirm_skip_and_select_ceobe(runtime):
    page=runtime.shot("dp_tr1_v33_skip_confirm"); compact=v31._compact_text(runtime.ocr(page))
    if "是否跳过剧情" not in compact and "跳过剧情" not in compact:
        runtime.log(f"⛔ [V33教程] 跳过确认框身份不符: {compact[:160]}","ERROR"); return False
    runtime.tap(1196,542); runtime.log("  [V33教程] 点击跳过剧情右侧对勾 @(1196,542)"); runtime.wait(3)
    after=runtime.shot("dp_tr1_v33_after_skip"); items=runtime.ocr(after); text=v31._compact_text(items)
    if "是否跳过剧情" in text or "选择逐影先锋" not in text:
        runtime.log(f"⛔ [V33教程] 跳过后未回到逐影先锋选择页: {text[:160]}","ERROR"); return False
    # Fixed formation was already verified as Midnight, Popukar, Amiya, Ceobe;
    # the live 1920x1080 selection page places Ceobe in the far-right card.
    runtime.tap(1845,980); runtime.log("  [V33教程] 固定编队选择最右刻俄柏 @(1845,980)"); runtime.wait(3)
    selected=runtime.shot("dp_tr1_v33_ceobe_selected"); selected_items=runtime.ocr(selected); selected_text=v31._compact_text(selected_items)
    if "1/1" not in selected_text:
        runtime.log(f"⛔ [V33教程] 选择刻俄柏后未读到1/1: {selected_text[:180]}","ERROR"); return False
    start=v31._find_fragmented_phrase(selected_items,"开始作战",y_min=550)
    if not start:
        runtime.log(f"⛔ [V33教程] 1/1已确认但没有开始作战: {selected_text[:180]}","ERROR"); return False
    runtime.tap(*start); runtime.log(f"  [V33教程] 1/1确认后点击开始作战 @{start}"); runtime.wait(4)
    return True


def install(runtime):
    if getattr(runtime,"_dp_tutorial_v33_installed",False): return runtime
    v31._confirm_skip_dialog=_confirm_skip_and_select_ceobe
    v31.install(runtime)
    runtime._dp_tutorial_v33_installed=True
    runtime.log("  [V33] 跳过对白后选择固定队最右刻俄柏，以1/1和开始作战验收")
    return runtime
