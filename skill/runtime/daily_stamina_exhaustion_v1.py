"""Verified exhaustion of existing sanity after MAA auto-series Fight.

MAA may finish the Fight task chain when its multi-proxy series selector cannot
read the next batch.  A completed task chain therefore is not proof that sanity
is exhausted.  This adapter keeps the fast auto-series first pass, then reads
live sanity and, when needed, finishes with Series=1 until the balance is below
the stage cost.
"""

from __future__ import annotations

from datetime import datetime


STAGE = "1-7"
STAGE_COST = 6
MAX_SINGLE_SERIES_ROUNDS = 3


def _verified_value(observation):
    if not isinstance(observation, dict) or observation.get("verified") is not True:
        return None
    value = observation.get("value")
    return value if isinstance(value, int) else None


def _configure_single_series(runtime, cfg, times=99):
    runtime._configure_fight(cfg, STAGE, times)
    fight = next(item for item in runtime._task_queue(cfg) if item.get("TaskType") == "Fight")
    fight["Series"] = 1
    fight["HideSeries"] = False
    fight["UseMedicine"] = False
    fight["UseStone"] = False
    fight["UseExpiringMedicine"] = False
    fight["MedicineCount"] = 0
    fight["StoneCount"] = 0


def _merge_handoff(runtime, prior, tail, start_value, final_value):
    prior = prior or {}
    total_runs = int(prior.get("runs", 0) or 0) + int(tail.get("runs", 0) or 0)
    total_cost = int(prior.get("sanity_consumed", 0) or 0) + int(tail.get("sanity_cost", 0) or 0)
    payload = {
        "game_day": runtime._game_day_key(),
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "stage": STAGE,
        "runs": total_runs,
        "sanity_cost_each": STAGE_COST,
        "sanity_consumed": total_cost,
        "series_batches": list(prior.get("series_batches") or []) + list(tail.get("series_batches") or []),
        "sanity_first": prior.get("sanity_first") if prior.get("sanity_first") is not None else start_value,
        "sanity_last": final_value,
        "evidence": "MAA FightTimes累计完成 + 单次代理尾段 + 实时理智前后OCR",
    }
    runtime._atomic_write_json(runtime.FIGHT_HANDOFF_FILE, payload)
    return payload


