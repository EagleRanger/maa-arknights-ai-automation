"""V39: recover later DP cards after a Copilot formation rejection."""
from __future__ import annotations

import re

import dp_event_cards_v35 as v35
import dp_progress_evidence_v38 as v38
import dp_result_navigation_v37 as v37


def _norm(value):
    return re.sub(r"\s+", "", str(value or "").upper())


def _is_dp_late_card_map(items):
    """Identify a later card view where only one full DP label remains visible."""
    words = [_norm(text) for text, _x, _y in items or []]
    joined = "".join(words)
    codes = {
        code
        for word in words
        for code in re.findall(r"DP-(?:TR-)?\d+", word)
    }
    has_card_brand = any(
        "DOLLY" in word or "OLLY'S" in word or "COMING" in word
        for word in words
    )
    has_lock_semantics = (
        any(word.startswith("LOCKE") for word in words)
        or bool(re.search(r"通关DP-\d+解锁", joined))
    )
    return (
        has_card_brand
        and has_lock_semantics
        and any(re.fullmatch(r"DP-\d+", code) for code in codes)
    )


def install(runtime):
    if getattr(runtime, "_dp_late_card_recovery_v39_installed", False):
        return runtime
    v38.install(runtime)
    old_v35_map = v35._is_dp_light_map
    old_v37_map = v37._is_dp_light_map
    original_locate = runtime._locate_event_stage

    def broad_dp_map(items):
        return old_v35_map(items) or old_v37_map(items) or _is_dp_late_card_map(items)

    def locate_event_stage(display_name, event=None):
        if str((event or {}).get("name") or "") == v38.EVENT_NAME:
            path = runtime.shot(f"dp_v39_visible_card_{display_name}")
            items = runtime.ocr(path)
            if broad_dp_map(items):
                pos = runtime._event_stage_position(items, display_name)
                if pos and runtime._event_stage_marker_reliable(pos):
                    runtime.log(
                        f"  [V39卡片] 当前后段卡片页直接定位{display_name} @{pos}"
                    )
                    return path, items, pos
        return original_locate(display_name, event=event)

    # V35/V37 closures resolve these module globals at call time. Replacing both
    # makes result readback, main-menu escape and current-card recovery agree.
    v35._is_dp_light_map = broad_dp_map
    v37._is_dp_light_map = broad_dp_map
    runtime._locate_event_stage = locate_event_stage
    runtime._dp_late_card_recovery_v39_installed = True
    runtime.log("  [V39] DP后段单关卡卡片识别与原位恢复已安装")
    return runtime
