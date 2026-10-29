"""Daily V19: run the frozen V18 workflow only in its verified Python runtime.

The 2026-09-20 pre-04:00 continuation exposed a launcher boundary defect: a
minimal interpreter could import package namespaces during the preflight but
could not import ``PIL.Image`` or ``RapidOCR`` later.  It then failed before
the emulator was ready, while the report could still display same-game-day
historical Fight evidence.  V19 makes the runtime identity and the actual
symbols an admission gate *before* importing any V18 layer or touching MAA.

V18 remains frozen.  This entry either re-execs itself through the verified
WorkBuddy environment, or fails before all game/MAA effects with a precise
error.  ``--check-only`` takes the same route so it proves the runtime that a
real launch would use.
"""

from __future__ import annotations
from portable_paths import resolve_path as _portable_path

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = "run_daily_v19.py --mode full"
LIVE_PYTHON = Path(
    _portable_path('python')
)
REEXEC_MARKER = "ARKNIGHTS_DAILY_V19_REEXEC"


def _runtime_probe():
    """Return a diagnostic-only readiness record without any game action."""

    result = {
        "executable": str(Path(sys.executable).resolve()),
        "preferred_executable": str(LIVE_PYTHON),
        "preferred": False,
        "symbols_ready": False,
        "error": None,
    }
    try:
        result["preferred"] = Path(sys.executable).resolve() == LIVE_PYTHON.resolve()
    except OSError:
        result["preferred"] = False
    try:
        from PIL import Image
        from rapidocr_onnxruntime import RapidOCR
        import uiautomation

        if not callable(getattr(Image, "open", None)):
            raise TypeError("PIL.Image.open is unavailable")
        if not callable(RapidOCR):
            raise TypeError("rapidocr_onnxruntime.RapidOCR is unavailable")
        if not getattr(uiautomation, "__file__", None):
            raise TypeError("uiautomation module path is unavailable")
        result["symbols_ready"] = True
    except Exception as exc:  # this record is used only to block safely
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _ensure_verified_runtime(argv=None, *, execve=os.execve, environ=None):
    """Re-exec once into the verified environment or fail before V18 imports."""

    args = list(sys.argv[1:] if argv is None else argv)
    probe = _runtime_probe()
    if probe["preferred"] and probe["symbols_ready"]:
        return probe
    if not LIVE_PYTHON.is_file():
        raise RuntimeError(f"Verified daily Python is missing: {LIVE_PYTHON}")
    environment = dict(os.environ if environ is None else environ)
    # The legacy scheduler injected CPython-3.12 private wheels into whichever
    # interpreter it chose.  That let namespace imports pass while native OCR
    # symbols later failed.  V19 owns one verified environment instead.
    environment.pop("PYTHONPATH", None)
    if environment.get(REEXEC_MARKER) == "1":
        raise RuntimeError(
            "Verified daily Python still lacks live OCR/UIA symbols: "
            + (probe["error"] or "interpreter identity mismatch")
        )
    environment[REEXEC_MARKER] = "1"
    command = [str(LIVE_PYTHON), str(Path(__file__).resolve()), *args]
    execve(str(LIVE_PYTHON), command, environment)
    raise AssertionError("os.execve unexpectedly returned")


def check_entry(at=None):
    """Read-only V19 production admission; it never opens a game."""
    from production_component_gate import resolve_production_recipes
    from sss_cycle_service_v1 import reward_window

    handoff = json.loads(
        (ROOT / ".project-reasoning" / "AUTOMATION_HANDOFF.json").read_text(
            encoding="utf-8"
        )
    )
    contract = json.loads((ROOT / "PROJECT_CONTRACT.json").read_text(encoding="utf-8"))
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Stable daily V19 entry is not the active production route")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("Current user contract and daily V19 route disagree")
    gate = resolve_production_recipes(
        ROOT / ".project-reasoning" / "COMPONENTS.json", handoff["required_recipes"]
    )
    registry = json.loads(
        (ROOT / ".project-reasoning" / "COMPONENTS.json").read_text(encoding="utf-8")
    )
    component_ids = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in registry["components"]:
        if component["id"] not in component_ids:
            continue
        for artifact in component.get("artifacts", []):
            path = (ROOT / artifact["path"]).resolve()
            path.relative_to(ROOT)
            actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            if actual != artifact["sha256"].upper():
                raise ValueError("Production artifact changed: " + artifact["path"])
    actual_entry = hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper()
    if actual_entry != handoff["production_snapshot_sha256"].upper():
        raise ValueError("Daily V19 entry snapshot changed")
    now = at or datetime.now().astimezone()
    return {
        "status": "PASS",
        "entrypoint": handoff["entrypoint"],
        "checked_at": now.isoformat(),
        "sss_window": reward_window(now),
        "runtime": _runtime_probe(),
        "runtime_policy": "verified_workbuddy_python_and_symbol_imports_before_game_control",
        "game_actions": 0,
    }


def main():
    _ensure_verified_runtime()
    import run_daily as base
    import run_daily_v18 as v18

    # V19 admits the reviewed current engine bundle itself.  The frozen V18
    # gate remains intact; this override applies only after V19's own route
    # and artifact gate have passed.
    base.ENGINE_SHA256 = hashlib.sha256(
        (ROOT / "arknights_daily_runtime_v12.py").read_bytes()
    ).hexdigest().upper()
    base.check_entry = check_entry
    v18.check_entry = check_entry
    return v18.main()


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    _ensure_verified_runtime(args)
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())
