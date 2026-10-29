"""Bind the daily controller to a project-local, writable portable MAA copy.

The installed AppData MAA is readable but its config ACL is read-only for the
scheduled execution identity.  Never mutate that installation or grant broad
permissions to it.  A portable copy keeps GUI, config, resources and logs in
the same writable tree, so the existing MAA evidence parser still applies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
PORTABLE_ROOT = ROOT / ".runtime_maa" / "MAA-App"


def preflight(root=PORTABLE_ROOT, *, write_probe=True):
    root = Path(root).resolve()
    root.relative_to(ROOT.resolve())
    required = (
        "MAA.exe", "MAA.dll", "MaaCore.dll", "config/gui.new.json",
        "resource/item_index.json",
    )
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise RuntimeError("portable MAA missing: " + ", ".join(missing))
    if not (root / "resource/tasks").is_dir():
        raise RuntimeError("portable MAA task resources are missing")
    config = json.loads((root / "config/gui.new.json").read_text(encoding="utf-8"))
    if not (root / "DirectML.dll").is_file():
        # This optional GPU provider is blocked by local endpoint protection.
        # A CPU-configured GUI was launched successfully from this copy.
        if '"UseGpu": false' not in (root / "config/gui.new.json").read_text(encoding="utf-8"):
            raise RuntimeError("portable MAA lacks DirectML while GPU use is not disabled")
    if not isinstance(config, dict):
        raise RuntimeError("portable MAA GUI config is not an object")
    if write_probe:
        probe = root / "config" / (".codex-write-probe-" + uuid4().hex)
        try:
            with probe.open("x", encoding="utf-8") as stream:
                stream.write("portable MAA config write probe\n")
        finally:
            probe.unlink(missing_ok=True)
    return {"root": str(root), "config_writable": bool(write_probe),
            "gpu_provider_present": (root / "DirectML.dll").is_file()}


def bind(runtime, root=PORTABLE_ROOT):
    result = preflight(root)
    root = Path(result["root"])
    runtime.MAA_ROOT = str(root)
    runtime.MAA_PATH = str(root / "MAA.exe")
    runtime.MAA_CONFIG = str(root / "config")
    runtime.MAA_LOG = str(root / "debug/asst.log")
    runtime.MAA_GUI_LOG = str(root / "debug/gui.log")
    runtime.MAA_STAGE_ACTIVITY_CACHE = str(root / "cache/gui/StageActivityV2.json")
    runtime.MAA_DEPOT_CACHE = str(root / "data/DepotData.json")
    runtime.MAA_ITEM_INDEX = str(root / "resource/item_index.json")
    return result
