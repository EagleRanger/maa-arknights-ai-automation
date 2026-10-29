"""V38: admit a DP clear checkpoint only after its saved images re-verify."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import dp_result_navigation_v37 as v37

EVENT_NAME = "逐影集趣"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _resolve_evidence_path(runtime, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = Path(runtime.BASE) / path
    try:
        path = path.resolve()
        path.relative_to(Path(runtime.BASE).resolve())
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


def _load_mode_state(runtime, event_name: str, stage_name: str, mode: str):
    try:
        data = json.loads(Path(runtime.EVENT_PROGRESS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return (
        (((data.get("events") or {}).get(event_name) or {}).get("stages") or {})
        .get(stage_name, {})
        .get("modes", {})
        .get(mode, {})
        or {}
    )


def _images_reverify_dp_clear(runtime, event_name: str, stage_name: str, mode: str) -> bool:
    if (
        event_name != EVENT_NAME
        or mode != "normal"
        or not re.fullmatch(r"DP-\d+", str(stage_name or ""))
    ):
        return False
    state = _load_mode_state(runtime, event_name, stage_name, mode)
    if state.get("status") != "cleared":
        return False
    evidence = state.get("evidence") or {}
    if evidence.get("schema") != "dp_result_plus_card_map_v1":
        return False
    receipt = _resolve_evidence_path(runtime, str(evidence.get("result_screenshot") or ""))
    card_map = _resolve_evidence_path(runtime, str(evidence.get("map_screenshot") or ""))
    if receipt is None or card_map is None:
        return False
    expected_receipt = str(evidence.get("result_sha256") or "").upper()
    expected_map = str(evidence.get("map_sha256") or "").upper()
    if not expected_receipt or not expected_map:
        return False
    if _sha256(receipt) != expected_receipt or _sha256(card_map) != expected_map:
        return False
    if v37._dp_result_stage(runtime.ocr(str(receipt))) != stage_name:
        return False
    return v37._is_dp_light_map(runtime.ocr(str(card_map)))


def install(runtime):
    if getattr(runtime, "_dp_progress_evidence_v38_installed", False):
        return runtime
    v37.install(runtime)
    original = runtime._event_mode_has_trusted_clear_evidence

    def trusted_clear(event_name, stage_name, mode):
        if original(event_name, stage_name, mode):
            return True
        cache_key = (event_name, stage_name, mode)
        cache = getattr(runtime, "_dp_v38_evidence_cache", {})
        if cache_key not in cache:
            cache[cache_key] = _images_reverify_dp_clear(
                runtime, event_name, stage_name, mode
            )
            runtime._dp_v38_evidence_cache = cache
        if cache[cache_key]:
            runtime.log(
                f"  [V38断点] {stage_name}结算截图与后继卡片地图重新核验通过"
            )
            return True
        return False

    runtime._event_mode_has_trusted_clear_evidence = trusted_clear
    runtime._dp_progress_evidence_v38_installed = True
    runtime.log("  [V38] DP历史断点双截图可信准入已安装")
    return runtime
