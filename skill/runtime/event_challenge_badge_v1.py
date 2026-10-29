"""Additive repair for the SR-EX challenge badge and the progress ledger.

Two defects were reproduced on 2026-09-17 while the daily route tried to close
the Moon-on-Water special stages.

1. The frozen V12 detector reads the fourth (challenge) badge from
   ``x .922-.977 / y .102-.223``.  Measured on the six verified 1920x1080
   detail screenshots of this event, that rectangle contains no badge at all
   (white ratio ``0.000``), so an already cleared challenge layer is read as
   unfinished.  The real badge sits at ``x .741-.815 / y .197-.329``; the
   tight core ``x .768-.807 / y .180-.290`` yields ``0.321-0.329`` on all six
   positives.

   The new rectangle still reads ``0.002`` on ``_evidence/bd1_challenge_after``
   (an earlier event whose challenge badge *is* inside the legacy rectangle and
   reads ``0.221`` there), so the repair takes ``max(legacy, current)`` instead
   of replacing the old geometry.  The negative control
   ``_evidence/bd1_challenge_before.png`` - the same BD-1 detail page with the
   challenge layer still dark - stays at ``0.000`` under both rectangles, which
   is why the existing ``>= 0.08`` threshold keeps working unchanged.

2. ``_update_event_progress`` is the single write entry and it overwrote a
   trusted ``cleared`` challenge record with today's ``job_incompatible``
   result (``SR-EX-1`` lost its 2026-09-14 clear).  A job that could not even
   reach the formation page is not evidence about the stage, so the guard below
   restores the trusted status while keeping the newly written
   ``attempted_jobs``/``incompatible_jobs`` exclusions.

Coverage is deliberately narrow: a real ``cleared`` write always wins, and a
stage with no trusted clear keeps the frozen behaviour.
"""

from __future__ import annotations

import re


CHALLENGE_BADGE_RATIO_THRESHOLD = 0.08
CURRENT_CHALLENGE_BADGE_BOX = (0.768, 0.180, 0.807, 0.290)

GUARD_DETAIL_SUFFIX = "；写入保护：本次失败/不兼容记录不覆盖已核验的完成状态"

REGRESSION_STATUSES = frozenset({
    "job_incompatible",
    "job_failed",
    "failed",
    "blocked",
    "unknown",
    "partial",
})


def current_detail_challenge_badge_ratio(image_path):
    """White-pixel ratio of this event UI's fourth, upper-right challenge badge."""
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    left, top, right, bottom = CURRENT_CHALLENGE_BADGE_BOX
    roi = image.crop((
        int(width * left), int(height * top),
        int(width * right), int(height * bottom),
    ))
    pixels = list(roi.getdata())
    if not pixels:
        return 0.0
    white = sum(1 for red, green, blue in pixels
                if red > 180 and green > 180 and blue > 180)
    return white / len(pixels)


def current_detail_challenge_badge_complete(
    image_path, *, threshold=CHALLENGE_BADGE_RATIO_THRESHOLD
):
    return current_detail_challenge_badge_ratio(image_path) >= threshold


def install_challenge_badge_detector(runtime) -> None:
    """Layer the current geometry over, rather than edit, the frozen V12 runtime."""
    if getattr(runtime, "_event_challenge_badge_v1_installed", False):
        return
    legacy = runtime._event_challenge_badge_ratio

    def challenge_badge_ratio(image_path):
        old_ratio = legacy(image_path)
        current = current_detail_challenge_badge_ratio(image_path)
        return max(old_ratio, current)

    challenge_badge_ratio._event_challenge_badge_v1_original = legacy
    runtime._event_challenge_badge_ratio = challenge_badge_ratio
    runtime._event_challenge_badge_v1_installed = True


