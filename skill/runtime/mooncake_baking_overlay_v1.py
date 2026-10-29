"""Close the verified Mid-Autumn baking page without choosing its reward.

The fifth ``锦枫映月`` page is not the earlier two-choice page.  Its single
``确认制作`` control is intentionally left untouched: closing the overlay is
enough to let the daily workflow continue without making a reward decision.
"""

from __future__ import annotations

from PIL import Image


EXPECTED_SIZE = (1920, 1080)
CLOSE_POINT = (1848, 150)


def is_baking_page(text: object) -> bool:
    compact = "".join(str(text or "").split()).upper()
    identity = (
        ("锦枫映月" in compact or "MAPLESINMOONLIGHT" in compact)
        and "月饼烘焙小教程·五" in compact
    )
    actionable = (
        "月饼制作" in compact
        and "确认制作" in compact
        and "水晶皮月饼" in compact
        and compact.count("已完成") >= 2
    )
    completed_calendar = (
        "馅料调制完毕" in compact
        and "月饼制作完成" in compact
        and "中秋限定家具" in compact
        and "结束时间" in compact
        and compact.count("已领取") >= 3
    )
    return identity and (actionable or completed_calendar)


def close_if_visible(runtime):
    """Return None when absent, True after a checked close, False on failure."""
    if runtime._maa_task_queue_running():
        return None
    before = runtime.shot("mooncake_baking_before")
    text = runtime.ocr_text(before)
    if not is_baking_page(text):
        return None
    with Image.open(before) as image:
        if image.size != EXPECTED_SIZE:
            runtime.log("⛔ 月饼制作页尺寸变化，未点击", "ERROR")
            return False
    runtime.tap(*CLOSE_POINT)
    runtime.wait(2)
    after = runtime.shot("mooncake_baking_after")
    if is_baking_page(runtime.ocr_text(after)):
        runtime.log("⛔ 月饼制作页关闭后仍在原页，停止重复点击", "ERROR")
        return False
    runtime._RUN_SUMMARY["mooncake_baking"] = {
        "status": "closed_without_selection",
        "reward_claimed": False,
        "before": str(before),
        "after": str(after),
    }
    runtime.log("✅ 已关闭月饼制作页并复核页面变化；未点确认制作")
    return True


def install(runtime):
    """Handle the overlay at both popup and unknown-navigation boundaries."""
    if getattr(runtime, "_mooncake_baking_overlay_v1_installed", False):
        return runtime
    old_popups = runtime.handle_popups
    old_unknown = runtime._wait_unknown_navigation_page

    def popups(*args, **kwargs):
        outcome = close_if_visible(runtime)
        return old_popups(*args, **kwargs) if outcome is None else outcome

    def unknown(*args, **kwargs):
        outcome = close_if_visible(runtime)
        return old_unknown(*args, **kwargs) if outcome is None else outcome

    runtime.handle_popups = popups
    runtime._wait_unknown_navigation_page = unknown
    runtime._mooncake_baking_overlay_v1_installed = True
    return runtime
