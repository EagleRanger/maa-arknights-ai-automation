"""V45: close DS custom results and recenter edge-bound DS cards.

The zero-sanity DS stages use a different Dolly receipt from numeric DP stages:
``游玩结束`` replaces ``挑战成功`` and there are no standard cyan result
badges.  This adapter accepts that receipt only with four independent anchors,
then still requires a real activity card-map readback before progress can be
committed.  It also recentres an exact DS label found at either screen edge;
the edge label itself is never returned as a clickable node.
"""
from __future__ import annotations

import re

import dp_event_cards_v35 as v35
import dp_formation_recovery_v44 as v44
import dp_progress_evidence_v38 as v38


def _norm(value):
    return re.sub(r"\s+", "", str(value or "").upper())


def _ds_result_stage(items):
    """Return one exact DS stage only on Dolly's custom finished receipt."""
    words = [_norm(text) for text, _x, _y in items or []]
    joined = "".join(words)
    if "MISSIONRESULT" not in joined or "游玩结束" not in joined:
        return ""
    if not any("DOLL" in word or "BREEZY" in word for word in words):
        return ""
    candidates = []
    for word in words:
        candidates.extend(re.findall(r"DS-\d+", word))
    unique = list(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else ""


def _stage_codes(items):
    return {
        code
        for text, _x, _y in items or []
        for code in re.findall(
            r"(?:DP-(?:TR-|EX-)?\d+|DS-\d+)", _norm(text)
        )
    }


def _is_dp_ds_card_map(items, event=None):
    """Recognize a DP/DS card map without confusing it with a result page."""
    words = [_norm(text) for text, _x, _y in items or []]
    joined = "".join(words)
    if "MISSIONRESULT" in joined:
        return False
    codes = _stage_codes(items)
    configured = {
        str(row.get("display") or "").upper()
        for row in (event or {}).get("stages", [])
        if row.get("display")
    }
    if configured:
        codes &= configured
    map_semantics = any(
        marker in joined
        for marker in ("DOLL", "COMING", "LOCKED", "解锁", "轻游", "欢动")
    )
    return map_semantics and len(codes) >= 2


def _recenter_swipe(runtime, pos, swipe_y):
    x, _y = pos
    if x < 230:
        return runtime.swipe(800, swipe_y, 1250, swipe_y, 450)
    if x > 1650:
        return runtime.swipe(1200, swipe_y, 750, swipe_y, 450)
    return None


def _locate_ds_stage(runtime, display_name, event=None):
    """Locate a DS card and require a post-recentre exact OCR readback."""
    event = event or runtime.get_active_event()
    swipe_y = int((event or {}).get("navigation_swipe_y", 700))
    reset_swipe = tuple((event or {}).get(
        "navigation_reset_swipe", (950, swipe_y, 1600, swipe_y, 700)
    ))
    forward_swipe = tuple((event or {}).get(
        "navigation_forward_swipe", (1500, swipe_y, 950, swipe_y, 700)
    ))
    if not runtime._select_event_stage_section(display_name, event=event):
        return None, [], None

    for overlay_round in range(4):
        for _ in range(5):
            if runtime.swipe(*reset_swipe) is False:
                runtime._event_page_attention(
                    "adb_swipe_rejected",
                    display_name,
                    "input injection failed; no further map actions",
                )
                return None, [], None
            runtime.wait(1)

        restart_after_overlay = False
        for attempt in range(24):
            path = runtime.shot(
                f"dp_v45_stage_{display_name}_{overlay_round}_{attempt}"
            )
            items = runtime.ocr(path)
            if runtime._dismiss_known_event_map_overlay(items):
                restart_after_overlay = True
                break
            pos = runtime._event_stage_position(items, display_name)
            if pos and runtime._event_stage_marker_reliable(pos):
                return path, items, pos
            if pos:
                moved = _recenter_swipe(runtime, pos, swipe_y)
                if moved is False:
                    runtime.log(
                        f"❌ [V45卡片] {display_name}边缘回正滑动被拒绝",
                        "ERROR",
                    )
                    return None, [], None
                if moved is not None:
                    runtime.wait(1.5)
                    centered_path = runtime.shot(
                        f"dp_v45_recenter_{display_name}_{overlay_round}_{attempt}"
                    )
                    centered_items = runtime.ocr(centered_path)
                    centered_pos = runtime._event_stage_position(
                        centered_items, display_name
                    )
                    if (
                        centered_pos
                        and runtime._event_stage_marker_reliable(centered_pos)
                    ):
                        runtime.log(
                            f"  [V45卡片] {display_name}边缘文字已回正并二次OCR确认 "
                            f"@{centered_pos}"
                        )
                        return centered_path, centered_items, centered_pos
                    runtime.log(
                        f"  [V45卡片] {display_name}回正后仍未形成可点节点，继续有界扫描",
                        "WARN",
                    )
            if attempt < 23:
                if runtime.swipe(*forward_swipe) is False:
                    runtime.log(
                        "  [V45卡片] 前向扫描滑动失败，拒绝继续假扫描",
                        "ERROR",
                    )
                    return None, [], None
                runtime.wait(1.5)
        if restart_after_overlay:
            continue
        return None, [], None
    return None, [], None


def install(runtime):
    if getattr(runtime, "_dp_ds_result_navigation_v45_installed", False):
        return runtime
    v44.install(runtime)
    original_state = runtime.get_state
    original_badges = runtime._victory_three_star_status
    original_verify = runtime.verify_event_stage_cleared
    original_main = runtime.goto_main_menu
    original_locate = runtime._locate_event_stage

    def get_state():
        state = original_state()
        if state != "unknown":
            return state
        page = runtime.shot("dp_v45_ds_result_probe")
        stage = _ds_result_stage(runtime.ocr(page))
        if stage:
            runtime._dp_v45_last_ds_result_stage = stage
            runtime.log(f"  [V45结算] 识别{stage}逐影集趣‘游玩结束’页")
            return "victory"
        return state

    def victory_three_star_status(image_path):
        result = original_badges(image_path)
        if result.get("perfect"):
            return result
        stage = _ds_result_stage(runtime.ocr(image_path))
        if not stage:
            return result
        runtime._dp_v45_last_ds_result_stage = stage
        runtime.log(
            f"  [V45结算] {stage}无标准三星槽；‘游玩结束’仅作本局完成直接证据"
        )
        # The caller's ``perfect`` branch is the only path that proceeds to a
        # map readback.  DS has no normal badge geometry, so this value means
        # "receipt accepted", not fabricated three-star pixels.
        return {
            "lit": 3,
            "ratios": [],
            "perfect": True,
            "receipt": "ds_finished_no_star_geometry",
        }

    def verify_event_stage_cleared(event, display_name):
        is_ds = re.fullmatch(r"DS-\d+", str(display_name or "").upper())
        if (
            str((event or {}).get("name") or "") != v38.EVENT_NAME
            or not is_ds
            or getattr(runtime, "_dp_v45_last_ds_result_stage", "") != display_name
        ):
            return original_verify(event, display_name)
        page = runtime.shot(f"dp_v45_map_receipt_{display_name}")
        items = runtime.ocr(page)
        if not _is_dp_ds_card_map(items, event=event):
            runtime.log(
                f"❌ [V45结算] {display_name}已有‘游玩结束’证据，"
                "但未回读到真实DP/DS卡片地图",
                "ERROR",
            )
            return None, None
        runtime._dp_v45_last_ds_result_stage = ""
        runtime.log(
            f"  [V45结算] {display_name}‘游玩结束’直接证据 + "
            "DP/DS卡片地图回读闭环"
        )
        return True, True

    def goto_main_menu(*args, **kwargs):
        page = runtime.shot("dp_v45_main_escape_probe")
        items = runtime.ocr(page)
        stage = _ds_result_stage(items)
        if stage:
            runtime._dp_v45_last_ds_result_stage = stage
            runtime.tap(*runtime.POS_DISMISS)
            runtime.wait(3)
            map_page = runtime.shot("dp_v45_main_escape_map")
            map_items = runtime.ocr(map_page)
            if _is_dp_ds_card_map(map_items, event=runtime.get_active_event()):
                runtime.log(
                    f"  [V45日常交接] 已关闭{stage}‘游玩结束’并确认卡片地图"
                )
            else:
                runtime.log(
                    f"  [V45日常交接] 已关闭{stage}结算，后续交由原回主界面链识别",
                    "WARN",
                )
        return original_main(*args, **kwargs)

    def locate_event_stage(display_name, event=None):
        if (
            str((event or {}).get("name") or "") == v38.EVENT_NAME
            and re.fullmatch(r"DS-\d+", str(display_name or "").upper())
        ):
            return _locate_ds_stage(runtime, display_name, event=event)
        return original_locate(display_name, event=event)

    runtime.get_state = get_state
    runtime._victory_three_star_status = victory_three_star_status
    runtime.verify_event_stage_cleared = verify_event_stage_cleared
    runtime.goto_main_menu = goto_main_menu
    runtime._locate_event_stage = locate_event_stage
    runtime._dp_ds_result_navigation_v45_installed = True
    runtime.log("  [V45] DS游玩结束、卡片地图回读与边缘回正已安装")
    return runtime

