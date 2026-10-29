"""V3 stamina tail: use MaaCore's new ten-entry series parser."""

from __future__ import annotations

import daily_stamina_exhaustion_v1 as v1


_V1_DRAIN = v1.drain_single_series


def _configure_new_series_single(runtime, cfg, times=99):
    runtime._configure_fight(cfg, v1.STAGE, times)
    fight = next(
        item for item in runtime._task_queue(cfg) if item.get("TaskType") == "Fight"
    )
    fight.update({
        "StagePlan": [v1.STAGE],
        "Series": 1,
        "HideSeries": True,
        "UseMedicine": False,
        "UseExpiringMedicine": False,
        "MedicineCount": 0,
        "UseStone": False,
        "StoneCount": 0,
    })
    return fight


def drain_single_series(runtime, prior_handoff=None, summary=None):
    import maa_series_resource_v1 as resource

    resource.install(runtime)
    original = v1._configure_single_series
    v1._configure_single_series = _configure_new_series_single
    try:
        return _V1_DRAIN(
            runtime,
            prior_handoff=prior_handoff,
            summary=summary,
        )
    finally:
        v1._configure_single_series = original


def install(runtime):
    import maa_series_resource_v1 as resource

    resource.install(runtime)
    current = runtime.mode_orundum_rock_fallback
    if getattr(current, "_daily_stamina_exhaustion_v3", False):
        return runtime
    if getattr(current, "_daily_stamina_exhaustion_v2", False) or getattr(
        current, "_daily_stamina_exhaustion_v1", False
    ):
        current = current._wrapped

    def verified_fallback():
        result = current()
        summary = runtime._RUN_SUMMARY.setdefault("remaining_sanity_use", {})
        if result is not True:
            return False
        observation = runtime._capture_stamina_observation(
            "rock_auto_series_final", navigate=True
        )
        value = v1._verified_value(observation)
        if value is None:
            summary.update({
                "status": "failed_exhaustion_unverified",
                "detail": "MAA Fight结束，但实时理智未确认；不得报告理智耗尽",
            })
            return False
        if value < v1.STAGE_COST:
            summary.update({
                "status": "completed_verified_exhausted",
                "detail": f"实时理智{value}/210，低于1-7消耗{v1.STAGE_COST}",
                "final_sanity": value,
            })
            return True
        runtime.log(
            f"⚠️ MAA多次代理结束但实时理智仍为{value}/210；"
            "使用新版十档倍率解析器切换到单次代理继续耗尽",
            "WARN",
        )
        return drain_single_series(runtime, summary=summary)

    verified_fallback._daily_stamina_exhaustion_v3 = True
    verified_fallback._wrapped = current
    runtime.mode_orundum_rock_fallback = verified_fallback
    runtime._daily_stamina_exhaustion_v3_installed = True
    return runtime
