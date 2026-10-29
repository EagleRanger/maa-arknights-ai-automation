"""V46: accept both verified DS result layouts.

DS mini-game results have now been observed in two genuine layouts:
``游玩结束`` and ``挑战成功``.  Both still require one exact DS stage,
``MISSION RESULT`` and a Dolly/Breezy brand anchor.  V45's independent
card-map readback remains mandatory before progress is committed.
"""
from __future__ import annotations

import re

import dp_ds_result_navigation_v45 as v45
import dp_event_route_v26 as route


FROZEN_DS_STAGES = {"DS-1"}


def _norm(value):
    return re.sub(r"\s+", "", str(value or "").upper())


def _ds_result_stage(items):
    """Return one exact DS stage for either verified custom-result layout."""
    words = [_norm(text) for text, _x, _y in items or []]
    joined = "".join(words)
    result_title = "游玩结束" in joined or "挑战成功" in joined
    if "MISSIONRESULT" not in joined or not result_title:
        return ""
    if not any("DOLL" in word or "BREEZY" in word for word in words):
        return ""
    candidates = []
    for word in words:
        candidates.extend(re.findall(r"DS-\d+", word))
    unique = list(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else ""


def _is_dp_ex_card_map(items):
    """Recognize a deep EX carousel with one exact EX card and lock semantics."""
    words = [_norm(text) for text, _x, _y in items or []]
    joined = "".join(words)
    if "MISSIONRESULT" in joined:
        return False
    # Count only stand-alone visible card labels. Unlock prose can legitimately
    # mention the next EX stage and must not turn one visible card into two.
    codes = {word for word in words if re.fullmatch(r"DP-EX-\d+", word)}
    has_brand = any(
        "DOLLY" in word or "OLLY'S" in word or "COMING" in word
        for word in words
    )
    has_lock = (
        any(word.startswith("LOCKE") for word in words)
        or bool(re.search(r"通关DP-EX-\d+解锁", joined))
    )
    return has_brand and has_lock and len(codes) == 1


def _images_reverify_ds_clear(runtime, event_name, stage_name, mode):
    """Re-admit a DS checkpoint only from its immutable result+map pair."""
    if (
        event_name != v45.v38.EVENT_NAME
        or mode != "normal"
        or stage_name not in FROZEN_DS_STAGES
    ):
        return False
    state = v45.v38._load_mode_state(runtime, event_name, stage_name, mode)
    if state.get("status") != "cleared":
        return False
    evidence = state.get("evidence") or {}
    if evidence.get("schema") != "ds_result_plus_card_map_v1":
        return False
    receipt = v45.v38._resolve_evidence_path(
        runtime, str(evidence.get("result_screenshot") or "")
    )
    card_map = v45.v38._resolve_evidence_path(
        runtime, str(evidence.get("map_screenshot") or "")
    )
    if receipt is None or card_map is None:
        return False
    expected_receipt = str(evidence.get("result_sha256") or "").upper()
    expected_map = str(evidence.get("map_sha256") or "").upper()
    if not expected_receipt or not expected_map:
        return False
    if (
        v45.v38._sha256(receipt) != expected_receipt
        or v45.v38._sha256(card_map) != expected_map
    ):
        return False
    if _ds_result_stage(runtime.ocr(str(receipt))) != stage_name:
        return False
    configured = runtime._configured_event_from_name(event_name)
    if configured is None and event_name == v45.v38.EVENT_NAME:
        configured = route.build_dp_event()
    return v45._is_dp_ds_card_map(runtime.ocr(str(card_map)), event=configured)


def _recover_ex_stage_after_formation(runtime, event, display_name, max_backs=4):
    """Read the EX badge after a pre-battle rejection without going home."""
    if (
        str((event or {}).get("name") or "") != v45.v38.EVENT_NAME
        or not re.fullmatch(r"DP-EX-\d+", str(display_name or "").upper())
        or getattr(runtime, "_LAST_VERIFY_ENTERED_BATTLE", False)
    ):
        return False, None
    for step in range(max_backs + 1):
        path = runtime.shot(f"dp_v46_ex_formation_recovery_{display_name}_{step}")
        items = runtime.ocr(path)
        if _is_dp_ex_card_map(items):
            runtime.log(
                f"  [V46 EX编队恢复] 已回到{display_name}深层卡片地图（回退{step}层）"
            )
            opened = runtime._open_event_stage_detail(
                event,
                display_name,
                tag="dp_v46_ex_recovery_detail",
                ensure_map=False,
            )
            if not opened:
                return True, (None, None)
            detail_path, _detail_items, _detail_text = opened
            ratio = runtime._event_normal_badges_ratio(detail_path)
            runtime.back()
            runtime.wait(2)
            cleared = ratio >= 0.08
            runtime.log(
                f"  [V46 EX编队恢复] {display_name}详情徽记cyan={ratio:.3f} → "
                f"{'已完成' if cleared else '未完成；排除当前作业并继续'}"
            )
            return True, (cleared, cleared)

        state = runtime.get_state()
        text = " ".join(str(item[0]) for item in items or [] if item)
        recoverable = state in {"operator_page", "formation", "stage_detail"}
        recoverable = recoverable or any(
            marker in text
            for marker in ("开始行动", "代理指挥", "自动编队", "编队", "干员", "技能")
        )
        if step >= max_backs or not recoverable:
            break
        runtime.back()
        runtime.wait(2)
    return False, None


def install(runtime):
    if getattr(runtime, "_dp_ds_result_navigation_v46_installed", False):
        return runtime
    # V45's installed closures resolve this module global at call time.  Patch
    # the recognizer before installation so its map double-evidence contract,
    # edge recentering and daily escape behavior remain unchanged.
    v45._ds_result_stage = _ds_result_stage
    v45.install(runtime)
    old_v35_map = v45.v35._is_dp_light_map
    old_v37_map = v45.v38.v37._is_dp_light_map

    def broad_dp_ex_map(items):
        return old_v35_map(items) or old_v37_map(items) or _is_dp_ex_card_map(items)

    # Formation rejection can return to a far-right EX carousel where only one
    # exact EX label remains.  V35/V37 closures read these globals at call time,
    # so the strict EX identity is shared by recovery and main-menu escape.
    v45.v35._is_dp_light_map = broad_dp_ex_map
    v45.v38.v37._is_dp_light_map = broad_dp_ex_map
    original_verify = runtime.verify_event_stage_cleared
    original_main = runtime.goto_main_menu
    original_trusted = runtime._event_mode_has_trusted_clear_evidence
    original_clear = runtime.clear_event_stage

    def trusted_clear(event_name, stage_name, mode):
        if original_trusted(event_name, stage_name, mode):
            return True
        cache_key = (event_name, stage_name, mode)
        cache = getattr(runtime, "_dp_v46_ds_evidence_cache", {})
        if cache_key not in cache:
            cache[cache_key] = _images_reverify_ds_clear(
                runtime, event_name, stage_name, mode
            )
            runtime._dp_v46_ds_evidence_cache = cache
        if cache[cache_key]:
            runtime.log(
                f"  [V46断点] {stage_name}结算与卡片地图双截图重新核验通过"
            )
            return True
        return False

    def clear_event_stage(event, stage, mode="normal", *args, **kwargs):
        event_name = str((event or {}).get("name") or "")
        stage_name = str((stage or {}).get("display") or "")
        if (
            event_name == v45.v38.EVENT_NAME
            and stage_name in FROZEN_DS_STAGES
            and trusted_clear(event_name, stage_name, mode)
        ):
            runtime.log(
                f"  [V46硬门] {stage_name}已有持久双图证据，禁止重新进入或战斗"
            )
            return True
        return original_clear(event, stage, mode=mode, *args, **kwargs)

    def verify_event_stage_cleared(event, display_name):
        recovered, ex_result = _recover_ex_stage_after_formation(
            runtime, event, display_name
        )
        if recovered:
            return ex_result
        is_ds = re.fullmatch(r"DS-\d+", str(display_name or "").upper())
        if (
            str((event or {}).get("name") or "") != v45.v38.EVENT_NAME
            or not is_ds
            or getattr(runtime, "_dp_v45_last_ds_result_stage", "")
            != display_name
        ):
            return original_verify(event, display_name)
        # The animated card carousel can take longer than V45's fixed three
        # seconds to become OCR-stable.  Poll only for the strict card-map
        # identity; never click or guess during this settling window.
        for attempt in range(8):
            page = runtime.shot(
                f"dp_v46_map_settle_{display_name}_{attempt}"
            )
            items = runtime.ocr(page)
            if v45._is_dp_ds_card_map(items, event=event):
                runtime._dp_v45_last_ds_result_stage = ""
                runtime.log(
                    f"  [V46结算] {display_name}双版式结果 + "
                    f"稳定卡片地图回读闭环 ({attempt + 1}/8)"
                )
                return True, True
            if attempt < 7:
                runtime.wait(1.5)
        runtime.log(
            f"❌ [V46结算] {display_name}结果已确认，但卡片地图在稳定窗口内未出现",
            "ERROR",
        )
        return None, None

    def goto_main_menu(*args, **kwargs):
        page = runtime.shot("dp_v46_startup_result_probe")
        stage = _ds_result_stage(runtime.ocr(page))
        if stage:
            event = runtime.get_active_event()
            runtime._dp_v45_last_ds_result_stage = stage
            runtime.tap(*runtime.POS_DISMISS)
            runtime.wait(3)
            cleared, perfect = verify_event_stage_cleared(event, stage)
            if cleared and perfect:
                updater = getattr(runtime, "_update_event_progress", None)
                if callable(updater):
                    updater(
                        event["name"],
                        stage,
                        "cleared",
                        "normal; recovered DS custom result + card-map receipt",
                        mode="normal",
                        record_attempt=False,
                    )
                runtime.log(
                    f"  [V46启动恢复] {stage}结果+地图双证据已落账，继续退出活动"
                )
        return original_main(*args, **kwargs)

    runtime.verify_event_stage_cleared = verify_event_stage_cleared
    runtime.goto_main_menu = goto_main_menu
    runtime._event_mode_has_trusted_clear_evidence = trusted_clear
    runtime.clear_event_stage = clear_event_stage
    runtime._dp_ds_result_navigation_v46_installed = True
    runtime.log(
        "  [V46] DS双版式结算、动画地图稳定等待与启动恢复已安装"
    )
    return runtime
