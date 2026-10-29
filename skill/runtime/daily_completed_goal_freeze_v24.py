"""Prevent same-game-day completed daily chains from being executed again.

V23 correctly separated the final five-chain result from the overall workflow,
but the inherited final-tail dispatcher still started a fresh StartUp/Infrast
queue.  The old recovery helper inspected only the last StartUp segment, so a
new partial queue hid an earlier complete queue from the same game day.

V24 scans every queue segment in the current and rotated MAA GUI logs.  It may
freeze the final daily goal only when one complete five-chain queue is newer
than the latest real sanity-spending Fight.  Otherwise the original final-tail
dispatcher remains authoritative.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path


DAILY_CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")
START_RE = re.compile(r"开始任务:\s*开始唤醒|Start Task Chain:\s*StartUp", re.I)
QUEUE_END_RE = re.compile(r"任务已全部完成|All Tasks Completed", re.I)
CHAIN_DONE_RE = {
    "StartUp": re.compile(r"完成任务:\s*开始唤醒|Completed Task Chain:\s*StartUp", re.I),
    "Infrast": re.compile(r"完成任务:\s*基建换班|Completed Task Chain:\s*Infrast", re.I),
    "Recruit": re.compile(r"完成任务:\s*自动公招|Completed Task Chain:\s*Recruit", re.I),
    "Mall": re.compile(r"完成任务:\s*信用收支|Completed Task Chain:\s*Mall", re.I),
    "Award": re.compile(r"完成任务:\s*领取奖励|Completed Task Chain:\s*Award", re.I),
}
STAMP_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _default_game_day(value: datetime) -> str:
    return (value - timedelta(hours=4)).date().isoformat()


def completed_daily_segments(text, *, source="", now=None, game_day_key=None):
    """Return every complete five-chain queue in the current game day."""

    text = text or ""
    now = now or datetime.now()
    game_day_key = game_day_key or _default_game_day
    starts = [match.start() for match in START_RE.finditer(text)]
    results = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        segment = text[start:end]
        queue_end = QUEUE_END_RE.search(segment)
        if queue_end is None:
            continue
        line_end = segment.find("\n", queue_end.end())
        closed = segment if line_end < 0 else segment[: line_end + 1]
        if any(pattern.search(closed) is None for pattern in CHAIN_DONE_RE.values()):
            continue
        end_line_start = closed.rfind("\n", 0, queue_end.start()) + 1
        end_line_end = closed.find("\n", queue_end.end())
        end_line = closed[end_line_start:] if end_line_end < 0 else closed[end_line_start:end_line_end]
        stamp = STAMP_RE.search(end_line)
        if stamp is None:
            continue
        try:
            completed_at = datetime.fromisoformat(stamp.group(1))
        except ValueError:
            continue
        if completed_at > now or game_day_key(completed_at) != game_day_key(now):
            continue
        results.append(
            {
                "completed_at": completed_at,
                "chains": DAILY_CHAINS,
                "source": str(source),
                "segment_sha256": hashlib.sha256(closed.encode("utf-8")).hexdigest().upper(),
            }
        )
    return results


def _gui_log_paths(runtime):
    primary = Path(runtime.MAA_GUI_LOG)
    paths = [primary]
    for candidate in (primary.with_name("gui.bak.log"), primary.with_suffix(".bak.log")):
        if candidate not in paths:
            paths.append(candidate)
    return paths


def find_same_day_completed_goal(runtime, *, now=None):
    """Find a completed daily queue not invalidated by a later real Fight."""

    now = now or datetime.now()
    game_day_key = getattr(runtime, "_game_day_key", _default_game_day)
    candidates = []
    latest_fight = getattr(runtime, "_CURRENT_RUN_LAST_STAMINA_BATTLE_AT", None)
    inspected = []
    for path in _gui_log_paths(runtime):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        inspected.append(str(path))
        candidates.extend(
            completed_daily_segments(
                text, source=path, now=now, game_day_key=game_day_key
            )
        )
        try:
            observed = runtime._latest_completed_fight_at_from_gui_log(text, now=now)
        except (AttributeError, TypeError, ValueError):
            observed = None
        if observed is not None:
            latest_fight = max(latest_fight, observed) if latest_fight else observed

    eligible = [
        item
        for item in candidates
        if latest_fight is None or item["completed_at"] > latest_fight
    ]
    if not eligible:
        return {
            "status": "not_frozen",
            "reason": "no_same_day_complete_after_latest_fight",
            "latest_fight_at": latest_fight.isoformat(timespec="seconds") if latest_fight else None,
            "inspected_logs": inspected,
            "candidate_count": len(candidates),
        }
    chosen = max(eligible, key=lambda item: item["completed_at"])
    return {
        "status": "frozen_same_day_complete",
        "game_day": game_day_key(now),
        "completed_at": chosen["completed_at"].isoformat(timespec="seconds"),
        "latest_fight_at": latest_fight.isoformat(timespec="seconds") if latest_fight else None,
        "chains": list(chosen["chains"]),
        "source": chosen["source"],
        "segment_sha256": chosen["segment_sha256"],
        "inspected_logs": inspected,
        "candidate_count": len(candidates),
        "reentry_prevented": True,
    }


def _synthetic_completed_log(chains):
    lines = []
    for chain in chains:
        lines.append(f'TaskChainStart {{"taskchain":"{chain}"}}\n')
        lines.append(f'TaskChainCompleted {{"taskchain":"{chain}"}}\n')
    lines.append('AllTasksCompleted {"taskchain":"Award"}\n')
    return "".join(lines)


def install(runtime):
    if getattr(runtime, "_daily_completed_goal_freeze_v24_installed", False):
        return runtime
    original = runtime._run_full_final_daily_step

    def guarded_final_daily_step():
        evidence = find_same_day_completed_goal(runtime)
        runtime._RUN_SUMMARY["daily_goal_freeze"] = evidence
        if evidence.get("status") != "frozen_same_day_complete":
            return original()

        runtime._LAST_MAA_RUN_LOG = _synthetic_completed_log(evidence["chains"])
        runtime._RUN_SUMMARY["daily_requested_chains"] = list(evidence["chains"])
        runtime._RUN_SUMMARY["daily_scope_result"] = {
            "complete": True,
            "source": "same_game_day_completed_goal_freeze_v24",
            "completed_at": evidence["completed_at"],
        }
        runtime._RUN_SUMMARY["final_daily_completed"] = True
        receipt = Path(runtime.BASE) / "outputs" / "daily_goal_completion" / (
            evidence["game_day"] + ".json"
        )
        receipt.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(evidence)
        payload["recorded_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        runtime._atomic_write_json(str(receipt), payload)
        runtime._RUN_SUMMARY["daily_goal_freeze"]["receipt"] = str(receipt)
        runtime.log(
            "✅ 本游戏日最终日常五链已有完整队列证据，且其后无真实理智战斗；"
            "冻结完成域，不重复启动StartUp/Infrast/Recruit/Mall/Award"
        )
        return True

    guarded_final_daily_step._daily_completed_goal_freeze_v24 = True
    guarded_final_daily_step._daily_completed_goal_freeze_original = original
    runtime._run_full_final_daily_step = guarded_final_daily_step
    runtime._daily_completed_goal_freeze_v24_installed = True
    runtime.log("  [V24] 同游戏日完成域冻结门已启用")
    return runtime

