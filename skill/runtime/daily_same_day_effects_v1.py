"""Recover only directly evidenced same-game-day stamina use across continuations."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path


def _game_day(value: datetime) -> str:
    return (value - timedelta(hours=4)).date().isoformat()


def load_verified_activity(root, *, now=None):
    """Return a same-day activity only when its screenshot and cost record exist."""
    root = Path(root)
    now = now or datetime.now().astimezone()
    candidates = []
    for path in sorted((root / "outputs" / "run_manifests").glob("daily-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(str(payload.get("created_at") or ""))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if _game_day(created) != _game_day(now):
            continue
        stamina = ((payload.get("run_summary") or {}).get("stamina") or {})
        cost = stamina.get("verified_cost")
        runs = stamina.get("fight_times")
        stage = stamina.get("stage")
        evidence = stamina.get("evidence")
        if not (
            isinstance(cost, int)
            and cost > 0
            and isinstance(runs, int)
            and runs > 0
            and stage
            and evidence
        ):
            continue
        evidence_path = Path(evidence)
        if not evidence_path.is_absolute():
            evidence_path = root / evidence_path
        if not evidence_path.is_file():
            continue
        if cost % runs:
            continue
        candidates.append(
            {
                "game_day": _game_day(now),
                "type": "event_farm",
                "event": "月行水上" if str(stage).upper().startswith("SR-") else None,
                "stage": str(stage),
                "runs": runs,
                "sanity_cost_each": cost // runs,
                "sanity_consumed": cost,
                "sanity_before_farm": stamina.get("start"),
                "sanity_after_farm": stamina.get("final_observed"),
                "evidence": str(evidence_path),
                "source_manifest": str(path),
            }
        )
    return candidates[-1] if candidates else None


def install(app):
    original = app._game_day_activity_summary
    if getattr(original, "_same_day_effects_v1", False):
        return original

    def recovered(now=None):
        result = original(now=now)
        if result:
            return result
        result = load_verified_activity(app.BASE, now=now)
        if result:
            app._RUN_SUMMARY["same_day_activity_recovered"] = result
        return result

    recovered._same_day_effects_v1 = True
    recovered._same_day_effects_original = original
    app._game_day_activity_summary = recovered
    return recovered

