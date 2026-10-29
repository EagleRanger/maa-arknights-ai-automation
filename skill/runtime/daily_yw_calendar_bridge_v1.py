"""Narrow YW bridge for a lagging MAA map bundle and one observed OCR alias.

Only the normal YW section before the announced second-section opening is in
scope.  A current terminal card and unique, current MAA calendar entry are
still mandatory; pinned candidate data does not by itself prove a live page.
"""

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import hashlib
import json

import event_availability_v12 as availability
import yw_event_intake_v1 as intake
import vector_special_resources_v1 as resources


ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "outputs/yw_20261009/candidates/catalog.json"
MANIFEST = ROOT / "outputs/yw_20261009/admitted_candidates/candidate_manifest.json"
CATALOG_SHA256 = "F0BE6E6663C6C75B08549FAEC9FEFD37A08475FF2B9AFC68EEFF0B838516E264"
MANIFEST_SHA256 = "BF9D76FBA746AF5E7CE8BD670FC21FBD61369B95EA993ED635CD2123A8C1FA38"
SECOND_SECTION_OPENS = datetime(2026, 10, 16, 16, 0, tzinfo=timezone(timedelta(hours=8)))


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _current_story(stories, now):
    rows = []
    for row in stories or []:
        if intake.canonical_name(row.get("name")) != "昨日海" or row.get("key") != "YW":
            continue
        try:
            start = datetime.fromisoformat(row["start_utc"])
            end = datetime.fromisoformat(row["expire_utc"])
        except (KeyError, TypeError, ValueError):
            continue
        if start.tzinfo is not None and end.tzinfo is not None and start <= now < end:
            rows.append(row)
    return rows[0] if len(rows) == 1 else None


def admitted_event(name, stories, *, now=None, catalog_path=CATALOG,
                   manifest_path=MANIFEST, catalog_sha=CATALOG_SHA256,
                   manifest_sha=MANIFEST_SHA256):
    """Return metadata for *live navigation*, never a stage-clear assertion."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or intake.canonical_name(name) != "昨日海":
        return None
    if not now < SECOND_SECTION_OPENS or _current_story(stories, now) is None:
        return None
    if _digest(catalog_path) != catalog_sha or _digest(manifest_path) != manifest_sha:
        return None
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("status") != "offline_candidates_verified":
        return None
    event = intake.event_config(catalog, now)
    codes = [row["code"] for row in manifest.get("stages") or []]
    if codes != [f"YW-{n}" for n in range(1, 9)]:
        return None
    if {row["display"] for row in event["stages"]} != set(codes):
        return None
    event["_discovery_status"] = "ready_for_visual_navigation"
    event["_discovery_reason"] = "当前终端卡与唯一MAA活动日历相符；关卡地图和完成度仍须实图核验"
    event["_source"] = "pinned YW game data + unique current MAA calendar + live terminal OCR"
    # Observed activity lobby's mission entry, not the adjacent material shop.
    event["task_keywords"] = ["打捞方案"]
    return event


@contextmanager
def boundary(runtime):
    """Add the bridge around frozen V90 without editing its implementation."""
    original_discover = runtime.discover_event
    original_verify = runtime.verify_event_navigation_ready

    def discover(name, stories, maa_root, now=None):
        result = original_discover(name, stories, maa_root, now=now)
        if result and result.get("_discovery_status") == "ready_for_visual_navigation":
            return result
        try:
            candidate = admitted_event(name, stories, now=now)
        except (OSError, ValueError, KeyError, TypeError):
            candidate = None
        return candidate or result

    def verify(event=None):
        if (event or {}).get("_source") == "pinned YW game data + unique current MAA calendar + live terminal OCR":
            try:
                installed = resources.install(
                    str(ROOT), runtime.MAA_ROOT, str(MANIFEST),
                    queue_idle=lambda: not runtime._maa_task_queue_running(),
                )
                runtime._RUN_SUMMARY.setdefault("event", {})["pinned_resources"] = installed
                if installed.get("changed") and runtime._maa_process_exists() is True:
                    runtime.reload_maa_after_config_switch("昨日海地图资源已校验安装，空闲重载")
            except Exception as exc:
                runtime._RUN_SUMMARY.setdefault("event", {}).setdefault("navigation", {}).update(
                    status="failed", detail=f"昨日海地图资源未安全就绪：{type(exc).__name__}: {exc}"
                )
                runtime.log("昨日海地图资源未安全就绪；停止活动战斗", "ERROR")
                return False
        return original_verify(event)

    with patch.object(runtime, "discover_event", discover), patch.object(
        runtime, "verify_event_navigation_ready", verify
    ):
        yield
