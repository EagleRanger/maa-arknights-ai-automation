"""Skip live SSS navigation only while a fully verified cycle remains current.

The cache is volatile run state, not a second policy source.  A cache entry is
accepted only when all reward domains were closed by a real SSS sweep and both
the monthly reward window and the area period are still current.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, time
from pathlib import Path
from typing import Any

from sss_cycle_service_v1 import CST, reward_window


ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "outputs" / "sss_cycle_completion.json"
COMPONENT_ID = "ARK-SSS-CYCLE-SKIP-V1"


def _as_cst(value: datetime | str | None) -> datetime:
    if value is None:
        value = datetime.now(CST)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=CST)
    return value.astimezone(CST)


def _area_period_end(area_period: str) -> datetime | None:
    match = re.search(r"end-(\d{4}-\d{2}-\d{2})$", str(area_period or ""))
    if not match:
        return None
    day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
    return datetime.combine(day, time(4, 0), tzinfo=CST)


def _normalise_security(security: dict[str, Any]) -> dict[str, Any]:
    service = security.get("reward_service") or {}
    tasks = service.get("tasks") or {}
    records = service.get("records") or {}
    active_regions = sorted(str(item) for item in (security.get("active_regions") or []))
    normalised_records: dict[str, Any] = {}
    for region in active_regions:
        record = records.get(region) or {}
        rows = record.get("rows") or {}
        normalised_records[region] = {
            "verified": record.get("verified") is True,
            "claimable": record.get("claimable"),
            "rows": {
                str(stage): (rows.get(stage) or rows.get(str(stage)) or {}).get("state")
                for stage in range(1, 7)
            },
        }
    return {
        "reward_counts": security.get("reward_counts") or service.get("counts") or {},
        "active_regions": active_regions,
        "tasks": {
            "verified": tasks.get("verified") is True,
            "claimable": tasks.get("claimable"),
            "incomplete": tasks.get("incomplete"),
            "progress": tasks.get("progress") or {},
        },
        "records": normalised_records,
        "home_verified": service.get("home_verified") is True,
        "service_complete": service.get("complete") is True,
        "available_rewards_serviced": service.get("available_rewards_serviced") is True,
        "task_objectives_complete": service.get("task_objectives_complete") is True,
        "record_objectives_remaining": service.get("record_objectives_remaining") or [],
    }


def _security_is_complete(security: dict[str, Any]) -> bool:
    if security.get("status") != "completed":
        return False
    if security.get("reason") != "all_reward_domains_verified":
        return False
    evidence = _normalise_security(security)
    counts = evidence["reward_counts"]
    if counts.get("strip") != 60 or counts.get("device") != 24:
        return False
    regions = evidence["active_regions"]
    if not regions or set(evidence["records"]) != set(regions):
        return False
    tasks = evidence["tasks"]
    progress = tasks.get("progress") or {}
    if not (
        tasks.get("verified") is True
        and tasks.get("claimable") == 0
        and tasks.get("incomplete") == 0
        and isinstance(progress.get("total"), int)
        and progress.get("total", 0) > 0
        and progress.get("completed") == progress.get("total")
    ):
        return False
    if not (
        evidence["home_verified"]
        and evidence["service_complete"]
        and evidence["available_rewards_serviced"]
        and evidence["task_objectives_complete"]
        and not evidence["record_objectives_remaining"]
    ):
        return False
    return all(
        record.get("verified") is True
        and record.get("claimable") == 0
        and set(record.get("rows") or {}) == {str(stage) for stage in range(1, 7)}
        and all(state in {"completed", "claimed"} for state in record["rows"].values())
        for record in evidence["records"].values()
    )


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()


def build_completion_cache(
    security: dict[str, Any],
    *,
    completed_at: datetime | str | None = None,
    source_report: str | None = None,
    source_report_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a cache record only from a completely closed live SSS result."""
    if not _security_is_complete(security):
        raise ValueError("SSS result is not a fully verified cycle closeout")
    completed = _as_cst(completed_at)
    window = reward_window(completed)
    if security.get("reward_cycle") != window["id"]:
        raise ValueError("SSS result reward cycle disagrees with completion time")
    area_period = str(security.get("period") or "")
    area_end = _area_period_end(area_period)
    if area_end is None or completed >= area_end:
        raise ValueError("SSS area period has no usable future refresh boundary")
    reward_end = datetime.fromisoformat(window["end"])
    valid_until = min(reward_end, area_end)
    evidence = _normalise_security(security)
    return {
        "schema_version": 1,
        "kind": "sss_cycle_completion",
        "status": "completed_verified",
        "component_id": COMPONENT_ID,
        "completed_at": completed.isoformat(),
        "reward_cycle": window["id"],
        "reward_valid_until": reward_end.isoformat(),
        "area_period": area_period,
        "area_valid_until": area_end.isoformat(),
        "skip_valid_until": valid_until.isoformat(),
        "security_evidence": evidence,
        "security_evidence_sha256": _digest(evidence),
        "source_report": source_report,
        "source_report_sha256": source_report_sha256,
    }


