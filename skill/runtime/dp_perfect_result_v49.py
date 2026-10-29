"""Distinguish a DP clear from all-three-pink-sheep perfect completion.

This is deliberately result-page-only.  A historical clear checkpoint or the
words `挑战成功` cannot certify perfect completion in Dolly's Playground.
"""

from __future__ import annotations

from pathlib import Path
from PIL import Image
from copy import deepcopy
from datetime import datetime
import hashlib
import json

import dp_result_navigation_v37 as v37


def sheep_pink_status(path: str | Path) -> tuple[bool, bool, bool] | None:
    with Image.open(path) as source:
        image = source.convert("RGB")
    width, height = image.size
    if width < 960 or height < 540:
        return None
    result = []
    for center in (160, 280, 405):
        x0 = round((center - 33) * width / 1920)
        x1 = round((center + 33) * width / 1920)
        y0 = round(575 * height / 1080)
        y1 = round(635 * height / 1080)
        crop = image.crop((x0, y0, x1, y1))
        pixels = list(crop.get_flattened_data() if hasattr(crop, "get_flattened_data") else crop.getdata())
        if not pixels:
            return None
        pink = sum(1 for red, green, blue in pixels
                   if red - green >= 10 and red - blue >= 3)
        result.append(pink / len(pixels) >= 0.65)
    return tuple(result)


def perfect_result(path: str | Path) -> bool | None:
    status = sheep_pink_status(path)
    return None if status is None else all(status)


def detail_sheep_pink_status(path: str | Path) -> tuple[bool, bool, bool] | None:
    with Image.open(path) as source:
        image = source.convert("RGB")
    width, height = image.size
    if width < 960 or height < 540:
        return None
    result = []
    for center in (1380, 1500, 1620):
        x0 = round((center - 25) * width / 1920)
        x1 = round((center + 25) * width / 1920)
        y0 = round(220 * height / 1080)
        y1 = round(270 * height / 1080)
        crop = image.crop((x0, y0, x1, y1))
        pixels = list(crop.get_flattened_data() if hasattr(crop, "get_flattened_data") else crop.getdata())
        if not pixels:
            return None
        pink = sum(1 for red, green, blue in pixels
                   if red - green >= 10 and red - blue >= 3)
        result.append(pink / len(pixels) >= 0.65)
    return tuple(result)


def ex1_attempt_limit(contract: dict, mode: str) -> int:
    key = f"逐影集趣:DP-EX-1:{mode}"
    hard = (contract.get("hard_constraints") or {}).get("event_stage_attempt_overrides") or {}
    goal = next(
        item for item in (contract.get("active_goals") or [])
        if item.get("id") == "G-EVENT-001"
    )
    intended = goal.get("stage_retry_overrides") or {}
    if hard.get(key) != intended.get(key) or hard.get(key) != 10:
        raise ValueError("DP-EX-1 additional five opportunities are not contract-aligned")
    return 10


