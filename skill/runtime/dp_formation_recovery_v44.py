"""V44: keep pre-battle formation recovery out of post-battle settlement.

V43 correctly recovered a DP card map after an operator/formation rejection,
but its verifier also intercepted the normal post-battle verification call.
That bypassed V37's custom result-plus-card-map closure and tried to read the
standard cyan badge geometry from DP's custom detail panel.  V44 preserves the
bounded recovery only when no battle/result evidence exists; otherwise the
frozen V37 chain remains authoritative.
"""
from __future__ import annotations

import re

import dp_deep_card_recovery_v40 as v40
import dp_event_cards_v35 as v35
import dp_progress_evidence_v38 as v38


def _is_numeric_dp_stage(value):
    return re.fullmatch(r"DP-\d+", str(value or "").upper()) is not None


def _recover_visible_dp_card_map(runtime, display_name, max_backs=4):
    """Return the strict DP card map after bounded recognized back steps."""
    for step in range(max_backs + 1):
        path = runtime.shot(f"dp_v44_formation_recovery_{display_name}_{step}")
        items = runtime.ocr(path)
        if v35._is_dp_light_map(items):
            runtime.log(
                f"  [V44编队恢复] 已回到{display_name}所在DP卡片地图（回退{step}层）"
            )
            return path, items

        state = runtime.get_state()
        text = " ".join(str(item[0]) for item in items or [] if item)
        recoverable = state in {"operator_page", "formation", "stage_detail"}
        recoverable = recoverable or any(
            marker in text
            for marker in (
                "开始行动", "代理指挥", "自动编队", "编队", "干员", "技能",
            )
        )
        if step >= max_backs or not recoverable:
            break
        runtime.back()
        runtime.wait(2)
    return None, []


def _has_post_battle_evidence(runtime, display_name):
    return bool(getattr(runtime, "_LAST_VERIFY_ENTERED_BATTLE", False)) or (
        getattr(runtime, "_dp_v37_last_result_stage", "") == display_name
    )


def install(runtime):
    if getattr(runtime, "_dp_formation_recovery_v44_installed", False):
        return runtime
    v40.install(runtime)
    original_goto_event_map = runtime.goto_event_map
    original_verify = runtime.verify_event_stage_cleared

    def goto_event_map(event=None, *args, **kwargs):
        if str((event or {}).get("name") or "") == v38.EVENT_NAME:
            path = runtime.shot("dp_v44_event_map_probe")
            if v35._is_dp_light_map(runtime.ocr(path)):
                runtime.log("  [V44卡片] 已在逐影集趣卡片地图，不绕回主页")
                return True
        return original_goto_event_map(event, *args, **kwargs)

    def verify_event_stage_cleared(event, display_name):
        if (
            str((event or {}).get("name") or "") != v38.EVENT_NAME
            or not _is_numeric_dp_stage(display_name)
        ):
            return original_verify(event, display_name)

        # A real battle or V37 result marker owns the settlement path.  This is
        # the decisive V44 boundary: never replace the DP custom result+map
        # proof with the unrelated standard cyan-badge detector.
        if _has_post_battle_evidence(runtime, display_name):
            runtime.log(
                f"  [V44结算边界] {display_name}已有战斗/专用结果证据，委托V37闭环"
            )
            return original_verify(event, display_name)

        recovered_path, _items = _recover_visible_dp_card_map(runtime, display_name)
        if not recovered_path:
            return original_verify(event, display_name)

        opened = runtime._open_event_stage_detail(
            event,
            display_name,
            tag="dp_v44_recovery_detail",
            ensure_map=False,
        )
        if not opened:
            runtime.log(
                f"❌ [V44编队恢复] 已确认DP卡片地图但无法打开{display_name}详情",
                "ERROR",
            )
            return None, None
        detail_path, _detail_items, _detail_text = opened
        ratio = runtime._event_normal_badges_ratio(detail_path)
        runtime.back()
        runtime.wait(2)
        cleared = ratio >= 0.08
        runtime.log(
            f"  [V44编队恢复] {display_name}详情徽记cyan={ratio:.3f} → "
            f"{'已完成' if cleared else '未完成；排除当前作业并继续'}"
        )
        return cleared, cleared

    runtime.goto_event_map = goto_event_map
    runtime.verify_event_stage_cleared = verify_event_stage_cleared
    runtime._dp_formation_recovery_v44_installed = True
    runtime.log("  [V44] DP编队失败恢复与战后专用结算边界已安装")
    return runtime