def write_completion_cache(
    security: dict[str, Any],
    *,
    completed_at: datetime | str | None = None,
    cache_path: Path = CACHE_PATH,
) -> dict[str, Any]:
    """Atomically persist a newly verified closeout after a real live sweep."""
    data = build_completion_cache(security, completed_at=completed_at)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, cache_path)
    return data


def _source_report_matches(cache: dict[str, Any], root: Path) -> bool:
    source = cache.get("source_report")
    expected_hash = cache.get("source_report_sha256")
    if not source and not expected_hash:
        return True
    if not source or not expected_hash:
        return False
    try:
        path = (root / source).resolve()
        path.relative_to(root.resolve())
        if hashlib.sha256(path.read_bytes()).hexdigest().upper() != str(expected_hash).upper():
            return False
        report = json.loads(path.read_text(encoding="utf-8"))
        security = report.get("security") or (report.get("run_summary") or {}).get("security") or {}
    except (OSError, ValueError, TypeError):
        return False
    return _security_is_complete(security) and _normalise_security(security) == cache.get("security_evidence")


def evaluate_completion_cache(
    *,
    at: datetime | str | None = None,
    root: Path = ROOT,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Return a read-only skip decision; any uncertainty forces a live audit."""
    now = _as_cst(at)
    path = cache_path or (root / "outputs" / "sss_cycle_completion.json")
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"skip": False, "reason": "completion_cache_missing_or_invalid", "checked_at": now.isoformat()}

    required = {
        "schema_version": 1,
        "kind": "sss_cycle_completion",
        "status": "completed_verified",
        "component_id": COMPONENT_ID,
    }
    if any(cache.get(key) != value for key, value in required.items()):
        return {"skip": False, "reason": "completion_cache_identity_mismatch", "checked_at": now.isoformat()}
    evidence = cache.get("security_evidence")
    if not isinstance(evidence, dict) or _digest(evidence) != cache.get("security_evidence_sha256"):
        return {"skip": False, "reason": "completion_cache_evidence_mismatch", "checked_at": now.isoformat()}
    if not _source_report_matches(cache, root):
        return {"skip": False, "reason": "completion_source_report_mismatch", "checked_at": now.isoformat()}
    try:
        completed = _as_cst(cache["completed_at"])
        reward_end = _as_cst(cache["reward_valid_until"])
        area_end = _as_cst(cache["area_valid_until"])
        skip_until = _as_cst(cache["skip_valid_until"])
    except (KeyError, TypeError, ValueError):
        return {"skip": False, "reason": "completion_cache_time_invalid", "checked_at": now.isoformat()}
    window = reward_window(now)
    if cache.get("reward_cycle") != window["id"] or reward_end != _as_cst(window["end"]):
        return {"skip": False, "reason": "monthly_reward_cycle_refreshed", "checked_at": now.isoformat()}
    if area_end != _area_period_end(str(cache.get("area_period") or "")):
        return {"skip": False, "reason": "area_period_boundary_mismatch", "checked_at": now.isoformat()}
    if skip_until != min(reward_end, area_end):
        return {"skip": False, "reason": "earliest_refresh_boundary_mismatch", "checked_at": now.isoformat()}
    if now < completed or now >= skip_until:
        return {"skip": False, "reason": "sss_refresh_due", "checked_at": now.isoformat(), "valid_until": skip_until.isoformat()}
    return {
        "skip": True,
        "reason": "current_sss_cycle_already_verified",
        "checked_at": now.isoformat(),
        "valid_until": skip_until.isoformat(),
        "reward_cycle": cache["reward_cycle"],
        "area_period": cache["area_period"],
        "reward_counts": evidence["reward_counts"],
        "active_regions": evidence["active_regions"],
        "source_report": cache.get("source_report"),
    }


def cached_security_summary(decision: dict[str, Any]) -> dict[str, Any]:
    """Report a truthful local skip without claiming that today's UI was scanned."""
    return {
        "status": "completed",
        "reason": "current_cycle_already_verified_skip_until_refresh",
        "skipped_cached": True,
        "live_page_visited": False,
        "period": decision.get("area_period"),
        "reward_cycle": decision.get("reward_cycle"),
        "reward_counts": decision.get("reward_counts") or {},
        "active_regions": decision.get("active_regions") or [],
        "cache_valid_until": decision.get("valid_until"),
        "reward_service": {
            "cached_cycle_complete": True,
            "available_rewards_serviced": False,
            "tasks_remaining": 0,
        },
        "battle_started": False,
    }
