"""SR-specific priority gate: clear an unlocked special route before farming."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

from event_lobby_recovery_v1 import is_sr_event_lobby, sr_special_route_locked


def discover_special_stages(maa_root, prefix="SR"):
    """Return only special combat stages backed by current MaaCore maps."""
    root = Path(maa_root) / "resource"
    overview_path = root / "Arknights-Tile-Pos" / "overview.json"
    try:
        overview = json.loads(overview_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return []
    rows = []
    pattern = re.compile(re.escape(prefix) + r"-EX-(\d+)$")
    for value in overview.values():
        code = str(value.get("code") or "")
        match = pattern.fullmatch(code)
        if not match:
            continue
        filename = str(value.get("filename") or "")
        internal = value.get("stageId")
        tile = (root / "Arknights-Tile-Pos" / filename).resolve()
        if not filename or not internal or not tile.is_file():
            continue
        rows.append(
            {
                "display": code,
                "internal": internal,
                "modes": ["normal", "challenge"],
                "_order": int(match.group(1)),
            }
        )
    rows.sort(key=lambda row: row.pop("_order"))
    return rows


def _record(app, status, **extra):
    target = app._RUN_SUMMARY.setdefault("event", {}).setdefault("special_route", {})
    target.update(status=status, **extra)
    return target


def observe_special_route(app, event):
    """Open the real SR lobby and classify locked/unlocked without guessing time."""
    if not app.goto_event_map(event):
        _record(app, "unverified", detail="无法从当前界面确认月行水上活动地图")
        return "unverified"
    app.back()
    app.wait(4)
    path = app.shot("sr_special_route_priority")
    items = app.ocr(path)
    text = " ".join(str(value) for value, _x, _y in items)
    if not is_sr_event_lobby(text):
        _record(app, "unverified", detail="返回后未确认月行水上活动大厅", evidence=path)
        return "unverified"
    if sr_special_route_locked(text):
        _record(app, "locked", detail="实机仍显示9月11日16:00:00后开启", evidence=path)
        app.goto_main_menu()
        return "locked"
    _record(app, "unlocked", detail="实机活动大厅未再显示锁定时间", evidence=path)
    app.goto_main_menu()
    return "unlocked"


def install(app):
    """Wrap farm preparation so an unlocked special route cannot be skipped."""
    original = app._configure_new_event_farm_from_live_inventory
    if getattr(original, "_sr_special_priority_v1", False):
        return original

    def priority_wrapper(event):
        if str((event or {}).get("stage_prefix") or "").upper() != "SR":
            return original(event)
        state = observe_special_route(app, event)
        if state == "unverified":
            app._block_stamina_flow(
                "特殊路线锁定状态未通过实机大厅确认",
                source="sr_special_route_priority",
            )
            return False
        if state == "locked":
            app.log("  [特殊关优先] 实机仍锁定，允许继续普通活动材料关")
            return original(event)

        stages = discover_special_stages(app._maa_install_root(), "SR")
        if not stages:
            _record(
                app,
                "unlocked_maps_pending",
                detail="特殊路线已开放，但当前MaaCore尚无SR-EX地图；禁止越过特殊关刷材料",
            )
            app._block_stamina_flow(
                "特殊路线已开放但MaaCore地图尚未更新",
                source="sr_special_route_priority",
            )
            return False

        special_event = deepcopy(event)
        special_event["stages"] = stages
        special_event["tutorial_stages"] = []
        special_event["prerequisite_stages"] = []
        special_event["first_clear_modes"] = ["normal", "challenge"]
        special_event.setdefault("section_keywords", {})["ex"] = [
            "月行水上",
            "SUR LA LUNE",
        ]
        _record(app, "clearing", stages=[row["display"] for row in stages])
        result = app.mode_event_first_clear(special_event)
        if result is not True:
            _record(app, "incomplete", result=str(result))
            app._block_stamina_flow(
                "特殊路线未全部完成，禁止先刷普通材料关",
                source="sr_special_route_priority",
            )
            return False
        _record(app, "completed", stages=[row["display"] for row in stages])
        app.log("✅ 特殊路线当前全部普通/突袭已闭环，开始普通活动材料刷取")
        return original(event)

    priority_wrapper._sr_special_priority_v1 = True
    priority_wrapper._sr_special_priority_original = original
    app._configure_new_event_farm_from_live_inventory = priority_wrapper
    return priority_wrapper