def install(runtime):
    """Keep DP cleared and perfect separate in the existing battle closure."""
    if getattr(runtime, "_dp_perfect_result_v49_installed", False):
        return runtime
    original_stars = runtime._victory_three_star_status
    original_verify = runtime.verify_event_stage_cleared
    original_update = runtime._update_event_progress
    original_trusted = runtime._event_mode_has_trusted_clear_evidence
    original_open = runtime._open_event_stage_detail
    original_clear = runtime.clear_event_stage

    def clear_stage(event, stage, mode="normal", max_attempts=None, force_replay=False):
        if (event or {}).get("name") == "逐影集趣" and (stage or {}).get("display") == "DP-EX-1" and max_attempts is None:
            contract = json.loads((Path(runtime.BASE) / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
            max_attempts = ex1_attempt_limit(contract, mode)
        return original_clear(event, stage, mode=mode,
                              max_attempts=max_attempts, force_replay=force_replay)

    def open_detail(event, display_name, *args, **kwargs):
        result = original_open(event, display_name, *args, **kwargs)
        runtime._dp_v49_last_detail = (
            display_name, str(result[0]) if result else ""
        )
        return result

    def stars(path):
        stage = v37._dp_result_stage(runtime.ocr(path))
        if not stage:
            return original_stars(path)
        states = sheep_pink_status(path)
        if states is None:
            runtime._dp_v49_last_result = (stage, None)
            return {"lit": 0, "ratios": [], "perfect": False}
        runtime._dp_v49_last_result = (stage, all(states))
        runtime._dp_v49_last_result_path = str(path)
        runtime.log(f"  [V49满星] {stage}羊颜色={states}; 完美={all(states)}")
        return {"lit": sum(states), "ratios": [float(item) for item in states],
                "perfect": all(states)}

    def verify(event, display_name):
        cleared, _old_perfect = original_verify(event, display_name)
        if str((event or {}).get("name") or "") != "逐影集趣":
            return cleared, _old_perfect
        if not str(display_name).startswith("DP-"):
            return cleared, _old_perfect
        detail_stage, detail_path = getattr(runtime, "_dp_v49_last_detail", (None, ""))
        if detail_stage == display_name and detail_path and Path(detail_path).is_file():
            detail_states = detail_sheep_pink_status(detail_path)
            if detail_states is not None:
                return True, all(detail_states)
        last_stage, last_perfect = getattr(runtime, "_dp_v49_last_result", (None, None))
        if last_stage != display_name:
            # The old light-map receipt establishes clearance only.  It never
            # establishes that all three sheep were pink.
            return cleared, False if cleared else _old_perfect
        return cleared, bool(last_perfect) if cleared else False

    def trusted(event_name, stage, mode):
        if event_name != "逐影集趣" or mode != "normal" or not str(stage).startswith("DP-") or "TR" in stage or "EX" in stage:
            return original_trusted(event_name, stage, mode)
        state = (
            (((runtime._load_event_progress().get("events") or {}).get(event_name) or {})
             .get("stages") or {}).get(stage) or {}
        )
        normal = (state.get("modes") or {}).get("normal") or {}
        if normal.get("perfect_status") == "verified":
            evidence = normal.get("perfect_evidence") or {}
            path = Path(str(evidence.get("result_screenshot") or ""))
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest().upper() == str(evidence.get("result_sha256") or "").upper():
                return perfect_result(path) is True
        old_evidence = normal.get("evidence") or {}
        result_path = Path(runtime.BASE) / str(old_evidence.get("result_screenshot") or "")
        if result_path.is_file() and perfect_result(result_path) is True:
            return original_trusted(event_name, stage, mode)
        detail_evidence = normal.get("perfect_detail_evidence") or {}
        detail_path = Path(str(detail_evidence.get("screenshot") or ""))
        if detail_path.is_file() and hashlib.sha256(detail_path.read_bytes()).hexdigest().upper() == str(detail_evidence.get("sha256") or "").upper():
            return detail_sheep_pink_status(detail_path) == (True, True, True)
        return False

    def update(event_name, stage, status, detail="", mode=None, **kwargs):
        dp_normal = event_name == "逐影集趣" and mode == "normal" and str(stage).startswith("DP-")
        old = {}
        if dp_normal:
            old = (
                (((runtime._load_event_progress().get("events") or {}).get(event_name) or {})
                 .get("stages") or {}).get(stage) or {}
            )
        original_update(event_name, stage, status, detail, mode, **kwargs)
        if not dp_normal or not old:
            return
        old_mode = (old.get("modes") or {}).get("normal") or {}
        if old_mode.get("status") != "cleared":
            return
        data = runtime._load_event_progress()
        current = data["events"][event_name]["stages"][stage]
        current_mode = current["modes"]["normal"]
        if old_mode.get("evidence"):
            current_mode.setdefault("evidence", deepcopy(old_mode["evidence"]))
        if status != "cleared":
            # A failed recovery cannot erase an earlier genuine clear receipt.
            current_mode["status"] = "cleared"
            current_mode["last_perfect_attempt"] = {
                "status": status, "detail": detail,
                "at": datetime.now().isoformat(timespec="seconds"),
            }
            current["status"] = "cleared"
            current["detail"] = "已通关；完美通关仍待图形确认"
        else:
            last_stage, last_perfect = getattr(runtime, "_dp_v49_last_result", (None, None))
            path = getattr(runtime, "_dp_v49_last_result_path", "")
            if last_stage == stage and last_perfect and Path(path).is_file():
                current_mode["perfect_status"] = "verified"
                current_mode["perfect_evidence"] = {
                    "result_screenshot": path,
                    "result_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest().upper(),
                    "sheep": [True, True, True],
                }
        data["last_update"] = datetime.now().isoformat(timespec="seconds")
        runtime._atomic_write_json(runtime.EVENT_PROGRESS_FILE, data)
        runtime._RUN_SUMMARY.setdefault("event", {}).setdefault("stages", {})[stage] = deepcopy(current)

    runtime._victory_three_star_status = stars
    runtime._open_event_stage_detail = open_detail
    runtime.verify_event_stage_cleared = verify
    runtime._update_event_progress = update
    runtime._event_mode_has_trusted_clear_evidence = trusted
    runtime.clear_event_stage = clear_stage
    runtime._dp_perfect_result_v49_installed = True
    return runtime