def drain_single_series(runtime, prior_handoff=None, summary=None):
    """Consume existing sanity on 1-7 and prove the final balance is below 6."""
    summary = summary if isinstance(summary, dict) else runtime._RUN_SUMMARY.setdefault(
        "remaining_sanity_use", {}
    )
    summary.update({
        "status": "verifying_exhaustion",
        "stage": STAGE,
        "purpose": "搓合成玉所需固源岩",
        "medicine": False,
        "originium": False,
        "acceptance": "live_final_sanity_below_6",
    })
    before = runtime._capture_stamina_observation("rock_tail_before", navigate=True)
    start_value = _verified_value(before)
    if start_value is None:
        summary.update({"status": "failed", "detail": "尾段开始前实时理智未确认"})
        return False
    if start_value < STAGE_COST:
        summary.update({
            "status": "completed_verified_exhausted",
            "detail": f"实时理智{start_value}/210，低于1-7消耗{STAGE_COST}",
            "final_sanity": start_value,
            "tail_runs": 0,
            "tail_sanity_consumed": 0,
        })
        return True

    prior_handoff = dict(prior_handoff or runtime._load_fight_handoff() or {})
    total_tail_runs = 0
    total_tail_cost = 0
    total_batches = []
    rounds = []
    current_value = start_value

    for round_index in range(1, MAX_SINGLE_SERIES_ROUNDS + 1):
        runtime.reload_maa_after_config_switch(
            f"1-7单次代理尾段第{round_index}轮，实时理智{current_value}"
        )
        try:
            with runtime.temporary_maa_config(
                lambda cfg: _configure_single_series(runtime, cfg),
                "仅Fight 1-7，Series=1，直到实时理智低于6",
            ):
                if not runtime.run_maa_daily_tasks(enabled_tasks={"Fight"}):
                    summary.update({"status": "failed", "detail": "MAA单次代理尾段启动失败"})
                    return False
                result = runtime.wait_maa_complete(
                    timeout=7200,
                    prestarted_boundary=True,
                    active_battle_extension=3600,
                )
                if result is not True:
                    summary.update({
                        "status": "failed",
                        "detail": f"MAA单次代理尾段未确认结束: {result}",
                    })
                    return False
                maa_text = runtime._get_current_maa_run_log()
                evidence = runtime._parse_fight_times_evidence(maa_text) or {}
        except Exception as exc:
            summary.update({"status": "failed", "detail": f"单次代理尾段异常: {exc}"})
            runtime.log(f"❌ 1-7单次代理尾段异常: {exc}", "ERROR")
            return False

        runs = int(evidence.get("runs", 0) or 0)
        cost = runs * STAGE_COST
        after = runtime._capture_stamina_observation(
            f"rock_tail_after_{round_index}", navigate=True
        )
        after_value = _verified_value(after)
        rounds.append({
            "round": round_index,
            "before": current_value,
            "after": after_value,
            "runs": runs,
            "sanity_consumed": cost,
            "series_batches": list(evidence.get("series_batches") or []),
        })
        if runs <= 0 or after_value is None or after_value >= current_value:
            summary.update({
                "status": "failed_no_verified_progress",
                "detail": "单次代理尾段没有形成完成次数与实时理智下降闭环",
                "tail_rounds": rounds,
            })
            return False

        total_tail_runs += runs
        total_tail_cost += cost
        total_batches.extend(evidence.get("series_batches") or [])
        current_value = after_value
        if current_value < STAGE_COST:
            tail = {
                "runs": total_tail_runs,
                "sanity_cost": total_tail_cost,
                "series_batches": total_batches,
            }
            merged = _merge_handoff(
                runtime, prior_handoff, tail, start_value, current_value
            )
            summary.update({
                "status": "completed_verified_exhausted",
                "detail": f"实时理智已降至{current_value}/210，低于1-7消耗{STAGE_COST}",
                "tail_runs": total_tail_runs,
                "tail_sanity_consumed": total_tail_cost,
                "actual_runs": int(merged["runs"]),
                "sanity_consumed": int(merged["sanity_consumed"]),
                "final_sanity": current_value,
                "tail_rounds": rounds,
                "completed_at": datetime.now().isoformat(timespec="seconds"),
            })
            runtime.log(
                f"✅ 1-7理智尾段闭环：新增{total_tail_runs}次，最终{current_value}/210"
            )
            return True

    summary.update({
        "status": "failed_not_exhausted_after_bounded_retries",
        "detail": f"{MAX_SINGLE_SERIES_ROUNDS}轮后实时理智仍为{current_value}/210",
        "tail_runs": total_tail_runs,
        "tail_sanity_consumed": total_tail_cost,
        "tail_rounds": rounds,
    })
    return False


def install(runtime):
    current = runtime.mode_orundum_rock_fallback
    if getattr(current, "_daily_stamina_exhaustion_v1", False):
        return runtime

    def verified_fallback():
        result = current()
        summary = runtime._RUN_SUMMARY.setdefault("remaining_sanity_use", {})
        if result is not True:
            return False
        observation = runtime._capture_stamina_observation(
            "rock_auto_series_final", navigate=True
        )
        value = _verified_value(observation)
        if value is None:
            summary.update({
                "status": "failed_exhaustion_unverified",
                "detail": "MAA Fight结束，但实时理智未确认；不得报告理智耗尽",
            })
            return False
        if value < STAGE_COST:
            summary.update({
                "status": "completed_verified_exhausted",
                "detail": f"实时理智{value}/210，低于1-7消耗{STAGE_COST}",
                "final_sanity": value,
            })
            return True
        runtime.log(
            f"⚠️ MAA Fight已结束但实时理智仍为{value}/210；切换Series=1继续耗尽",
            "WARN",
        )
        return drain_single_series(runtime, summary=summary)

    verified_fallback._daily_stamina_exhaustion_v1 = True
    verified_fallback._wrapped = current
    runtime.mode_orundum_rock_fallback = verified_fallback
    runtime._daily_stamina_exhaustion_v1_installed = True
    return runtime
