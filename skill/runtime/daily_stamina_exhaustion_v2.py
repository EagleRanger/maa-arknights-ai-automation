"""V2 stamina exhaustion adapter using MAA's verified single-battle mode.

V1 set ``Series=1`` but left ``HideSeries=False``.  On MAA 6.16.8 that still
activates the native multi-proxy selector; when the selector cannot read its
list it falls back to five-battle batches and can end early.  The older V23
resource route already proved that ``Series=1`` plus ``HideSeries=True`` is the
single-battle contract, so V2 reuses that exact configuration.
"""

from __future__ import annotations

import daily_stamina_exhaustion_v1 as v1


_V1_DRAIN = v1.drain_single_series


def _configure_single_battle(runtime, cfg, times=99):
    import daily_policy_v23

    return daily_policy_v23.configure_single_stage_fight(
        runtime, cfg, v1.STAGE, times=times
    )


def drain_single_series(runtime, prior_handoff=None, summary=None):
    original = v1._configure_single_series
    v1._configure_single_series = _configure_single_battle
    try:
        return _V1_DRAIN(
            runtime,
            prior_handoff=prior_handoff,
            summary=summary,
        )
    finally:
        v1._configure_single_series = original


def install(runtime):
    current = runtime.mode_orundum_rock_fallback
    if getattr(current, "_daily_stamina_exhaustion_v2", False):
        return runtime
    if getattr(current, "_daily_stamina_exhaustion_v1", False):
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
            "切换HideSeries=True的普通单次战斗继续耗尽",
            "WARN",
        )
        return drain_single_series(runtime, summary=summary)

    verified_fallback._daily_stamina_exhaustion_v2 = True
    verified_fallback._wrapped = current
    runtime.mode_orundum_rock_fallback = verified_fallback
    runtime._daily_stamina_exhaustion_v2_installed = True
    return runtime
