"""Close every 1-7 route with exact single-battle and live-sanity proof.

V58-V60 only wrapped ``mode_orundum_rock_fallback``.  The accepted V51
continuity route calls ``mode_resource('1-7', 99)`` directly, so its completed
MAA chain could still be mistaken for exhaustion when the native series
selector stopped early.  V4 protects both entry points and uses one explicitly
configured battle per MAA invocation for the bounded tail.
"""

from __future__ import annotations

from datetime import datetime


STAGE = "1-7"
STAGE_COST = 6
MAX_EXACT_SINGLE_BATTLES = 37


def _verified_value(observation):
    if not isinstance(observation, dict) or observation.get("verified") is not True:
        return None
    value = observation.get("value")
    return value if isinstance(value, int) else None


def _configure_exact_single(runtime, cfg):
    runtime._configure_fight(cfg, STAGE, 1)
    fight = next(
        item for item in runtime._task_queue(cfg) if item.get("TaskType") == "Fight"
    )
    fight.update({
        "StagePlan": [STAGE],
        "Series": 1,
        "HideSeries": True,
        "UseMedicine": False,
        "UseExpiringMedicine": False,
        "MedicineCount": 0,
        "UseStone": False,
        "StoneCount": 0,
    })
    return fight


def _merge_handoff(runtime, prior, tail_runs, start_value, final_value):
    prior = dict(prior or {})
    prior_runs = int(prior.get("runs", 0) or 0)
    prior_cost = int(prior.get("sanity_consumed", 0) or 0)
    payload = {
        "game_day": runtime._game_day_key(),
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "stage": STAGE,
        "runs": prior_runs + tail_runs,
        "sanity_cost_each": STAGE_COST,
        "sanity_consumed": prior_cost + tail_runs * STAGE_COST,
        "series_batches": list(prior.get("series_batches") or []) + [1] * tail_runs,
        "sanity_first": (
            prior.get("sanity_first")
            if prior.get("sanity_first") is not None
            else start_value
        ),
        "sanity_last": final_value,
        "evidence": (
            "既有FightTimes + V63逐次单场FightTimes + 每场实时理智下降 + "
            "最终实时理智低于1-7消耗"
        ),
    }
    runtime._atomic_write_json(runtime.FIGHT_HANDOFF_FILE, payload)
    return payload