def _mode_state(progress_file, event_name, stage, mode):
    try:
        import json

        with open(progress_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    event = (data.get("events") or {}).get(event_name) or {}
    stage_state = (event.get("stages") or {}).get(stage) or {}
    return ((stage_state.get("modes") or {}).get(mode) or {})


def _restore_trusted_clear(runtime, progress_file, event_name, stage, mode,
                           preserved, rejected_status, rejected_detail):
    """Put the trusted ``cleared`` record back after a regression write."""
    import json

    with open(progress_file, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    stage_state = data["events"][event_name]["stages"][stage]
    modes = stage_state.setdefault("modes", {})
    current = dict(modes.get(mode) or {})
    merged = dict(current)
    merged["status"] = "cleared"
    merged["detail"] = (
        str(preserved.get("detail") or "").strip() + GUARD_DETAIL_SUFFIX
    ).strip("；")
    if preserved.get("successful_job"):
        merged["successful_job"] = preserved["successful_job"]
    modes[mode] = merged

    configured = None
    resolver = getattr(runtime, "_configured_event_from_name", None)
    if callable(resolver):
        configured = resolver(event_name) or None
    stage_config = next(
        (
            item for item in (configured or {}).get("stages", [])
            if item.get("display") == stage
        ),
        {},
    )
    modes_for_stage = getattr(runtime, "_event_stage_modes", None)
    required_modes = (
        modes_for_stage(configured, stage_config) if callable(modes_for_stage)
        else ["normal", "challenge"]
    )
    all_cleared = all(
        (modes.get(name) or {}).get("status") == "cleared"
        for name in required_modes
    )
    if all_cleared:
        stage_state["status"] = "cleared"
        stage_state["detail"] = (
            "、".join("普通" if name == "normal" else "突袭"
                      for name in required_modes)
            + "均完成"
        )
    data["last_update"] = __import__("datetime").datetime.now().isoformat(
        timespec="seconds"
    )

    original = getattr(runtime, "_atomic_write_json", None)
    if callable(original):
        original(progress_file, data)
    else:
        with open(progress_file, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

    summary = getattr(runtime, "_RUN_SUMMARY", None)
    if isinstance(summary, dict):
        run_stages = (summary.setdefault("event", {"name": event_name, "stages": {}})
                      .setdefault("stages", {}))
        run_stages[stage] = dict(stage_state)
        summary.setdefault("event_progress_guard", []).append({
            "stage": stage,
            "mode": mode,
            "rejected_status": rejected_status,
            "rejected_detail_jobs": re.findall(
                r"[A-Za-z0-9_-]+\.json", str(rejected_detail or "")
            ),
            "restored": "cleared",
            "restored_from_job": preserved.get("successful_job"),
        })
    runtime.log(
        "  [进度保护] {} {} 的已核验完成状态未被本次“{}”记录覆盖".format(
            stage, mode, rejected_status
        )
    )


def install_event_progress_guard(runtime) -> None:
    """Never let a failure/incompatible write erase a trusted clear."""
    if getattr(runtime, "_event_progress_guard_v1_installed", False):
        return
    original = runtime._update_event_progress
    progress_file = getattr(runtime, "EVENT_PROGRESS_FILE", None)

    def update_event_progress(event_name, stage, status, detail="", mode=None,
                              **kwargs):
        preserved = {}
        if mode and progress_file and str(status or "") in REGRESSION_STATUSES:
            previous = _mode_state(progress_file, event_name, stage, mode)
            if previous.get("status") == "cleared":
                preserved = previous
        result = original(event_name, stage, status, detail=detail, mode=mode,
                          **kwargs)
        if preserved and progress_file:
            _restore_trusted_clear(runtime, progress_file, event_name, stage,
                                   mode, preserved, status, detail)
        return result

    update_event_progress._event_progress_guard_v1_original = original
    runtime._update_event_progress = update_event_progress
    runtime._event_progress_guard_v1_installed = True


def install(runtime) -> None:
    """Idempotent installation of both layers."""
    install_challenge_badge_detector(runtime)
    install_event_progress_guard(runtime)
    if getattr(runtime, "_event_challenge_badge_v1_installed", False) is not True:
        raise ValueError("challenge badge detector layer missing")
    if getattr(runtime, "_event_progress_guard_v1_installed", False) is not True:
        raise ValueError("event progress guard layer missing")
