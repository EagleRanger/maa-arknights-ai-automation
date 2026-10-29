"""Turn the hot-update failure page into repeated, verified retries.

Live evidence, 2026-09-17:

* 16:09:47-16:12:32 the frozen daily runtime waited through its whole
  10x15s startup loop on one page, ``get_state()`` returned ``unknown`` for
  every frame, and the run continued into the daily chains with the game still
  stuck.  The same page was then reported to the project lane as
  ``unknown_page_no_verified_progress_30s``
  (``outputs/event_page_attention/3580e366c0f5fdb274b1.json``).
* The page itself is the B-station U8 SDK hot-update check:
  ``获取资源版本信息失败，请检查网络连接后重试`` / ``错误号:0`` /
  ``正在获取更新…``.  Its only control is the white circular checkmark at
  ``(960, 736)`` - the same verified error-0 retry control the frozen runtime
  already taps for ``transient_game_login_error``.  ``网络检测`` opens a
  diagnostic popup and ``清除缓存`` discards the client cache, so neither is a
  retry.
* The failure is transient: the 15:30 event of the same kind cleared by itself
  in about two minutes, and the user states plainly that repeating the click
  gets the client in.

The frozen runtime cannot be edited (``run_daily_v14.check_entry`` verifies its
artifact hash), so this module installs additive wrappers instead:

1. ``ensure_env`` - after the frozen startup loop, keep tapping the checkmark
   while that exact page is still on screen, until the page leaves or a bounded
   tap budget is spent.
2. ``handle_popups`` - during the startup window only, the same tap replaces a
   passive 15s wait, so the retry happens while the frozen loop is still running.
3. ``_wait_unknown_navigation_page`` - a later recurrence during
   ``goto_main_menu`` is retried instead of being reported as an unknown page.

Every tap is gated on MAA being idle, so no input is ever sent while a MAA
queue owns the game.  ``MAX_TAPS_PER_RUN`` bounds the whole run: once the budget
is gone the page is treated as genuinely unhandled and the frozen guard reports
it truthfully.
"""

from __future__ import annotations

import re


# 1920x1080 实机核验：白色圆形对勾位于屏幕下方中央，不是文字按钮。
RETRY_TAP = (960, 736)
MAX_TAPS_PER_RUN = 30
DENSE_ATTEMPTS = 24
DENSE_INTERVAL = 4
NAV_DENSE_ATTEMPTS = 6


def is_resource_version_retry_page(text):
    """True only for the B-station hot-update check failure page.

    ``获取资源版本信息失败`` is the page-specific sentence.  The generic
    ``登入时发生错误`` dialog is a different page and must keep its own
    handling, so it is never matched here.
    """
    compact = re.sub(r"\s+", "", str(text or ""))
    if "获取资源版本信息失败" not in compact:
        return False
    if "正在获取更新" in compact:
        return True
    return re.search(r"错误号[:：]?0(?!\d)", compact) is not None


def _maa_busy(runtime):
    """Any running MAA queue means the game is owned elsewhere: never tap."""
    for name in ("_maa_task_queue_running", "_maa_daily_queue_running"):
        probe = getattr(runtime, name, None)
        if probe is None:
            continue
        try:
            if probe():
                return True
        except Exception:
            continue
    return False


def _new_state():
    return {
        "taps": 0,
        "probes": 0,
        "skipped_maa_busy": 0,
        "last_screenshot": None,
        "last_ocr": "",
        "startup_active": False,
        "status": "idle",
    }


def _probe(runtime, state, label):
    path = runtime.shot(label)
    text = runtime.ocr_text(path)
    state["probes"] += 1
    state["last_screenshot"] = str(path)
    state["last_ocr"] = text
    return path, text