def drain_exact_single_battles(runtime, prior_handoff=None, summary=None):
    """Use existing sanity only and prove the resulting balance is below six."""

    summary = summary if isinstance(summary, dict) else runtime._RUN_SUMMARY.setdefault(
        "remaining_sanity_use", {}
    )
    summary.update({
        "status": "verifying_exhaustion_exact_single",
        "stage": STAGE,
        "purpose": summary.get("purpose") or "搓合成玉所需固源岩",
        "medicine": False,
        "originium": False,
        "acceptance": "each_exact_single_has_fighttimes_and_live_drop; final_below_6",
    })
    before = runtime._capture_stamina_observation("v63_exact_single_before", navigate=True)
    start_value = _verified_value(before)
    if start_value is None:
        summary.update(status="failed_exhaustion_unverified", detail="单场收尾开始前实时理智未确认")
        return False
    if start_value < STAGE_COST:
        summary.update({
            "status": "completed_verified_exhausted",
            "detail": f"实时理智{start_value}/210，低于1-7消耗{STAGE_COST}",
            "final_sanity": start_value,
            "tail_runs": 0,
            "tail_sanity_consumed": 0,
            "tail_rounds": [],
        })
        return True

    prior_handoff = dict(prior_handoff or runtime._load_fight_handoff() or {})
    # Natural recovery can add at most a small amount during this short loop.
    # Two extra rounds cover that without turning the recovery into an open loop.
    round_budget = min(MAX_EXACT_SINGLE_BATTLES, start_value // STAGE_COST + 2)
    current_value = start_value
    rounds = []
    completed = 0

    for round_index in range(1, round_budget + 1):
        if current_value < STAGE_COST:
            break
        runtime.reload_maa_after_config_switch(
            f"V63 1-7逐次单场收尾第{round_index}次，实时理智{current_value}"
        )
        try:
            with runtime.temporary_maa_config(
                lambda cfg: _configure_exact_single(runtime, cfg),
                "仅Fight 1-7一次；Series=1且隐藏多次代理；禁药禁石",
            ):
                if not runtime.run_maa_daily_tasks(enabled_tasks={"Fight"}):
                    raise RuntimeError("MAA单场Fight启动失败")
                result = runtime.wait_maa_complete(
                    timeout=1200,
                    prestarted_boundary=True,
                    active_battle_extension=1200,
                )
                if result is not True:
                    raise RuntimeError(f"MAA单场Fight未确认结束: {result}")
                maa_text = runtime._get_current_maa_run_log()
                evidence = runtime._parse_fight_times_evidence(maa_text) or {}
        except Exception as exc:
            summary.update({
                "status": "failed",
                "detail": f"第{round_index}次单场收尾异常: {exc}",
                "tail_rounds": rounds,
            })
            runtime.log(f"❌ V63 1-7单场收尾异常: {exc}", "ERROR")
            return False

        after = runtime._capture_stamina_observation(
            f"v63_exact_single_after_{round_index}", navigate=True
        )
        after_value = _verified_value(after)
        evidence_runs = int(evidence.get("runs", 0) or 0)
        record = {
            "round": round_index,
            "before": current_value,
            "after": after_value,
            "configured_times": 1,
            "fighttimes_evidence": evidence_runs,
            "runs": 1 if evidence_runs >= 1 else 0,
            "sanity_consumed": STAGE_COST if evidence_runs >= 1 else 0,
        }
        rounds.append(record)
        if evidence_runs < 1 or after_value is None or after_value >= current_value:
            summary.update({
                "status": "failed_no_verified_progress",
                "detail": "单场Fight没有形成FightTimes与实时理智下降闭环",
                "tail_rounds": rounds,
            })
            return False
        completed += 1
        current_value = after_value

    if current_value >= STAGE_COST:
        summary.update({
            "status": "failed_not_exhausted_after_bounded_retries",
            "detail": f"{round_budget}次单场收尾后实时理智仍为{current_value}/210",
            "tail_runs": completed,
            "tail_sanity_consumed": completed * STAGE_COST,
            "tail_rounds": rounds,
        })
        return False

    merged = _merge_handoff(
        runtime, prior_handoff, completed, start_value, current_value
    )
    summary.update({
        "status": "completed_verified_exhausted",
        "detail": f"逐次单场后实时理智{current_value}/210，低于1-7消耗{STAGE_COST}",
        "tail_runs": completed,
        "tail_sanity_consumed": completed * STAGE_COST,
        "actual_runs": int(merged["runs"]),
        "sanity_consumed": int(merged["sanity_consumed"]),
        "final_sanity": current_value,
        "tail_rounds": rounds,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    })
    runtime.log(f"✅ V63理智闭环：新增{completed}次1-7，最终{current_value}/210")
    return True


def _verify_or_drain(runtime, result, summary):
    if result is not True:
        return False
    observation = runtime._capture_stamina_observation(
        "v63_route_final", navigate=True
    )
    value = _verified_value(observation)
    if value is None:
        summary.update(
            status="failed_exhaustion_unverified",
            detail="Fight结束但实时理智未确认；不得报告理智耗尽",
        )
        return False
    if value < STAGE_COST:
        summary.update(
            status="completed_verified_exhausted",
            detail=f"实时理智{value}/210，低于1-7消耗{STAGE_COST}",
            final_sanity=value,
        )
        return True
    runtime.log(
        f"⚠️ 1-7链结束但实时理智仍为{value}/210；进入V63逐次单场收尾",
        "WARN",
    )
    return drain_exact_single_battles(runtime, summary=summary)


def install(runtime):
    if getattr(runtime, "_daily_stamina_exhaustion_v4_installed", False):
        return runtime

    original_resource = runtime.mode_resource
    original_orundum = runtime.mode_orundum_rock_fallback
    original_report = runtime.generate_daily_report

    def verified_resource(*args, **kwargs):
        stage = kwargs.get("stage_code")
        if stage is None and args:
            stage = args[0]
        result = original_resource(*args, **kwargs)
        summary = runtime._RUN_SUMMARY.setdefault("remaining_sanity_use", {})
        if str(stage).upper() != STAGE:
            return result
        return _verify_or_drain(runtime, result, summary)

    def verified_orundum():
        result = original_orundum()
        summary = runtime._RUN_SUMMARY.setdefault("remaining_sanity_use", {})
        return _verify_or_drain(runtime, result, summary)

    def strict_report(*args, **kwargs):
        report = original_report(*args, **kwargs)
        summary = (report.get("run_summary") or {}).get("remaining_sanity_use") or {}
        final_value = report.get("final_stamina")
        if (
            summary.get("stage") == STAGE
            and isinstance(final_value, int)
            and final_value >= STAGE_COST
        ):
            summary.update({
                "status": "failed_not_exhausted",
                "detail": f"最终实时理智{final_value}/210仍可执行1-7，禁止报告完成",
                "final_sanity": final_value,
            })
            report["workflow_completed"] = False
            report["overall_status"] = "partial"
            issue = f"1-7理智未耗尽: {final_value}/210"
            if issue not in report.setdefault("domain_issues", []):
                report["domain_issues"].append(issue)
            if issue not in report.setdefault("unspent_stamina", []):
                report["unspent_stamina"].append(issue)
        return report

    verified_resource._daily_stamina_exhaustion_v4 = True
    verified_resource._wrapped = original_resource
    verified_orundum._daily_stamina_exhaustion_v4 = True
    verified_orundum._wrapped = original_orundum
    strict_report._daily_stamina_exhaustion_v4 = True
    strict_report._wrapped = original_report
    runtime.mode_resource = verified_resource
    runtime.mode_orundum_rock_fallback = verified_orundum
    runtime.generate_daily_report = strict_report
    runtime._daily_stamina_exhaustion_v4_installed = True
    return runtime
