"""Evidence-only admission and accounting for an interrupted post-Fight run."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta


def game_day(at):
    return (at - timedelta(hours=4)).date().isoformat()


def admit(source, fight, mainline, log, *, now, active=()):
    if active:
        raise ValueError("A game/controller still owns the account")
    started = datetime.fromisoformat(source["started_at"])
    if game_day(started) != game_day(now):
        raise ValueError("Continuation must remain in the source game day")
    if source.get("business_complete") is not False or source.get("status") not in {
        "running", "interrupted", "partial_or_blocked"
    }:
        raise ValueError("Source is not an unfinished daily run")
    day = game_day(now)
    if fight.get("game_day") != day or mainline.get("game_day") != day:
        raise ValueError("Effect receipts are not from this game day")
    recorded = datetime.fromisoformat(fight["recorded_at"])
    if not started.replace(tzinfo=None) <= recorded.replace(tzinfo=None) <= now.replace(tzinfo=None):
        raise ValueError("Fight receipt lies outside the source interval")
    runs, cost = fight.get("runs"), fight.get("sanity_consumed")
    batches = fight.get("series_batches") or []
    if (fight.get("stage") != "1-7" or type(runs) is not int or runs <= 0
            or type(cost) is not int or cost != runs * 6
            or not batches or any(type(n) is not int or not 1 <= n <= 10 for n in batches)
            or sum(batches) != runs):
        raise ValueError("Source FightTimes/cost/batches are not reconciled")
    if (mainline.get("status") != "completed"
            or (mainline.get("run") or {}).get("status") != "completed"):
        raise ValueError("Source mainline scan was not completed")
    required = (f"time={started.replace(tzinfo=None).isoformat(timespec='seconds')}",
                f"1-7真实完成{runs}次", "场景: 每日日常任务", "任务链切换到: Infrast")
    if any(text not in log for text in required):
        raise ValueError("Run log does not prove this post-Fight interruption")
    if "最终日常五条任务链（含Award）均已确认完成" in log:
        raise ValueError("Do not replay a finished final queue")
    return {"source_run_id": source["run_id"], "mainline": deepcopy(mainline["run"]),
            "prior_fight": deepcopy(fight), "reuse": "same_day_verified_mainline_scan",
            "unfinished": ["live_sanity_tail", "333_products_and_rotation", "post_fight_daily", "report", "cleanup"]}


def normalize_report(report, source):
    """Keep this process's balances distinct from the explicitly inherited effects."""
    prior = source["prior_fight"]
    if report.get("date") and report["date"] != prior["game_day"]:
        raise ValueError("Cannot merge effects across game days")
    current = deepcopy(report.get("fight") or {})
    runs = current.get("times_finished", current.get("fights"))
    cost = current.get("total_cost")
    verified = (current.get("stage") == prior["stage"]
                and type(runs) is int and runs > 0 and type(cost) is int
                and cost == runs * 6)
    current_drops = deepcopy(report.get("drops") or []) if verified else []
    drop_totals = {}
    for row in [*(prior.get("drops") or []), *current_drops]:
        if row.get("item") and type(row.get("qty")) is int and row["qty"] >= 0:
            drop_totals[row["item"]] = drop_totals.get(row["item"], 0) + row["qty"]
    totals = {"source_run_id": source["source_run_id"], "stage": "1-7",
              "prior_runs": prior["runs"], "prior_cost": prior["sanity_consumed"],
              "current_runs": runs if verified else None,
              "current_cost": cost if verified else None,
              "total_runs": prior["runs"] + runs if verified else prior["runs"],
              "total_cost": prior["sanity_consumed"] + cost if verified else prior["sanity_consumed"],
              "current_effect_verified": verified,
              "prior_drops": deepcopy(prior.get("drops") or []),
              "current_drops": current_drops,
              "total_drops": [{"item": item, "qty": qty} for item, qty in drop_totals.items()],
              "prior_sanity_first": prior.get("sanity_first"),
              "prior_sanity_last": prior.get("sanity_last"),
              "final_live_sanity": report.get("final_stamina"),
              "scope": "explicit_same_game_day_cumulative_not_this_process_consumption"}
    report["same_game_day_verified_totals"] = totals
    report["same_day_continuation_source"] = source["source_run_id"]
    report.setdefault("run_summary", {})["same_game_day_verified_totals"] = deepcopy(totals)
    # Do not promote any completion flag: five chains, live balance and cleanup
    # must still be proven by the existing production runtime.
    return report
