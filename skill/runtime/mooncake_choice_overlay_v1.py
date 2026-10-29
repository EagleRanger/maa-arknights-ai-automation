"""Safely leave the 2026 Mid-Autumn exclusive-choice overlay.

The two mooncake/furniture rewards are mutually exclusive.  The daily runner
may close the overlay to continue its already-authorized work, but it must not
choose either reward or report the choice as claimed.
"""

from __future__ import annotations

from PIL import Image


CLOSE_POINT = (1752, 140)
EXPECTED_SIZE = (1920, 1080)


def is_choice_page(text):
    compact = "".join(str(text or "").split()).upper()
    return (
        ("锦械映月" in compact or "MAPLESINMOONLIGHT" in compact)
        and "月饼烘焙小教程" in compact
        and "冰皮月饼" in compact
        and "水晶皮月饼" in compact
        and "材料只够制作其中一款" in compact
    )


def close_if_visible(runtime):
    """Return None if absent, True only after a verified close, else False."""
    if runtime._maa_task_queue_running():
        return False  # Never pass through to another popup handler during MAA control.
    before = runtime.shot("mooncake_choice_before")
    text = runtime.ocr_text(before)
    if not is_choice_page(text):
        return None
    with Image.open(before) as image:
        if image.size != EXPECTED_SIZE:
            runtime.log("⛔ 月饼二选一页面尺寸变化，未点击", "ERROR")
            return False
    runtime.tap(*CLOSE_POINT)
    runtime.wait(2)
    after = runtime.shot("mooncake_choice_after")
    after_text = runtime.ocr_text(after)
    if is_choice_page(after_text):
        runtime.log("⛔ 月饼二选一页面关闭后仍在原页，停止重复点击", "ERROR")
        return False
    runtime._RUN_SUMMARY["mooncake_choice"] = {
        "status": "closed_without_selection",
        "reward_claimed": False,
        "before": str(before),
        "after": str(after),
    }
    runtime.log("✅ 已关闭月饼互斥奖励选择页并复核页面变化；未代选或领取奖励")
    return True


def install(runtime):
    if getattr(runtime, "_mooncake_choice_overlay_v1_installed", False):
        return runtime.handle_popups
    original = runtime.handle_popups

    def handle_popups_with_choice(*args, **kwargs):
        outcome = close_if_visible(runtime)
        if outcome is not None:
            return outcome
        return original(*args, **kwargs)

    handle_popups_with_choice._mooncake_choice_original = original
    runtime.handle_popups = handle_popups_with_choice
    runtime._mooncake_choice_overlay_v1_installed = True
    return runtime.handle_popups
