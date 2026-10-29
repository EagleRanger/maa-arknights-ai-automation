"""SR special-route production adapter backed by the 2026-09-14 live UI.

V2 established the business order and the single-MAA-job boundary.  V3 keeps
that order, but teaches the frozen runtime that ``要去哪里？ / ASCENT`` is the
SR vertical stage map, and verifies that MaaCore has all 16 normal/challenge
tile entries before the first battle.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

import sr_special_priority_v2 as v2


SPECIAL_ROUTE_KIND = "sr_funeral_hall_vertical"
STAGE_RE = re.compile(r"SR\s*[-—–]?\s*EX\s*[-—–]?\s*(\d+)", re.I)
_RESOURCE_READY_FOR = set()

UNLOCK_TIME_RE = re.compile(
    r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
    r"(?P<hour>\d{1,2})[:：](?P<minute>\d{2})(?:[:：](?P<second>\d{2}))?"
    r"(?:后)?(?:正式)?(?:开启|开放|解锁)"
)


def _compact(text):
    return "".join(str(text or "").split()).upper()


def is_sr_special_hall(text):
    value = _compact(text)
    return "要去哪里" in value and "SR-EX-" in value and (
        "ASCENT" in value or value.count("SR-EX-") >= 1
    )


def is_sr_special_detail(text, display_name=None):
    value = _compact(text)
    if display_name and _compact(display_name) not in value:
        return False
    return "SR-EX-" in value and any(
        marker in value
        for marker in ("开始行动", "代理指挥", "推荐平均等级", "敌人情报", "敌方情报")
    )


def visible_special_stage_positions(items):
    """Return left stage-strip coordinates only; ignore the detail title."""
    found = {}
    for raw, x, y in items or []:
        match = STAGE_RE.search(str(raw or ""))
        if not match or int(x) >= 700:
            continue
        name = f"SR-EX-{int(match.group(1))}"
        # The selected stage can be OCRed twice; the lowest-left label is the
        # reliable hit target used in the live run.
        current = found.get(name)
        if current is None or int(y) > current[1]:
            found[name] = (int(x), int(y))
    return found


def extract_special_unlock_at(text, *, year=None, tzinfo=None):
    """Read the explicit lobby schedule without inferring a missing value."""
    match = UNLOCK_TIME_RE.search("".join(str(text or "").split()))
    if not match:
        return None
    now = datetime.now().astimezone()
    return datetime(
        int(year or now.year),
        int(match.group("month")),
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second") or 0),
        tzinfo=tzinfo or now.tzinfo,
    )


def observe_special_route(app, event, *, now=None):
    """Reuse V2's live probe, then cache every explicit unlock-time wording.

    The first ordinary-stage pass pays for one real lobby scan.  A future
    timestamp suppresses repeat visits until it becomes due.  MAA's notice is
    deliberately not used as availability proof: it describes the single-job
    control path but contains no unlock timestamp.
    """
    now = now or datetime.now().astimezone()
    state = v2.observe_special_route(app, event, now=now)
    if state != "locked":
        return state
    cached = v2._load_state(app)
    if cached.get("unlock_at"):
        return state
    evidence = cached.get("evidence")
    if not evidence:
        return state
    try:
        text = app.ocr_text(evidence)
    except (AttributeError, OSError, TypeError, ValueError):
        return state
    unlock_at = extract_special_unlock_at(text, year=now.year, tzinfo=now.tzinfo)
    if not unlock_at:
        return state
    state_path = v2._save_state(
        app,
        status="locked",
        unlock_at=unlock_at.isoformat(),
        evidence=evidence,
        availability_source="game_lobby_explicit_time",
    )
    v2._record(
        app,
        "locked",
        unlock_at=unlock_at.isoformat(),
        evidence=evidence,
        state_file=state_path,
        next_probe_at=unlock_at.isoformat(),
    )
    return state


def inspect_maa_special_resources(maa_root):
    path = Path(maa_root) / "resource" / "Arknights-Tile-Pos" / "overview.json"
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "unverified", "path": str(path), "detail": str(exc)}
    keys = set(data) if isinstance(data, dict) else set()
    required = []
    for index in range(1, 9):
        required.extend((f"act54side_ex{index:02d}-", f"act54side_ex{index:02d}#f#-"))
    missing = [prefix for prefix in required if not any(key.startswith(prefix) for key in keys)]
    return {
        "status": "ready" if not missing else "missing",
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest().upper(),
        "required": len(required),
        "present": len(required) - len(missing),
        "missing": missing,
    }


def ensure_maa_special_resources(app):
    root = str(app._maa_install_root())
    result = inspect_maa_special_resources(root)
    app._RUN_SUMMARY.setdefault("event", {}).setdefault("special_route", {})[
        "maa_tile_resources"
    ] = result
    if result.get("status") != "ready":
        app._block_stamina_flow(
            "SR-EX地图资源未包含8关普通/突袭共16项；未启动战斗",
            source="sr_special_priority_v3",
        )
        return False
    identity = (root, result["sha256"])
    if identity in _RESOURCE_READY_FOR:
        return True
    if app._maa_task_queue_running():
        app._block_stamina_flow(
            "SR-EX资源已补齐但MAA任务仍在运行，不能在战斗中重载",
            source="sr_special_priority_v3",
        )
        return False
    if app._maa_process_ids() and not app.reload_maa_after_config_switch(
        "SR-EX地图资源校验后重载MaaCore"
    ):
        app._block_stamina_flow(
            "SR-EX资源存在，但空闲MAA重载失败",
            source="sr_special_priority_v3",
        )
        return False
    _RESOURCE_READY_FOR.add(identity)
    return True


def _special_event(event):
    value = v2._special_event(event)
    value["special_route_kind"] = SPECIAL_ROUTE_KIND
    value["section_positions"] = {}
    return value


def _is_special_event(event):
    return (event or {}).get("special_route_kind") == SPECIAL_ROUTE_KIND


def _tap_lobby_special_entry(app, items):
    for keyword in ("殡仪堂", "疗仪堂"):
        pos = app.find_text(items, keyword, exact=False)
        if pos:
            app.tap(*pos)
            app.log(f"  [SR特殊导航] 点击{keyword}入口 @{pos}")
            app.wait(5)
            return True
    return False


def goto_sr_special_hall(app, event, original_goto):
    probe = app.shot("sr_special_hall_probe")
    items = app.ocr(probe)
    text = " ".join(str(item[0]) for item in items if item)
    if is_sr_special_detail(text):
        app.back()
        app.wait(3)
        probe = app.shot("sr_special_hall_after_detail")
        items = app.ocr(probe)
        text = " ".join(str(item[0]) for item in items if item)
    if is_sr_special_hall(text):
        return True
    if _tap_lobby_special_entry(app, items):
        verify = app.shot("sr_special_hall_from_lobby")
        if is_sr_special_hall(app.ocr_text(verify)):
            return True
    # The frozen generic navigator can still reach the event lobby.  Its
    # success result is not accepted until the special map anchors are read.
    original_goto(event)
    verify = app.shot("sr_special_hall_after_generic")
    verify_items = app.ocr(verify)
    verify_text = " ".join(str(item[0]) for item in verify_items if item)
    if is_sr_special_detail(verify_text):
        app.back()
        app.wait(3)
        verify = app.shot("sr_special_hall_after_generic_detail")
        verify_items = app.ocr(verify)
        verify_text = " ".join(str(item[0]) for item in verify_items if item)
    if is_sr_special_hall(verify_text):
        return True
    if _tap_lobby_special_entry(app, verify_items):
        final = app.shot("sr_special_hall_verify")
        if is_sr_special_hall(app.ocr_text(final)):
            return True
    app.log("❌ 未确认进入殡仪堂‘要去哪里？/ASCENT’特殊路线页", "ERROR")
    return False


def locate_sr_special_stage(app, event, display_name, goto_hall):
    if not goto_hall(event):
        return None, [], None
    target_match = STAGE_RE.search(display_name)
    target_number = int(target_match.group(1)) if target_match else 0
    previous_signature = None
    stagnant = 0
    for attempt in range(14):
        path = app.shot(f"sr_special_stage_{display_name}_{attempt}")
        items = app.ocr(path)
        text = " ".join(str(item[0]) for item in items if item)
        if is_sr_special_detail(text):
            app.back()
            app.wait(3)
            continue
        if not is_sr_special_hall(text):
            return None, items, None
        positions = visible_special_stage_positions(items)
        if display_name in positions:
            return path, items, positions[display_name]
        numbers = sorted(int(name.rsplit("-", 1)[1]) for name in positions)
        signature = tuple((name, pos[1]) for name, pos in sorted(positions.items()))
        stagnant = stagnant + 1 if signature == previous_signature else 0
        previous_signature = signature
        if stagnant >= 2:
            break
        if not numbers or target_number > max(numbers):
            # Later SR-EX labels extend above the initial viewport.  Drag the
            # vertical stage strip down in small steps; do not jump to its end.
            app.swipe(650, 330, 650, 690, 500)
        else:
            app.swipe(650, 820, 650, 500, 500)
        app.wait(2)
    app.log(f"❌ 殡仪堂垂直关卡条未定位{display_name}；未盲点", "ERROR")
    return None, [], None


def install_navigation(app):
    if getattr(app, "_sr_special_navigation_v3_installed", False):
        return
    original_goto = app.goto_event_map
    original_section = app._select_event_stage_section
    original_locate = app._locate_event_stage

    def goto_event_map(event=None):
        if _is_special_event(event):
            return goto_sr_special_hall(app, event, original_goto)
        return original_goto(event)

    def select_section(display_name, event=None):
        if _is_special_event(event):
            return goto_event_map(event)
        return original_section(display_name, event=event)

    def locate_stage(display_name, event=None):
        if _is_special_event(event):
            return locate_sr_special_stage(app, event, display_name, goto_event_map)
        return original_locate(display_name, event=event)

    app.goto_event_map = goto_event_map
    app._select_event_stage_section = select_section
    app._locate_event_stage = locate_stage
    app._sr_special_navigation_v3_installed = True


def enforce_special_priority(app, event, *, now=None):
    """Keep the user-approved strict order: unlocked EX before material farm."""
    state = observe_special_route(app, event, now=now)
    if state == "unverified":
        app._block_stamina_flow(
            "特殊路线锁定状态未通过实机大厅确认",
            source="sr_special_priority_v3",
        )
        return False
    if state == "locked":
        app.log("  [特殊关优先] 尚未到实机公告开放时间，允许继续普通活动流程")
        return True
    capability = v2.read_maa_special_capability(app._maa_install_root())
    v2._record(app, "unlocked", maa_capability=capability)
    if capability["status"] != "manual_navigation_single_job_supported":
        app._block_stamina_flow(
            "SR-EX已开放，但MAA当前能力提示未确认单作业执行路径",
            source="sr_special_priority_v3",
        )
        return False
    if not ensure_maa_special_resources(app):
        return False
    special = _special_event(event)
    v2._record(
        app,
        "clearing",
        stages=[stage["display"] for stage in special["stages"]],
        navigation="sr_vertical_strip_to_detail_then_formation_then_single_MAA_job",
        maa_capability=capability,
    )
    result = app.mode_event_first_clear(special)
    if result is not True:
        v2._record(app, "incomplete", result=str(result), maa_capability=capability)
        app._block_stamina_flow(
            "当前已解锁SR-EX普通/突袭尚未闭环，禁止先刷普通材料关",
            source="sr_special_priority_v3",
        )
        return False
    v2._record(
        app,
        "completed",
        stages=[stage["display"] for stage in special["stages"]],
        maa_capability=capability,
    )
    return True


def install(app):
    install_navigation(app)
    original = app._run_full_event_steps
    if getattr(original, "_sr_special_priority_v3", False):
        return original

    def wrapper(event):
        if str((event or {}).get("stage_prefix") or "").upper() != "SR":
            return original(event)
        if not enforce_special_priority(app, event):
            return False, True
        return original(event)

    wrapper._sr_special_priority_v3 = True
    wrapper._sr_special_priority_original = original
    app._run_full_event_steps = wrapper
    return wrapper
