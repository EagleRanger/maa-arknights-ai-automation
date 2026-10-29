"""SR special-route gate that always runs before the ordinary farm branch.

The Moon-on-Water EX map is a separate, irregular lobby entry.  MAA does not
navigate it in multi-job mode, but its own announcement explicitly supports
the normal single-job flow once the game has already reached formation.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re

from event_lobby_recovery_v1 import is_sr_event_lobby, sr_special_route_locked


SPECIAL_UNLOCK_RE = re.compile(
    r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?后开启"
)


def extract_unlock_at(text, *, year=None, tzinfo=None):
    """Read the lobby's explicit unlock time; return None instead of guessing."""
    compact = "".join(str(text or "").split())
    match = SPECIAL_UNLOCK_RE.search(compact)
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


def read_maa_special_capability(maa_root):
    """Classify MAA's current SR-EX notice without treating navigation as combat."""
    notice = Path(maa_root) / "cache" / "announcement.md"
    try:
        text = notice.read_text(encoding="utf-8-sig")
    except OSError:
        return {"status": "unverified", "evidence": str(notice)}
    compact = "".join(text.split())
    sr_notice = "SR-EX" in compact and "不适配多作业模式" in compact
    single_job = all(
        marker in compact
        for marker in ("手动选关", "开始行动", "编队界面", "启动MAA")
    )
    if sr_notice and single_job:
        return {
            "status": "manual_navigation_single_job_supported",
            "evidence": str(notice),
        }
    if sr_notice:
        return {"status": "multi_job_unsupported", "evidence": str(notice)}
    return {"status": "unverified", "evidence": str(notice)}


def _state_path(app):
    base = Path(getattr(app, "BASE", Path(__file__).resolve().parent))
    return base / "outputs" / "sr_special_route_state.json"


def _load_state(app):
    try:
        value = json.loads(_state_path(app).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_state(app, **updates):
    path = _state_path(app)
    value = _load_state(app)
    value.update(updates, updated_at=datetime.now().astimezone().isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _record(app, status, **extra):
    target = app._RUN_SUMMARY.setdefault("event", {}).setdefault("special_route", {})
    target.update(status=status, **extra)
    return target


def observe_special_route(app, event, *, now=None):
    """Use cached future time when safe; otherwise inspect the real SR lobby."""
    now = now or datetime.now().astimezone()
    cached = _load_state(app)
    raw_unlock = cached.get("unlock_at")
    if raw_unlock:
        try:
            unlock_at = datetime.fromisoformat(raw_unlock)
        except ValueError:
            unlock_at = None
        if unlock_at and now < unlock_at:
            _record(
                app,
                "locked_cached",
                unlock_at=unlock_at.isoformat(),
                evidence=cached.get("evidence"),
            )
            return "locked"

    if not app.goto_event_map(event):
        _record(app, "unverified", detail="无法从当前界面确认月行水上活动地图")
        return "unverified"
    app.back()
    app.wait(4)
    path = app.shot("sr_special_route_priority_v2")
    items = app.ocr(path)
    text = " ".join(str(value) for value, _x, _y in items)
    if not is_sr_event_lobby(text):
        _record(app, "unverified", detail="返回后未确认月行水上活动大厅", evidence=path)
        return "unverified"

    unlock_at = extract_unlock_at(text, year=now.year, tzinfo=now.tzinfo)
    if sr_special_route_locked(text):
        state_path = _save_state(
            app,
            status="locked",
            unlock_at=unlock_at.isoformat() if unlock_at else None,
            evidence=path,
        )
        _record(
            app,
            "locked",
            unlock_at=unlock_at.isoformat() if unlock_at else None,
            evidence=path,
            state_file=state_path,
        )
        app.goto_main_menu()
        return "locked"

    state_path = _save_state(app, status="unlocked", unlock_at=raw_unlock, evidence=path)
    _record(app, "unlocked", evidence=path, state_file=state_path)
    app.goto_main_menu()
    return "unlocked"


def special_stages():
    """The live lobby and current copilot job identify act54side EX-1..8."""
    return [
        {
            "display": f"SR-EX-{index}",
            "internal": f"act54side_ex{index:02d}",
            "challenge_internal": f"act54side_ex{index:02d}#f#",
            "modes": ["normal", "challenge"],
        }
        for index in range(1, 9)
    ]


def _special_event(event):
    value = deepcopy(event)
    value["stages"] = special_stages()
    value["tutorial_stages"] = []
    value["prerequisite_stages"] = []
    value["story_stages"] = []
    value["first_clear_modes"] = ["normal", "challenge"]
    value["combat_keywords"] = ["殡仪堂", "疗仪堂"]
    value.setdefault("section_keywords", {})["ex"] = ["殡仪堂", "疗仪堂"]
    return value


def enforce_special_priority(app, event, *, now=None):
    """Return True only when ordinary SR work may proceed."""
    state = observe_special_route(app, event, now=now)
    if state == "unverified":
        app._block_stamina_flow(
            "特殊路线锁定状态未通过实机大厅确认",
            source="sr_special_route_priority_v2",
        )
        return False
    if state == "locked":
        app.log("  [特殊关优先] 尚未到实机公告开放时间，允许继续普通活动流程")
        return True

    capability = read_maa_special_capability(app._maa_install_root())
    _record(app, "unlocked", maa_capability=capability)
    if capability["status"] != "manual_navigation_single_job_supported":
        app._block_stamina_flow(
            "SR-EX已开放，但MAA当前能力提示未确认单作业执行路径",
            source="sr_special_route_priority_v2",
        )
        return False

    special = _special_event(event)
    _record(
        app,
        "clearing",
        stages=[stage["display"] for stage in special["stages"]],
        navigation="game_select_stage_then_start_action_then_single_MAA_job",
        maa_capability=capability,
    )
    result = app.mode_event_first_clear(special)
    if result is not True:
        _record(app, "incomplete", result=str(result), maa_capability=capability)
        app._block_stamina_flow(
            "SR-EX普通/突袭尚未全部闭环，禁止先刷普通材料关",
            source="sr_special_route_priority_v2",
        )
        return False
    _record(
        app,
        "completed",
        stages=[stage["display"] for stage in special["stages"]],
        maa_capability=capability,
    )
    app.log("✅ SR-EX当前全部普通/突袭已闭环，才允许普通活动材料刷取")
    return True


def install(app):
    """Wrap the whole event branch, before preconfigured farm_stage is consulted."""
    original = app._run_full_event_steps
    if getattr(original, "_sr_special_priority_v2", False):
        return original

    def priority_wrapper(event):
        if str((event or {}).get("stage_prefix") or "").upper() != "SR":
            return original(event)
        if not enforce_special_priority(app, event):
            return False, True
        return original(event)

    priority_wrapper._sr_special_priority_v2 = True
    priority_wrapper._sr_special_priority_original = original
    app._run_full_event_steps = priority_wrapper
    return priority_wrapper

