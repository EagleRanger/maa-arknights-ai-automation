"""Live stamina observation overlay.

The frozen V12 runtime always navigated to the home page before its final
observation.  That throws away a stronger ``x/210`` value already visible on
the stage detail page and can land on an activity banner whose home-card OCR
is unreliable.  This overlay samples the current screen first, then falls
back to the home page only when no stable explicit value is available.
"""

from __future__ import annotations

from datetime import datetime


def _stable_samples(runtime, attempts=3):
    samples = []
    for _ in range(attempts):
        samples.append(runtime.get_stamina())
        if (
            len(samples) >= 2
            and isinstance(samples[-1], int)
            and samples[-1] == samples[-2]
        ):
            break
        runtime.wait(1)
    value = samples[-1] if samples else None
    verified = bool(
        len(samples) >= 2
        and isinstance(value, int)
        and value == samples[-2]
    )
    return samples, value, verified


def install(runtime):
    current = runtime._capture_stamina_observation
    if getattr(current, "_daily_live_stamina_ocr_v1", False):
        return runtime

    def capture(phase, navigate=True):
        observations = runtime._RUN_SUMMARY.setdefault("stamina_observations", {})
        record = {
            "phase": str(phase),
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "source": "game_screen_ocr_current_then_home",
            "value": None,
            "verified": False,
        }
        try:
            # Stage detail and map pages expose a literal x/210 ratio.  Read it
            # before navigation so an already decisive value is not discarded.
            samples, value, verified = _stable_samples(runtime)
            source_page = "current_screen"
            if not verified and navigate:
                if runtime.goto_main_menu():
                    samples, value, verified = _stable_samples(runtime)
                    source_page = "main_menu_fallback"
                else:
                    record["navigation_reason"] = "main_menu_not_confirmed"
            record["samples"] = samples
            record["source_page"] = source_page
            if verified:
                record.update({
                    "value": value,
                    "max": 210,
                    "verified": True,
                    "evidence": runtime.shot(f"stamina_{phase}_verified"),
                })
                runtime.log(
                    f"  [日报理智实证] {phase}: {value}/210 ({source_page})"
                )
            else:
                record["reason"] = "stamina_ocr_failed_or_disagreed"
                runtime.log(f"  [日报理智实证] {phase}: OCR未确认", "WARN")
        except Exception as exc:
            record["reason"] = f"{type(exc).__name__}: {exc}"
            runtime.log(
                f"  [日报理智实证] {phase}: {record['reason']}", "WARN"
            )
        observations[str(phase)] = record
        return record

    capture._daily_live_stamina_ocr_v1 = True
    capture._wrapped = current
    runtime._capture_stamina_observation = capture
    runtime._daily_live_stamina_ocr_v1_installed = True
    return runtime

