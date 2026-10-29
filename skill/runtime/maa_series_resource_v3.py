"""Use MaaCore's dynamic parser with the live-proven shipped geometry.

The V65 live run showed that the shipped matcher geometry detects five visible
items at x=965, while the old parser rejects anything other than six items.
The earlier V60 geometry started at x=970 and therefore clipped every detected
multiplier before the dynamic parser could OCR it.  The minimal compatible
state is consequently: no old-parser flag, but the shipped icon/list geometry.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import maa_series_resource_v1 as v1
import maa_series_resource_v2 as v2


ROOT = Path(__file__).resolve().parent
DEFAULT_TASKS_PATH = v1.DEFAULT_TASKS_PATH
TASK_NAME = v1.TASK_NAME
TARGET_ICON = dict(v2.SHIPPED_ICON)
TARGET_LIST = dict(v2.SHIPPED_LIST)


class MaaSeriesResourceError(RuntimeError):
    pass


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def align_dynamic_parser_with_live_geometry(tasks_path=DEFAULT_TASKS_PATH, *, backup_dir=None):
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
    if flag not in (None, v2.SHIPPED_FLAG):
        raise MaaSeriesResourceError(f"conflicting {TASK_NAME}: {flag!r}")
    if icon not in (v1.NEW_ICON, TARGET_ICON):
        raise MaaSeriesResourceError(f"unknown FightSeries-Icon shape: {icon!r}")
    if series_list not in (v1.NEW_LIST, TARGET_LIST):
        raise MaaSeriesResourceError(f"unknown FightSeries-List-Multiply shape: {series_list!r}")

    before_sha = _digest(path)
    if flag is None and icon == TARGET_ICON and series_list == TARGET_LIST:
        return {
            "status": "already_aligned",
            "path": str(path),
            "sha256": before_sha,
            "old_method_flag_present": False,
            "series_parser": "dynamic_visible_items_with_live_geometry",
        }

    target_dir = Path(backup_dir or (ROOT / "outputs" / "maa_resource_backups"))
    target_dir.mkdir(parents=True, exist_ok=True)
    backup = target_dir / f"tasks.before_v66_{before_sha[:16]}.json"
    if not backup.exists():
        shutil.copy2(path, backup)
        if _digest(backup) != before_sha:
            raise MaaSeriesResourceError("MAA resource backup hash mismatch")

    data.pop(TASK_NAME, None)
    data["FightSeries-Icon"] = TARGET_ICON
    data["FightSeries-List-Multiply"] = TARGET_LIST
    temp = path.with_name(f"{path.name}.v66.{os.getpid()}.tmp")
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
        TASK_NAME not in readback
        and readback.get("FightSeries-Icon") == TARGET_ICON
        and readback.get("FightSeries-List-Multiply") == TARGET_LIST
    ):
        raise MaaSeriesResourceError("MAA dynamic/live-geometry resource read-back failed")
    return {
        "status": "aligned_verified",
        "path": str(path),
        "backup": str(backup),
        "before_sha256": before_sha,
        "sha256": _digest(path),
        "old_method_flag_present": False,
        "series_parser": "dynamic_visible_items_with_live_geometry",
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def install(runtime, *, tasks_path=DEFAULT_TASKS_PATH):
    result = align_dynamic_parser_with_live_geometry(tasks_path)
    runtime._RUN_SUMMARY.setdefault("maa_series_resource_v3", {}).update(result)
    runtime._maa_series_resource_v3_installed = True
    runtime.log("  [V66] MAA动态连战解析与实机几何已组合并读回: " + result["status"])
    return result
