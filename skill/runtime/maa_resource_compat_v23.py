"""Narrow MAA 6.17.5 resource compatibility preflight for Bilibili resources.

The base CN task bundle can miss ``FightSeries-OldMethodFlag`` even though the
same installed build ships the task in every international/client overlay.
MAA then logs ``Unknown task`` and may enter the fragile series-icon detector.
This module adds only the upstream-equivalent ``JustReturn`` task, with an
immutable backup and read-back verification.  A conflicting existing task is
never overwritten.
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
EXPECTED_TASK = {
    "algorithm": "JustReturn",
    "doc": "whether to use old series method",
}
DEFAULT_TASKS_PATH = Path(
    _portable_path('maa', 'resource/tasks/tasks.json')
)


class MaaResourceCompatibilityError(RuntimeError):
    """Fail closed before MAA/game startup when the resource cannot be proven."""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def ensure_fight_series_old_method_flag(
    tasks_path: Path | str = DEFAULT_TASKS_PATH,
    *,
    backup_dir: Path | str | None = None,
) -> dict:
    """Ensure the exact shipped overlay task exists in the active base bundle."""

    path = Path(tasks_path)
    if not path.is_file():
        raise MaaResourceCompatibilityError(f"MAA tasks file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MaaResourceCompatibilityError(f"MAA tasks JSON unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise MaaResourceCompatibilityError("MAA tasks JSON root is not an object")

    existing = data.get(TASK_NAME)
    before_sha = _digest(path)
    if existing is not None:
        if existing != EXPECTED_TASK:
            raise MaaResourceCompatibilityError(
                f"{TASK_NAME} exists with a conflicting definition: {existing!r}"
            )
        return {
            "status": "already_compatible",
            "path": str(path),
            "sha256": before_sha,
            "task": dict(EXPECTED_TASK),
        }

    target_backup_dir = Path(backup_dir or (ROOT / "outputs" / "maa_resource_backups"))
    target_backup_dir.mkdir(parents=True, exist_ok=True)
    backup = target_backup_dir / f"tasks.before_v23_{before_sha[:16]}.json"
    if not backup.exists():
        shutil.copy2(path, backup)
        if _digest(backup) != before_sha:
            raise MaaResourceCompatibilityError("MAA tasks backup hash mismatch")

    data[TASK_NAME] = dict(EXPECTED_TASK)
    temp = path.with_name(f"{path.name}.v23.{os.getpid()}.tmp")
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
    if readback.get(TASK_NAME) != EXPECTED_TASK:
        raise MaaResourceCompatibilityError("MAA task compatibility read-back failed")
    return {
        "status": "patched_verified",
        "path": str(path),
        "backup": str(backup),
        "before_sha256": before_sha,
        "sha256": _digest(path),
        "task": dict(EXPECTED_TASK),
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def install(runtime, *, tasks_path: Path | str = DEFAULT_TASKS_PATH) -> dict:
    """Run the preflight once and expose its evidence to the daily report."""

    if getattr(runtime, "_maa_resource_compat_v23_installed", False):
        return runtime._RUN_SUMMARY.get("maa_resource_compat_v23") or {}
    result = ensure_fight_series_old_method_flag(tasks_path)
    runtime._RUN_SUMMARY.setdefault("maa_resource_compat_v23", {}).update(result)
    runtime._maa_resource_compat_v23_installed = True
    runtime.log(
        "  [V23] MAA连续代理资源兼容门已读回核验: " + result["status"]
    )
    return result
