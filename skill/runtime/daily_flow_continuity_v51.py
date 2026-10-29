"""Continue an already-decided daily flow without asking for the same choice again.

This adapter is intentionally narrow.  It does not turn a manual declaration
into stage-clear evidence.  It only chooses the already-authorized ordinary
stamina route after the matching zero-sanity event and after weekly
annihilation has been verified complete.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESOLUTION_PATH = ROOT / "config" / "current_event_resolution_20260926.json"
WEEKLY_COMPLETE = {"completed_weekly", "skipped_weekly_complete"}


def load_resolution(path=RESOLUTION_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "event_name", "resolution", "repeat_stamina_reward", "stamina_stage",
        "existing_sanity_only", "use_medicine", "use_originium",
        "requires_weekly_annihilation_complete",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"current event resolution missing fields: {missing}")
    if data["resolution"] != "user_manually_completed_all_stages":
        raise ValueError("current event resolution is not a manual completion decision")
    if data["repeat_stamina_reward"] is not False:
        raise ValueError("repeat stamina reward must be explicitly false")
    if data["stamina_stage"] != "1-7":
        raise ValueError("this adapter only accepts the explicit 1-7 decision")
    if not data["existing_sanity_only"] or data["use_medicine"] or data["use_originium"]:
        raise ValueError("resource boundary must remain existing-sanity-only")
    return data


def _compact(value):
    return str(value or "").replace(" ", "")


def may_continue(event, annihilation_status, resolution):
    if _compact((event or {}).get("name")) != _compact(resolution.get("event_name")):
        return False
    if resolution.get("requires_weekly_annihilation_complete") is True:
        return annihilation_status in WEEKLY_COMPLETE
    return True


def install(runtime, *, resolution_path=RESOLUTION_PATH):
    if getattr(runtime, "_daily_flow_continuity_v51_installed", False):
        return runtime

    resolution = load_resolution(resolution_path)
    original_event_steps = runtime._run_full_event_steps
    original_record_request = runtime._record_decision_request

    def record_request_once(action, reason, goal_ids=None, proposed_change=None):
        for existing in runtime._RUN_SUMMARY.get("decision_requests") or []:
            if (
                existing.get("action") == action
                and existing.get("reason") == reason
                and existing.get("proposed_change") == proposed_change
            ):
                return existing
        return original_record_request(action, reason, goal_ids, proposed_change)

    def event_steps(event):
        annihilation_status = (runtime._RUN_SUMMARY.get("annihilation") or {}).get("status")
        if not may_continue(event, annihilation_status, resolution):
            return original_event_steps(event)

        run = runtime._RUN_SUMMARY.setdefault("event", {})
        run.update({
            "name": resolution["event_name"],
            "status": "manual_completion_declared_resource_continuation",
            "completion_source": "user_declaration",
            "script_verified_all_stages": False,
            "repeat_stamina_reward": False,
            "stamina_diversion_forbidden": False,
            "resource_stage": resolution["stamina_stage"],
        })
        runtime._RUN_SUMMARY["remaining_sanity_use"] = {
            "status": "running",
            "stage": resolution["stamina_stage"],
            "purpose": resolution.get("stamina_purpose"),
            "medicine": False,
            "originium": False,
            "source": "current_event_resolution_20260926",
        }
        runtime.log(
            "  [V51] 当前零理智活动已有用户明确收口；周剿灭已完成，"
            "直接用现有理智执行1-7，不重复活动流程"
        )
        if runtime.mode_resource(stage_code=resolution["stamina_stage"], times=99) is not True:
            runtime._RUN_SUMMARY["remaining_sanity_use"].update(
                status="failed", detail="1-7未确认完成；未改刷其他关卡"
            )
            return False, True
        # V24 freezes an earlier same-day five-chain only when no later real
        # stamina battle is known.  ``mode_resource`` persists Fight evidence
        # but the legacy path did not update this in-process boundary, so an
        # earlier five-chain was incorrectly reused after 1-7.  Record the
        # conservative completion boundary immediately after MAA settles.
        runtime._CURRENT_RUN_LAST_STAMINA_BATTLE_AT = datetime.now()
        runtime._RUN_SUMMARY["remaining_sanity_use"].update(
            status="completed", detail="1-7已运行至现有理智不足"
        )
        return True, True

    runtime._record_decision_request = record_request_once
    runtime._run_full_event_steps = event_steps
    runtime._daily_flow_continuity_v51_installed = True
    runtime._daily_flow_continuity_v51_resolution = deepcopy(resolution)
    return runtime
