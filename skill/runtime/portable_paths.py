"""Resolve installation defaults on the receiving PC; never install or launch software."""
from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(__file__).resolve().parent


def resolve_path(kind, relative=""):
    if kind == "python":
        if relative:
            raise ValueError("Python selection does not take a relative path")
        return os.environ.get("ARKNIGHTS_PYTHON") or sys.executable
    if kind == "project":
        root = PROJECT_ROOT
    elif kind == "maa":
        selected = os.environ.get("ARKNIGHTS_MAA_ROOT") or os.environ.get("ARKNIGHTS_MAA_PATH")
        if selected:
            root = Path(selected).expanduser()
            if root.suffix.lower() == ".exe":
                root = root.parent
        else:
            local = os.environ.get("LOCALAPPDATA")
            root = (Path(local) if local else Path.home() / "AppData" / "Local") / "MAA-App"
    elif kind == "mumu":
        selected = os.environ.get("ARKNIGHTS_MUMU_ROOT")
        programs = os.environ.get("ProgramFiles") or (os.environ.get("SystemDrive", "C:") + "\\Program Files")
        root = Path(selected) if selected else Path(programs) / "Netease" / "MuMuPlayer-12.0"
    elif kind == "user":
        root = Path.home()
    else:
        raise ValueError("Unknown installation path kind: " + str(kind))
    relative = str(relative).replace("\\", "/")
    parts = Path(relative)
    if parts.is_absolute() or ".." in parts.parts or ":" in relative:
        raise ValueError("Expected a relative path within the selected installation")
    return str(root / parts)
