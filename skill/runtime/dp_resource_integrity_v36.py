"""V36 repair for the pinned DP tile resources installed by V26.

V26 copied the official per-stage JSON files, but synthesized each
``overview.json`` row with only three fields.  MaaCore requires the complete
seven-field tile metadata and rejects the partial rows with
``invalid map<K, T> key``.  This module rebuilds only the pinned DP rows from
the already hash-verified official stage payloads, preserving all unrelated
MAA resources and keeping a reversible backup.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.parse

import dp_event_route_v26 as v26


OVERVIEW_FIELDS = ("code", "filename", "height", "levelId", "name", "stageId", "width")


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _entry_from_payload(payload: dict, filename: str) -> dict:
    entry = {
        "code": payload.get("code"),
        "filename": filename,
        "height": payload.get("height"),
        "levelId": payload.get("levelId"),
        "name": payload.get("name"),
        "stageId": payload.get("stageId"),
        "width": payload.get("width"),
    }
    if (
        not all(entry.get(field) not in (None, "") for field in OVERVIEW_FIELDS)
        or not isinstance(entry["height"], int)
        or not isinstance(entry["width"], int)
    ):
        raise RuntimeError(f"DP tile metadata incomplete: {filename}")
    return entry


def probe_dp_resources(maa_root) -> dict:
    root = v26._resource_dir(maa_root)
    overview_path = root / "overview.json"
    result = {
        "status": "missing",
        "official_commit": v26.OFFICIAL_COMMIT,
        "resource_dir": str(root),
        "expected_files": len(v26.DP_RESOURCE_SPECS),
        "valid_files": 0,
        "invalid": [],
    }
    try:
        overview = json.loads(overview_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        result["invalid"].append(f"overview:{type(exc).__name__}")
        return result
    for key, code, stage_id, filename, sha256 in v26.DP_RESOURCE_SPECS:
        path = root / filename
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8-sig"))
            expected = _entry_from_payload(payload, filename)
        except (OSError, UnicodeDecodeError, ValueError, RuntimeError) as exc:
            result["invalid"].append(f"{filename}:{type(exc).__name__}")
            continue
        if v26._digest(raw) != sha256:
            result["invalid"].append(filename + ":sha256")
            continue
        if payload.get("code") != code or payload.get("stageId") != stage_id:
            result["invalid"].append(filename + ":identity")
            continue
        if overview.get(key) != expected:
            result["invalid"].append(key + ":overview_shape")
            continue
        result["valid_files"] += 1
    if not result["invalid"]:
        result["status"] = "ready"
    return result


def ensure_dp_resources(maa_root, *, fetch=None, now=None) -> dict:
    """Repair the pinned DP subset and retain a complete reversible backup."""
    before = probe_dp_resources(maa_root)
    if before["status"] == "ready":
        return {**before, "changed": False, "backup": None}

    fetch = fetch or v26._download
    root = v26._resource_dir(maa_root)
    overview_path = root / "overview.json"
    if not overview_path.is_file():
        raise RuntimeError(f"MAA overview missing: {overview_path}")
    overview = json.loads(overview_path.read_text(encoding="utf-8-sig"))
    replacements = {}
    entries = {}
    for key, code, stage_id, filename, sha256 in v26.DP_RESOURCE_SPECS:
        path = root / filename
        raw = path.read_bytes() if path.is_file() else b""
        if not raw or v26._digest(raw) != sha256:
            raw = fetch(v26.RESOURCE_BASE + urllib.parse.quote(filename, safe=""))
        if v26._digest(raw) != sha256:
            raise RuntimeError(f"Official DP resource hash mismatch: {filename}")
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError(f"Official DP resource is not JSON: {filename}") from exc
        if payload.get("code") != code or payload.get("stageId") != stage_id:
            raise RuntimeError(f"Official DP resource identity mismatch: {filename}")
        replacements[filename] = raw
        entries[key] = _entry_from_payload(payload, filename)

    now = now or datetime.now().astimezone()
    backup = Path(maa_root) / ".codex-resource-backups" / (
        "dp-v36-" + now.strftime("%Y%m%d-%H%M%S-%f")
    )
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(overview_path, backup / "overview.json")
    existing = set()
    for filename in replacements:
        path = root / filename
        if path.is_file():
            existing.add(filename)
            shutil.copy2(path, backup / filename)

    try:
        for filename, raw in replacements.items():
            v26._atomic_bytes(root / filename, raw)
        overview.update(entries)
        _atomic_json(overview_path, overview)
        after = probe_dp_resources(maa_root)
        if after["status"] != "ready":
            raise RuntimeError(f"DP resource V36 validation failed: {after}")
    except Exception:
        shutil.copy2(backup / "overview.json", overview_path)
        for filename in replacements:
            saved = backup / filename
            target = root / filename
            if filename in existing:
                shutil.copy2(saved, target)
            elif target.exists():
                target.unlink()
        raise
    return {
        **after,
        "changed": True,
        "backup": str(backup),
        "repair": "complete_overview_rows_from_pinned_stage_payloads",
    }


def install(runtime):
    if getattr(runtime, "_dp_resource_integrity_v36_installed", False):
        return runtime
    receipt = ensure_dp_resources(runtime._maa_install_root())
    runtime._RUN_SUMMARY["dp_resource_sync_v36"] = receipt
    runtime._dp_resource_integrity_v36_installed = True
    runtime.log(
        "  [V36资源] DP地图overview完整元数据已核验"
        + (f"并修复，备份={receipt['backup']}" if receipt.get("changed") else "")
    )
    return runtime
