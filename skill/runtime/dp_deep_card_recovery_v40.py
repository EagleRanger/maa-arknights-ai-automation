"""V40: recognize deep DP card pages after the event brand scrolls off-screen."""
from __future__ import annotations

import re

import dp_event_cards_v35 as v35
import dp_late_card_recovery_v39 as v39
import dp_progress_evidence_v38 as v38
import dp_result_navigation_v37 as v37


def _norm(value):
    return re.sub(r"\s+", "", str(value or "").upper())


def _is_dp_deep_card_map(items):
    """Identify a deep DP carousel page without relying on a visible brand title.

    A branded page may expose only one full numeric stage.  Once the carousel is
    farther right, the brand can be completely off-screen, so that case requires
    two distinct exact DP numeric stages plus an explicit locked/unlock marker.
    """
    words = [_norm(text) for text, _x, _y in items or []]
    joined = "".join(words)
    codes = {
        code
        for word in words
        for code in re.findall(r"DP-(?:TR-)?\d+", word)
    }
    numeric_codes = {
        code for code in codes if re.fullmatch(r"DP-\d+", code)
    }
    has_card_brand = any(
        "DOLLY" in word or "OLLY'S" in word or "COMING" in word
        for word in words
    )
    has_lock_semantics = (
        any(word.startswith("LOCKE") for word in words)
        or bool(re.search(r"通关DP-\d+解锁", joined))
    )
    return has_lock_semantics and (
        (has_card_brand and len(numeric_codes) >= 1)
        or len(numeric_codes) >= 2
    )


def install(runtime):
    if getattr(runtime, "_dp_deep_card_recovery_v40_installed", False):
        return runtime
    v39.install(runtime)
    old_v35_map = v35._is_dp_light_map
    old_v37_map = v37._is_dp_light_map
    original_locate = runtime._locate_event_stage

    def broad_dp_map(items):
        return (
            old_v35_map(items)
            or old_v37_map(items)
            or _is_dp_deep_card_map(items)
        )

    def locate_event_stage(display_name, event=None):
        if str((event or {}).get("name") or "") == v38.EVENT_NAME:
            path = runtime.shot(f"dp_v40_visible_card_{display_name}")
            items = runtime.ocr(path)
            if broad_dp_map(items):
                pos = runtime._event_stage_position(items, display_name)
                if pos and runtime._event_stage_marker_reliable(pos):
                    runtime.log(
                        f"  [V40卡片] 当前深层卡片页直接定位{display_name} @{pos}"
                    )
                    return path, items, pos
        return original_locate(display_name, event=event)

    # V35/V37/V38 resolve these globals at call time.  Keep navigation,
    # settlement readback and historical checkpoint admission on one identity.
    v35._is_dp_light_map = broad_dp_map
    v37._is_dp_light_map = broad_dp_map
    runtime._locate_event_stage = locate_event_stage
    runtime._dp_deep_card_recovery_v40_installed = True
    runtime.log("  [V40] DP深层双关卡码卡片识别、退出与断点复核已安装")
    return runtime