def _try_retry(runtime, state, *, label, reason, tap_wait=3):
    """Probe once and tap the verified retry control only when it is really there."""
    if _maa_busy(runtime):
        state["skipped_maa_busy"] += 1
        return "maa_busy"
    _path, text = _probe(runtime, state, label)
    if not is_resource_version_retry_page(text):
        return "not_retry_page"
    if state["taps"] >= MAX_TAPS_PER_RUN:
        state["status"] = "tap_budget_exhausted"
        return "tap_budget_exhausted"
    runtime.tap(*RETRY_TAP)
    state["taps"] += 1
    state["status"] = "retrying"
    runtime.log(
        "→ 获取资源版本信息失败页：第{}次点击重试（{}）".format(state["taps"], reason)
    )
    if tap_wait:
        runtime.wait(tap_wait)
    return "tapped"


def _record(runtime, state, outcome):
    summary = getattr(runtime, "_RUN_SUMMARY", None)
    if not isinstance(summary, dict):
        return
    summary["login_resource_retry"] = {
        "status": outcome,
        "taps": state["taps"],
        "probes": state["probes"],
        "skipped_maa_busy": state["skipped_maa_busy"],
        "last_screenshot": state["last_screenshot"],
    }


def retry_resource_page_until_ready(runtime, state, max_attempts=None,
                                    interval=None, reason="post_startup"):
    """Tap the hot-update retry control until the page leaves or the cap is hit.

    ``max_attempts``/``interval`` are read from the module constants at call
    time so an operator (or a test) can retune them without reimporting.
    """
    if max_attempts is None:
        max_attempts = DENSE_ATTEMPTS
    if interval is None:
        interval = DENSE_INTERVAL
    for _ in range(max_attempts):
        outcome = _try_retry(
            runtime, state, label="login_resource_retry_probe", reason=reason,
            tap_wait=interval,
        )
        if outcome == "not_retry_page":
            state["status"] = "page_left"
            _record(runtime, state, "page_left")
            return "page_left"
        if outcome != "tapped":
            _record(runtime, state, outcome)
            return outcome
    state["status"] = "attempts_exhausted"
    _record(runtime, state, "attempts_exhausted")
    return "attempts_exhausted"


def install(runtime):
    """Install the three additive wrappers; idempotent per process."""
    if getattr(runtime, "_login_resource_retry_v1_installed", False):
        return getattr(runtime, "ensure_env")

    state = _new_state()

    original_ensure_env = runtime.ensure_env

    def ensure_env_retry(*args, **kwargs):
        state["startup_active"] = True
        try:
            result = original_ensure_env(*args, **kwargs)
        finally:
            state["startup_active"] = False
        if not result:
            state["status"] = "environment_failed"
            return result
        retry_resource_page_until_ready(runtime, state)
        return result

    ensure_env_retry._login_resource_retry_original = original_ensure_env
    runtime.ensure_env = ensure_env_retry

    original_handle_popups = getattr(runtime, "handle_popups", None)
    if original_handle_popups is not None:
        def handle_popups_retry():
            if state["startup_active"]:
                outcome = _try_retry(
                    runtime, state, label="login_resource_retry_popup",
                    reason="startup_wait", tap_wait=3,
                )
                if outcome == "tapped":
                    return True
            return original_handle_popups()

        handle_popups_retry._login_resource_retry_original = original_handle_popups
        runtime.handle_popups = handle_popups_retry

    original_unknown_navigation = getattr(runtime, "_wait_unknown_navigation_page", None)
    if original_unknown_navigation is not None:
        def wait_unknown_navigation_page_retry():
            for _ in range(NAV_DENSE_ATTEMPTS):
                outcome = _try_retry(
                    runtime, state, label="login_resource_retry_nav_probe",
                    reason="unknown_navigation", tap_wait=3,
                )
                if outcome != "tapped":
                    break
            return original_unknown_navigation()

        wait_unknown_navigation_page_retry._login_resource_retry_original = (
            original_unknown_navigation
        )
        runtime._wait_unknown_navigation_page = wait_unknown_navigation_page_retry

    runtime._login_resource_retry_v1_state = state
    runtime._login_resource_retry_v1_installed = True
    return runtime.ensure_env
