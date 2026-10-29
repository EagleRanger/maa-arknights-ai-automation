"""Restore the exact MAA 6.18.0 series resource shipped on this machine.

V60 removed ``FightSeries-OldMethodFlag`` and replaced the shipped geometry
with the experimental scrolling-list geometry.  The 2026-09-29 live run then
proved that MaaCore 6.18.0 entered ``select_series_new`` and returned
``times_finished=0`` after failing to analyse that list.  MaaCore's own source
uses the flag as the parser switch.  This adapter reverses only the three
previously changed records to their exact pre-V60, auto-update-backed values.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import maa_series_resource_v1 as v1


ROOT = Path(__file__).resolve().parent
DEFAULT_TASKS_PATH = v1.DEFAULT_TASKS_PATH
TASK_NAME = v1.TASK_NAME
SHIPPED_FLAG = dict(v1.OLD_FLAG)
SHIPPED_ICON = dict(v1.LEGACY_ICON)
SHIPPED_LIST = dict(v1.LEGACY_LIST)


class MaaSeriesResourceError(RuntimeError):
    pass


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def restore_shipped_series_resources(tasks_path=DEFAULT_TASKS_PATH, *, backup_dir=None):
    path = Path(tasks_path)
    if not path.is_file():
        raise MaaSeriesResourceError(f"MAA tasks file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MaaSeriesResourceError(f"MAA tasks JSON unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise MaaSeriesResourceError("MAA tasks JSON root is not an object")

    flag = data.get(TASK_NAME)
    icon = data.get("FightSeries-Icon")
    series_list = data.get("FightSeries-List-Multiply")
    if flag not in (None, SHIPPED_FLAG):
        raise MaaSeriesResourceError(f"conflicting {TASK_NAME}: {flag!r}")
    if icon not in (v1.NEW_ICON, SHIPPED_ICON):
        raise MaaSeriesResourceError(f"unknown FightSeries-Icon shape: {icon!r}")
    if series_list not in (v1.NEW_LIST, SHIPPED_LIST):
        raise MaaSeriesResourceError(f"unknown FightSeries-List-Multiply shape: {series_list!r}")

    before_sha = _digest(path)
    if flag == SHIPPED_FLAG and icon == SHIPPED_ICON and series_list == SHIPPED_LIST:
        return {
            "status": "already_restored",
            "path": str(path),
            "sha256": before_sha,
            "old_method_flag_present": True,
            "series_parser": "shipped_six_visible_items",
        }

    target_dir = Path(backup_dir or (ROOT / "outputs" / "maa_resource_backups"))
    target_dir.mkdir(parents=True, exist_ok=True)
    backup = target_dir / f"tasks.before_v65_{before_sha[:16]}.json"
    if not backup.exists():
        shutil.copy2(path, backup)
        if _digest(backup) != before_sha:
            raise MaaSeriesResourceError("MAA resource backup hash mismatch")

    data[TASK_NAME] = SHIPPED_FLAG
    data["FightSeries-Icon"] = SHIPPED_ICON
    data["FightSeries-List-Multiply"] = SHIPPED_LIST
    temp = path.with_name(f"{path.name}.v65.{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

    readback = json.loads(path.read_text(encoding="utf-8"))
    if not (
        readback.get(TASK_NAME) == SHIPPED_FLAG
        and readback.get("FightSeries-Icon") == SHIPPED_ICON
        and readback.get("FightSeries-List-Multiply") == SHIPPED_LIST
    ):
        raise MaaSeriesResourceError("MAA shipped-series resource read-back failed")
    return {
        "status": "restored_verified",
        "path": str(path),
        "backup": str(backup),
        "before_sha256": before_sha,
        "sha256": _digest(path),
        "old_method_flag_present": True,
        "series_parser": "shipped_six_visible_items",
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def install(runtime, *, tasks_path=DEFAULT_TASKS_PATH):
    result = restore_shipped_series_resources(tasks_path)
    runtime._RUN_SUMMARY.setdefault("maa_series_resource_v2", {}).update(result)
    runtime._maa_series_resource_v2_installed = True
    runtime.log("  [V65] MAA 6.18.0随包连战资源已恢复并读回: " + result["status"])
    return result
