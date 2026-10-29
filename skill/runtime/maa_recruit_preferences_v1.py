"""Keep MAA automatic recruitment configured to accept 5-star and 6-star tags."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path.home() / "AppData" / "Local" / "MAA-App" / "config" / "gui.new.json"


def inspect_preferences(data: dict[str, Any]) -> dict[str, Any]:
    configurations = data.get("Configurations") or {}
    rows = []
    for name, configuration in configurations.items():
        for index, task in enumerate(configuration.get("TaskQueue") or []):
            if task.get("$type") == "RecruitTask" or task.get("TaskType") == "Recruit":
                rows.append(
                    {
                        "configuration": name,
                        "index": index,
                        "level5": task.get("Level5Choose") is True,
                        "level6": task.get("Level6Choose") is True,
                    }
                )
    return {
        "verified": bool(rows) and all(row["level5"] and row["level6"] for row in rows),
        "recruit_tasks": rows,
    }


def ensure_preferences(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    """Atomically enable both options in every saved MAA configuration."""
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    before = inspect_preferences(data)
    if not before["recruit_tasks"]:
        raise ValueError("MAA configuration contains no automatic recruitment task")
    changed = False
    for configuration in (data.get("Configurations") or {}).values():
        for task in configuration.get("TaskQueue") or []:
            if task.get("$type") == "RecruitTask" or task.get("TaskType") == "Recruit":
                for key in ("Level5Choose", "Level6Choose"):
                    if task.get(key) is not True:
                        task[key] = True
                        changed = True
    if changed:
        temporary = config_path.with_suffix(config_path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, config_path)
    after_data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    after = inspect_preferences(after_data)
    if not after["verified"]:
        raise ValueError("MAA automatic recruitment preferences failed read-back verification")
    return {"status": "verified", "changed": changed, "before": before, "after": after}
