"""Finite composition of existing Sami capabilities, not a new game strategy.

The caller owns the ready game, recording, exclusive control and cleanup.
This module never boots a game, runs daily/full/main, creates a schedule or
starts a second exploration. Injected gates are real caller checks, not a new
permission system. Unknown existing-service results remain partial.
"""
from copy import deepcopy
from datetime import datetime, timezone
from contextlib import nullcontext
from unittest.mock import patch


def existing_exploration_boundary(app, resume):
    """MAA starts_count limits NEW starts, not a suspended run's continuation.

    v6.20.1 RoguelikeTask.cpp sets StartExplore's pre-action times limit;
    the installed base task routes exceededNext to the stop plugin. Keep the
    mature controller/settlement parser, changing only this call's Core params.
    """
    if not resume:
        return nullcontext()
    original = app._roguelike_core_params
    def params(*args, **kwargs):
        value = original(*args, **kwargs)
        if value.get('theme') != 'Sami':
            raise ValueError('resume-only adapter is Sami-specific')
        return dict(value, starts_count=0, investment_enabled=False)
    return patch.object(app, '_roguelike_core_params', params)


def _reward_changed(row):
    before, after = row.get("pending_before"), row.get("pending_after")
    # A failed return-to-home does not undo rewards already received.
    return (type(before) is int and type(after) is int
            and 0 <= after < before)


def _culture_changed(row):
    for item in row.get("upgrades", []):
        if (item.get('ok') is True and item.get('terminal_complete') is True
                and item.get('effect_basis') == 'same_node_cost_and_full_research_terminal'
                and type(item.get('progress_before')) is int and item['progress_before'] < 43
                and item.get('progress_after') == 43
                and type(item.get('verified_upgrade_cost')) is int and item['verified_upgrade_cost'] > 0
                and item.get('before_screenshot') and item.get('after_screenshot')):
            return True
        values = [item.get(key) for key in (
            "progress_before", "progress_after", "points_before", "points_after")]
        if (item.get("ok") is True and all(type(value) is int for value in values)
                and values[1] > values[0] and 0 <= values[3] < values[2]):
            return True
    return False


def run_once(*, app, sami, ready, recording, deadline, save,
             needs_exploration, clock=None):
    """Call the old single-run, reward and culture services exactly once/phase.

    No implicit startup or cleanup: in particular, do not call the old looping
    supervisor's run/main/cleanup. The real caller must preserve process-query
    restrictions and prove target recording BEFORE any game input is enabled.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    if deadline.tzinfo is None:
        raise ValueError("absolute timezone-aware stop boundary required")
    state = {"version": "sami-demo-once-v1", "theme": "Sami",
             "status": "preparing", "explorations_started": 0,
             "input_phase_started": False,
             "max_explorations": 1, "services": [],
             "demonstrated": {"exploration": False, "rewards": False, "culture": False},
             "next_exploration_allowed": False}

    def emit(status, reason=None):
        state.update(status=status, reason=reason)
        save(state)
        return state

    def require_ready():
        if clock() >= deadline:
            return "deadline_before_next_action"
        if ready() is not True:
            return "caller_environment_or_exclusivity_unverified"
        if recording() is not True:
            return "target_recording_growth_or_game_frame_unverified"
        return None

    def progress(phase):
        for name, method, changed in (
            ("rewards", sami.service_expedition_records, _reward_changed),
            ("culture", sami.service_culture, _culture_changed),
        ):
            problem = require_ready()
            if problem:
                return problem
            result = method()
            state["services"].append({"phase": phase, "kind": name, "result": result,
                                      "observed_at": clock().isoformat()})
            state["demonstrated"][name] |= changed(result)
            save(state)
            if (phase == 'startup' and name == 'culture'
                    and result.get('reason') == 'culture_locked_by_active_exploration'):
                # A real game lock is not an OCR fault and does not authorize
                # abandoning this run. Return to its home, resume it once, and
                # defer upgrades until natural settlement.
                problem = require_ready()
                if problem:
                    return problem
                home = sami.establish_sami_home()
                result['deferred_until_settlement'] = True
                result['resume_home'] = home
                result['home_confirmed_after'] = home.get('ok') is True
                state['resume_existing_exploration'] = True
                save(state)
                if home.get('ok') is not True:
                    return 'active_exploration_home_unverified'
                continue
            if result.get("ok") is not True or result.get("home_confirmed_after") is not True:
                return f"{phase}_{name}_unverified"
        return None

    try:
        problem = require_ready()
        if problem:
            return emit("blocked_before_input", problem)
        state["input_phase_started"] = True
        emit("navigating")
        nav = sami.establish_sami_home()
        state["navigation"] = nav
        if nav.get("ok") is not True:
            return emit("partial", "sami_home_unverified")
        problem = progress("startup")
        if problem:
            return emit("partial", problem)
        # The caller decides from THIS invocation's live service results and
        # the user's remaining goal. Never load a historical checkpoint here.
        needed = needs_exploration(deepcopy(state["services"]))
        state["exploration_needed"] = needed
        if needed is False:
            return emit("completed_existing_progress_only", "no_remaining_exploration_goal")
        if needed is not True:
            return emit("partial", "remaining_exploration_goal_unverified")
        problem = require_ready()
        if problem:
            return emit("partial", problem)
        seconds_left = int((deadline - clock()).total_seconds())
        if seconds_left <= 60:
            return emit("partial", "insufficient_time_before_stop_boundary")
        state["explorations_started"] = 1
        emit("exploring")
        app._RUN_SUMMARY.pop("roguelike", None)
        # Same core/formation and native one-start limit as the existing route.
        resume = state.get('resume_existing_exploration') is True
        state['new_starts_allowed'] = 0 if resume else 1
        with existing_exploration_boundary(app, resume):
            state["mode_result"] = app.mode_roguelike(
                theme="sami", difficulty=2147483647, starts_count=1,
                max_tutorial_recoveries=0, core_char="维什戴尔",
                squad="指挥分队", roles="稳扎稳打", mode="Exp", use_foldartal=False,
                run_timeout=seconds_left - 60)
        state["roguelike"] = dict(app._RUN_SUMMARY.get("roguelike", {}))
        # A technical exit is not a natural end: do not use settlement clicks
        # to try to recover an exploration which may still be in progress.
        natural = state["roguelike"].get("status") in {
            "exploration_failed", "game_pass_confirmed"}
        if not natural:
            return emit("partial", "exploration_terminal_unverified")
        # This is an observation/service boundary, not another battle attempt.
        problem = require_ready()
        if problem:
            return emit("partial", problem)
        settled = sami.drain_safe_settlement()
        state["settlement"] = settled
        if settled.get("ok") is not True:
            return emit("partial", "natural_settlement_unverified")
        state["demonstrated"]["exploration"] = state["roguelike"].get("status") in {
            "exploration_failed", "game_pass_confirmed"}
        problem = progress("after_settlement")
        if problem:
            return emit("partial", problem)
        all_shown = all(state["demonstrated"].values())
        return emit("completed" if all_shown else "completed_with_unshown_effects",
                    "one_exploration_finished_no_restart" if all_shown else
                    "one_exploration_finished_no_extra_run_for_missing_reward_or_points")
    except Exception as exc:
        # Never silently restart or stop another controller after an exception.
        state["error"] = {"type": type(exc).__name__, "message": str(exc)}
        return emit("partial", "existing_service_exception")
