"""Daily V15 candidate: preserve V14's entry and retry the hot-update page.

2026-09-17 16:09:47-16:12:32 production evidence
(``outputs/event_page_attention/3580e366c0f5fdb274b1.json``):

* The B-station U8 SDK hot-update check page
  (``获取资源版本信息失败`` / ``错误号:0`` / ``正在获取更新``) stayed on
  screen while the frozen startup loop spent its whole 10 x 15s budget waiting.
  ``get_state()`` answered ``unknown`` for every frame, the run then started the
  daily chains with the game still stuck, and all five MAA chains failed.
* The page is transient: the 15:30 occurrence of the same page cleared by
  itself in about two minutes, and the user states plainly that repeating the
  click gets the client in.

V14 and everything below it stay frozen and untouched.  V15 adds exactly one
layer, ``login_resource_retry_v1``, which taps the verified white circular
checkmark at ``(960, 736)`` while that exact page is on screen - never
``网络检测``, never ``清除缓存``, and never while a MAA queue owns the game.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import run_daily as base
import run_daily_v14 as v14


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v15.py --mode full"


def check_entry(at=None):
    """V15's own immutable admission gate; no game action is performed here."""
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads((ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V15 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V15 route disagree")
    gate = resolve_production_recipes(ROOT / ".project-reasoning" / "COMPONENTS.json", handoff["required_recipes"])
    registry = json.loads((ROOT / ".project-reasoning" / "COMPONENTS.json").read_text(encoding="utf-8"))
    component_ids = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in component_ids:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            if hashlib.sha256(path.read_bytes()).hexdigest().upper() != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper() != handoff["production_snapshot_sha256"].upper():
        raise ValueError("Daily V15 entry snapshot changed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS", "entrypoint": ENTRYPOINT, "checked_at": now.isoformat(),
        "sss_window": reward_window(now), "daily_expired_by_sss": False,
        "sr_event_ui": "v14_vertical_map_identity_and_color_independent_badges",
        "login_resource_retry": "v1_repeated_verified_checkmark_until_page_leaves",
        "game_actions": 0,
    }


def install_v15_runtime_adapters():
    """V14 must bind its own layers first; then V15 adds only the retry layer."""
    runtime = v14.install_v14_runtime_adapters()
    import login_resource_retry_v1 as retry

    retry.install(runtime)
    if getattr(runtime, "_login_resource_retry_v1_installed", False) is not True:
        raise ValueError("V15 requires the hot-update retry layer")
    runtime.log("  [V15] 获取资源版本信息失败页重复重试层已安装（MAA运行时零输入）")
    return runtime


def main():
    check_entry()
    original_main = base.main

    def bound_main(*args, **kwargs):
        install_v15_runtime_adapters()
        return original_main(*args, **kwargs)

    bound_main._daily_v15_bound = True
    base.main = bound_main
    # V14 and V13 are used only as the already verified layers below.  Redirect
    # their preflight callbacks to V15 so the active handoff cannot be bypassed.
    v14.check_entry = check_entry
    return v14.main()


def cli(argv=None):
    """Keep the declared read-only production preflight genuinely read-only."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    return main()


if __name__ == "__main__":
    # Lower layers delegate to the legacy entry which resets argv to
    # ``--mode full``.  Handle this production gate here, before that
    # delegation, so execution lanes never mistake a real game run for a
    # read-only preflight.
    raise SystemExit(cli())
