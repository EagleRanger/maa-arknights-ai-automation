"""Restore native automatic series; keep live exhaustion and resource evidence.

MaaCore 6.18 Series=0 selects up to ten and reduces at the remaining-count /
sanity boundary. A configured maximum is not evidence of an executed batch.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from functools import wraps


def configure_auto(runtime, cfg, stage, times=99, current_stage=False):
    runtime._configure_fight(cfg, stage, times, current_stage=current_stage)
    fight = next(t for t in runtime._task_queue(cfg) if t.get("TaskType") == "Fight")
    fight.update(Series=0, HideSeries=False, UseMedicine=False,
                 UseExpiringMedicine=False, MedicineCount=0, UseStone=False, StoneCount=0)
    return fight


def _balance(obs):
    value = (obs or {}).get("value")
    return value if (obs or {}).get("verified") is True and type(value) is int else None


def drain_auto_batches(runtime, prior_handoff=None, summary=None):
    """One native queue, not one MAA restart/OCR navigation for every battle."""
    summary = summary if isinstance(summary, dict) else runtime._RUN_SUMMARY.setdefault("remaining_sanity_use", {})
    summary.update(stage="1-7", medicine=False, originium=False,
                   proxy_policy="native_auto_up_to_10", status="verifying_auto_batch_exhaustion")
    before = _balance(runtime._capture_stamina_observation("batch_tail_before", navigate=True))
    if before is None:
        summary.update(status="failed_exhaustion_unverified", detail="连续代理前实时理智未知")
        return False
    if before < 6:
        summary.update(status="completed_verified_exhausted", final_sanity=before, tail_runs=0)
        return True
    prior = dict(prior_handoff or runtime._load_fight_handoff() or {})
    # Keep the previous proven 37-battle tail ceiling, not a new resource budget.
    limit = min(37, before // 6 + 2)
    runtime.reload_maa_after_config_switch("1-7自动连续代理收尾，不逐场重启")
    try:
        with runtime.temporary_maa_config(
            lambda cfg: configure_auto(runtime, cfg, "1-7", limit),
            "1-7连续代理AUTO，最多10次一批、理智不足自动减次，禁药禁石",
        ):
            if not runtime.run_maa_daily_tasks(enabled_tasks={"Fight"}):
                raise RuntimeError("自动连续代理未启动")
            result = runtime.wait_maa_complete(timeout=7200, prestarted_boundary=True,
                                               active_battle_extension=3600)
            text = runtime._get_current_maa_run_log()
            evidence = runtime._parse_fight_times_evidence(text) or {}
    except Exception as exc:
        summary.update(status="failed", detail=str(exc))
        return False
    after = _balance(runtime._capture_stamina_observation("batch_tail_after", navigate=True))
    runs, cost = evidence.get("runs"), evidence.get("sanity_cost")
    batches = evidence.get("series_batches") or []
    verified = (type(runs) is int and 0 < runs <= limit
                and type(cost) is int and cost == runs * 6
                and all(type(n) is int and 1 <= n <= 10 for n in batches)
                and sum(batches) == runs and after is not None and after < before)
    summary["batch_tail_evidence"] = {
        "before": before, "after": after, "runs": runs, "sanity_cost": cost,
        "series_batches": batches, "task_completed": result is True,
        "verified": verified,
    }
    if not verified:
        summary.update(status="failed_no_verified_progress", detail="连续代理次数/批次/实时理智未对账，不自动重放")
        return False
    merged = dict(prior)
    merged.update(game_day=runtime._game_day_key(), recorded_at=datetime.now().isoformat(timespec="seconds"),
                  stage="1-7", runs=int(prior.get("runs", 0) or 0) + runs,
                  sanity_cost_each=6, sanity_consumed=int(prior.get("sanity_consumed", 0) or 0) + cost,
                  series_batches=list(prior.get("series_batches") or []) + batches,
                  sanity_first=prior.get("sanity_first") if prior.get("sanity_first") is not None else before,
                  sanity_last=after, evidence="本轮FightTimes实际批次与实时余额；不是配置上限")
    runtime._atomic_write_json(runtime.FIGHT_HANDOFF_FILE, merged)
    summary.update(actual_runs=merged["runs"], sanity_consumed=merged["sanity_consumed"],
                   final_sanity=after, tail_runs=runs, tail_sanity_consumed=cost,
                   actual_series_batches=merged["series_batches"])
    if result is not True or after >= 6:
        summary.update(status="failed_not_exhausted", detail="已有真实批次已保存，但尚未耗尽；不静默退回逐场重启")
        return False
    summary.update(status="completed_verified_exhausted", detail=f"连续代理完成，实时理智{after}<6")
    # Preserve V67's verified queue boundary: restored disk configuration is
    # not enough while the idle GUI still holds a Fight-only queue in memory.
    runtime.reload_maa_after_config_switch("连续代理已结算；最终五链重载已恢复的TaskQueue")
    return True


def install(runtime):
    import daily_policy_v23 as policy
    import daily_stamina_exhaustion_v1 as v1
    import daily_stamina_exhaustion_v2 as v2
    import daily_stamina_exhaustion_v3 as v3
    import daily_stamina_exhaustion_v4 as v4
    policy.configure_single_stage_fight = configure_auto
    v1._configure_single_series = lambda app, cfg, times=99: configure_auto(app, cfg, "1-7", times)
    v3._configure_new_series_single = v1._configure_single_series
    # Legacy drain wrappers also reinstall obsolete parser resources; do not
    # enter them after the final V66 geometry has been composed.
    v1.drain_single_series = drain_auto_batches
    v2.drain_single_series = drain_auto_batches
    v3.drain_single_series = drain_auto_batches
    v4.drain_exact_single_battles = drain_auto_batches
    for name in ("mode_orundum_rock_fallback", "mode_resource"):
        original = getattr(runtime, name, None)
        if not original:
            continue
        def wrap(fn):
            @wraps(fn)
            def call(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                finally:
                    summary = runtime._RUN_SUMMARY.get("remaining_sanity_use") or {}
                    if summary.get("stage"):
                        summary.update(series=0, proxy_policy="native_auto_up_to_10")
                        # Remove the frozen V23 misleading single-series claim.
                        detail = summary.get("detail", "")
                        summary["detail"] = detail.replace("以单次连续代理", "以原生自动倍率代理")
            return call
        setattr(runtime, name, wrap(original))
    runtime._RUN_SUMMARY["batch_proxy_policy"] = {
        "configured_series": 0, "max_native_batch": 10,
        "verified_batch_count": None, "actual_evidence_source": "current_run_FightTimes",
        "single_restart_tail_disabled": True,
    }
    return runtime


@contextmanager
def engine_boundary(runtime):
    import daily_policy_v23 as policy
    import daily_stamina_exhaustion_v1 as v1
    import daily_stamina_exhaustion_v2 as v2
    import daily_stamina_exhaustion_v3 as v3
    import daily_stamina_exhaustion_v4 as v4
    targets = [(policy, "configure_single_stage_fight"), (v1, "_configure_single_series"),
               (v3, "_configure_new_series_single"), (v4, "drain_exact_single_battles"),
               (v1, "drain_single_series"), (v2, "drain_single_series"), (v3, "drain_single_series")]
    originals = [(mod, key, getattr(mod, key)) for mod, key in targets]
    original_main = runtime.main

    @wraps(original_main)
    def main(*args, **kwargs):
        install(runtime)
        return original_main(*args, **kwargs)

    runtime.main = main
    try:
        yield
    finally:
        runtime.main = original_main
        for mod, key, value in originals:
            setattr(mod, key, value)
