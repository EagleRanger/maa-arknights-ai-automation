"""Align MAA 6.18.x with the game's ten-entry proxy series list.

The historical V23 compatibility shim intentionally inserted
``FightSeries-OldMethodFlag``.  MaaCore 6.18 uses the *presence* of that task
as a feature flag for the retired six-entry parser.  The live game now exposes
ten entries, so keeping the flag makes every explicit/AUTO series change fail.

This adapter accepts only the exact historical definitions observed in this
project (or the exact 2026-09-28 upstream definitions), creates an immutable
backup, removes the obsolete flag and updates the two geometry records used by
the new parser.  Unknown resource shapes fail closed.
"""

from __future__ import annotations
from portable_paths import resolve_path as _portable_path

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TASK_NAME = "FightSeries-OldMethodFlag"
DEFAULT_TASKS_PATH = Path(
    _portable_path('maa', 'resource/tasks/tasks.json')
)
OLD_FLAG = {"algorithm": "JustReturn", "doc": "whether to use old series method"}

LEGACY_ICON = {
    "doc": "代理指挥左侧的代理倍率乘号, rectMove为乘号到次数偏移",
    "method": "RGBCount",
    "colorScales": [[30, 70]],
    "roi": [927, 567, 122, 66],
    "rectMove": [20, -10, 32, 32],
}
NEW_ICON = {
    "doc": "代理指挥左侧的连战乘号, rectMove为乘号到次数偏移",
    "method": "RGBCount",
    "colorScales": [[30, 70]],
    "roi": [927, 567, 122, 66],
    "rectMove": [27, -10, 25, 32],
}
LEGACY_LIST = {
    "Doc": "代理倍率列表每个选项的乘号, rectMove到次数, 灰度低于150为碎石才能打",
    "action": "ClickRect",
    "roi": [960, 200, 40, 360],
    "rectMove": [25, 13, 32, 25],
    "specificRect": [0, -1, 75, 45],
    "specialParams": [150],
}
NEW_LIST = {
    "Doc": "连战次数列表每个选项的乘号, rectMove到次数, 灰度低于150为碎石才能打",
    "action": "ClickRect",
    "roi": [970, 200, 40, 360],
    "rectMove": [25, 10, 20, 25],
    "specificRect": [0, 0, 55, 40],
    "specialParams": [150],
}


class MaaSeriesResourceError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def align_new_series_resources(tasks_path=DEFAULT_TASKS_PATH, *, backup_dir=None):
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
    if flag not in (None, OLD_FLAG):
        raise MaaSeriesResourceError(f"conflicting {TASK_NAME}: {flag!r}")
    if icon not in (LEGACY_ICON, NEW_ICON):
        raise MaaSeriesResourceError(f"unknown FightSeries-Icon shape: {icon!r}")
    if series_list not in (LEGACY_LIST, NEW_LIST):
        raise MaaSeriesResourceError(
            f"unknown FightSeries-List-Multiply shape: {series_list!r}"
        )

    before_sha = _digest(path)
    if flag is None and icon == NEW_ICON and series_list == NEW_LIST:
        return {
            "status": "already_aligned",
            "path": str(path),
            "sha256": before_sha,
            "old_method_flag_present": False,
            "series_parser": "new_10_entry",
        }

    target_dir = Path(backup_dir or (ROOT / "outputs" / "maa_resource_backups"))
    target_dir.mkdir(parents=True, exist_ok=True)
    backup = target_dir / f"tasks.before_v60_{before_sha[:16]}.json"
    if not backup.exists():
        shutil.copy2(path, backup)
        if _digest(backup) != before_sha:
            raise MaaSeriesResourceError("MAA resource backup hash mismatch")

    data.pop(TASK_NAME, None)
    data["FightSeries-Icon"] = dict(NEW_ICON)
    data["FightSeries-List-Multiply"] = dict(NEW_LIST)
    temp = path.with_name(f"{path.name}.v60.{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()

    readback = json.loads(path.read_text(encoding="utf-8"))
    if (
        TASK_NAME in readback
        or readback.get("FightSeries-Icon") != NEW_ICON
        or readback.get("FightSeries-List-Multiply") != NEW_LIST
    ):
        raise MaaSeriesResourceError("MAA new-series resource read-back failed")
    return {
        "status": "aligned_verified",
        "path": str(path),
        "backup": str(backup),
        "before_sha256": before_sha,
        "sha256": _digest(path),
        "old_method_flag_present": False,
        "series_parser": "new_10_entry",
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def install(runtime, *, tasks_path=DEFAULT_TASKS_PATH):
    result = align_new_series_resources(tasks_path)
    runtime._RUN_SUMMARY.setdefault("maa_series_resource_v1", {}).update(result)
    runtime._maa_series_resource_v1_installed = True
    runtime.log(
        "  [V60] MAA十档连战资源已读回核验: " + result["status"]
    )
    return result
