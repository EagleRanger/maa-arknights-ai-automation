"""Evidence-first tracking for Phantom terminal battle collapses.

The tracker consumes the current MAA Roguelike log segment.  It never treats a
combat end as a failed run by itself: only a following RoguelikeSettlement may
classify the last StageInfo as the terminal collapse stage.  Reprocessing the
same text is safe because settlement and stage-entry events are content keyed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent
DEFAULT_LEDGER = BASE / "outputs" / "phantom_collapse_tracking.json"
DEFAULT_USER_AUTOPILOT_MANIFEST = (
    BASE / "resources" / "phantom_autopilot_afk_assault_v2.json"
)
OPTIMIZATION_MIN_SAMPLES = 3
FOCUS_STAGE_LIMIT = 4
TRACKING_DIRECTIVE_STARTED_AT = "2026-07-27 19:43:00"
REVIEWABLE_HISTORY_RESET_ID = "2026-07-28-user-corrected-v2"
POST_DIRECTIVE_HISTORY_IMPORT_ID = "2026-07-28-post-directive-restore-v1"
LEGACY_REVIEW_BACKUP = (
    BASE
    / "outputs"
    / "history_backups"
    / "phantom_collapse_tracking_pre_reviewable_reset_20260728_192715.json"
)


def load_user_optimized_stages(
    manifest_path: str | Path = DEFAULT_USER_AUTOPILOT_MANIFEST,
) -> list[str]:
    """Return stages with an explicit, reviewable user-directed map override."""

    try:
        value = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []
    stages = value.get("stages") if isinstance(value, dict) else None
    if not isinstance(stages, dict):
        return []
    return sorted(str(name) for name in stages if str(name).strip())

_TIME_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\]")
_NOT_IN_PLAN_RE = re.compile(
    r"(?P<stage>\S+) operator (?P<operator>.+?) is not in ALL deploy plan\."
)
_WAITING_COST_RE = re.compile(
    r"best deploy is (?P<operator>.+?) with rank \d+ but now waiting for cost\."
)
_KILLS_RE = re.compile(r"Kills:\s*(?P<current>\d+)\s*/\s*(?P<total>\d+)")
_BEST_MATCH_RE = re.compile(r"The best match is \{ name: (?P<operator>.+?), matched:")
_TACTICAL_NEEDS_RE = re.compile(
    r"use_air_defense (?P<air>[01])\s*,\s*use_blocking (?P<blocking>[01])\s*,\s*use_medic (?P<medic>[01])"
)
_BEST_OPER_RE = re.compile(
    r"best oper is (?P<operator>.+?) with cost being (?P<cost>\d+)"
)
_BEST_DEPLOY_RE = re.compile(
    r"best deploy is (?P<operator>.+?) with rank (?P<rank>\d+)(?P<waiting> but now waiting for cost\.)?\s*$"
)
_SWIPE_RE = re.compile(
    r"Swipe with scaled coordinates \((?P<x1>\d+),\s*(?P<y1>\d+)\) "
    r"\((?P<x2>\d+),\s*(?P<y2>\d+)\)"
)


def _timestamp(line: str) -> str | None:
    match = _TIME_RE.search(line)
    return match.group(1) if match else None


def _callback(line: str) -> dict | None:
    marker = "Assistant::append_callback |"
    if marker not in line:
        return None
    start = line.find("{", line.find(marker))
    if start < 0:
        return None
    try:
        value = json.loads(line[start:])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _deployment_attempt_is_reviewable(attempt: dict) -> bool:
    """Require the minimum evidence needed for a stage-specific battle review."""

    return bool(
        isinstance(attempt, dict)
        and attempt.get("operator")
        and attempt.get("screen_target")
        and attempt.get("direction")
    )


def _stage_has_reviewable_deployment(stage: dict | None) -> bool:
    if not isinstance(stage, dict):
        return False
    signals = stage.get("behavior_signals") or {}
    return any(
        _deployment_attempt_is_reviewable(attempt)
        for attempt in (signals.get("deployment_attempts") or [])
    )


def _at_or_after(value: str | None, threshold: str) -> bool:
    if not value:
        return False
    return str(value).replace("T", " ")[:19] >= threshold


def _outcome_is_reviewable_failure(outcome: dict) -> bool:
    """Keep direct post-directive failures or older fully reviewable samples."""

    if not isinstance(outcome, dict) or outcome.get("game_pass") is not False:
        return False
    if _stage_has_reviewable_deployment(outcome.get("terminal_stage")):
        return True
    stage = outcome.get("terminal_stage")
    return bool(
        isinstance(stage, dict)
        and stage.get("name")
        and stage.get("name") != "unknown"
        and _at_or_after(outcome.get("settled_at"), TRACKING_DIRECTIVE_STARTED_AT)
    )


def _load_ledger(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    value.setdefault("schema_version", 5)
    value["schema_version"] = max(5, int(value.get("schema_version", 5) or 5))
    value.setdefault(
        "policy",
        {
            "terminal_stage_definition": "失败RoguelikeSettlement之前最后一个StageInfo；缺失时保持unknown",
            "focus_stage_rule": "部署证据范围为已有逐图优化关、条件通过率低于50%的关、至少3次终局失败关与动态风险前四的并集",
            "optimization_min_samples": OPTIMIZATION_MIN_SAMPLES,
            "optimization_trigger": "同一关累计至少3次有效最终崩盘样本后才进入自动优化候选",
            "allowed_change_scope": "仅该关Phantom/autopilot战斗逻辑",
        },
    )
    value["policy"]["optimization_min_samples"] = OPTIMIZATION_MIN_SAMPLES
    value["policy"]["optimization_trigger"] = (
        "用户首次跟踪指令后，同一关累计至少3次有直接结算和终局关证据的崩盘即必须复盘；有因果证据时执行最小关内优化"
    )
    value["policy"]["history_scope"] = (
        "保留2026-07-27 19:43后可确认终局关的真实失败；监督器漏存部署字段不得抹去失败次数，指令前仅保留完整部署样本"
    )
    value["policy"]["deployment_tracking_rule"] = (
        "所有用户明确逐图优化关持续验证；另纳入条件通过率低于50%的关、至少3次终局失败关和动态风险前四"
    )
    value["policy"]["user_optimized_manifest"] = str(
        DEFAULT_USER_AUTOPILOT_MANIFEST
    )
    value.setdefault("outcomes", [])
    value.setdefault("focus_entry_events", [])
    value.setdefault("focus_stage_captures", [])
    value.setdefault("focus_stage_activity", [])
    if (
        path.resolve() == DEFAULT_LEDGER.resolve()
        and value["policy"].get("post_directive_history_import_id")
        != POST_DIRECTIVE_HISTORY_IMPORT_ID
    ):
        try:
            legacy = json.loads(LEGACY_REVIEW_BACKUP.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            legacy = {}
        if isinstance(legacy, dict):
            value["outcomes"].extend(legacy.get("outcomes") or [])
            value["focus_entry_events"].extend(
                item
                for item in (legacy.get("focus_entry_events") or [])
                if _at_or_after(item.get("seen_at"), TRACKING_DIRECTIVE_STARTED_AT)
            )
            value["focus_stage_captures"].extend(
                item
                for item in (legacy.get("focus_stage_captures") or [])
                if _at_or_after(item.get("stage_seen_at"), TRACKING_DIRECTIVE_STARTED_AT)
            )
        value["policy"]["post_directive_history_import_id"] = (
            POST_DIRECTIVE_HISTORY_IMPORT_ID
        )
    value["outcomes"] = [
        item
        for item in _dedupe_outcomes(value["outcomes"])
        if _outcome_is_reviewable_failure(item)
    ]
    value["focus_entry_events"] = list(
        {
            item.get("entry_id") or f"{item.get('seen_at')}|{item.get('stage')}": item
            for item in value["focus_entry_events"]
            if isinstance(item, dict)
            and _at_or_after(item.get("seen_at"), TRACKING_DIRECTIVE_STARTED_AT)
        }.values()
    )
    value["focus_stage_captures"] = list(
        {
            (
                item.get("stage"),
                item.get("stage_seen_at"),
                item.get("screenshot"),
            ): item
            for item in value["focus_stage_captures"]
            if isinstance(item, dict)
            and _at_or_after(item.get("stage_seen_at"), TRACKING_DIRECTIVE_STARTED_AT)
        }.values()
    )
    value["focus_stage_activity"] = list(
        {
            item.get("activity_id")
            or f"{item.get('run_id')}|{item.get('stage_seen_at')}|{item.get('stage')}": item
            for item in value["focus_stage_activity"]
            if isinstance(item, dict)
            and _at_or_after(
                item.get("stage_seen_at"), TRACKING_DIRECTIVE_STARTED_AT
            )
        }.values()
    )
    if value["policy"].get("reviewable_history_reset_id") != REVIEWABLE_HISTORY_RESET_ID:
        value["policy"]["reviewable_history_reset_id"] = REVIEWABLE_HISTORY_RESET_ID
    return value


def _outcome_key(outcome: dict) -> str:
    """Stable identity across tracker revisions with different event hashes."""

    return "|".join(
        [
            str(outcome.get("settled_at") or ""),
            json.dumps(
                outcome.get("settlement_details") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ]
    )


def _dedupe_outcomes(outcomes: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for item in outcomes:
        if not isinstance(item, dict):
            continue
        key = _outcome_key(item)
        if key not in by_key:
            order.append(key)
            by_key[key] = item
            continue
        # Prefer the duplicate carrying richer stage/deployment evidence.  Old
        # revisions may have the same settlement but only a terminal name.
        if _outcome_evidence_score(item) > _outcome_evidence_score(by_key[key]):
            by_key[key] = item
    return [by_key[key] for key in order]


def _outcome_evidence_score(outcome: dict) -> int:
    score = 0
    for stage in outcome.get("stage_sequence") or []:
        signals = stage.get("behavior_signals") or {}
        score += len(signals.get("deployment_attempts") or []) * 10
        score += len(signals.get("recognized_operators") or [])
        score += int(signals.get("kill_total") is not None)
    score += int(outcome.get("terminal_stage") is not None) * 100
    return score


def _stage_evidence_score(stage: dict) -> int:
    """Rank an in-battle snapshot so cumulative reads only move forward."""

    signals = stage.get("behavior_signals") or {}
    return (
        len(signals.get("deployment_attempts") or []) * 100
        + len(signals.get("recognized_operators") or []) * 10
        + int(signals.get("max_kills_seen", 0) or 0)
        + int(signals.get("kill_total") is not None) * 5
        + int(bool(stage.get("combat_end_seen"))) * 10000
    )


def _activity_id(stage: dict, run_context: dict | None, source: str) -> str:
    raw = "|".join(
        [
            str((run_context or {}).get("run_id") or ""),
            str(stage.get("seen_at") or ""),
            str(stage.get("name") or "unknown"),
            str(source),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _focus_activity_record(
    stage: dict, *, run_context: dict | None, source: str
) -> dict:
    """Create a durable snapshot before settlement or technical recovery."""

    signals = stage.get("behavior_signals") or {}
    return {
        "activity_id": _activity_id(stage, run_context, source),
        "run_id": (run_context or {}).get("run_id"),
        "stage": stage.get("name"),
        "stage_seen_at": stage.get("seen_at"),
        "combat_end_seen": bool(stage.get("combat_end_seen")),
        "combat_end_at": stage.get("combat_end_at"),
        "behavior_signals": json.loads(
            json.dumps(signals, ensure_ascii=False)
        ),
        "run_context": dict(run_context or {}),
        "source": source,
        "updated_at": datetime.now().astimezone().isoformat(),
        "persistence_reason": (
            "high_risk_stage_live_evidence_survives_task_chain_error"
        ),
    }


def _write_ledger(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _new_stage(details: dict, line: str) -> dict:
    return {
        "name": str(details.get("name") or "unknown"),
        "size": details.get("size"),
        "seen_at": _timestamp(line),
        "combat_end_seen": False,
        "behavior_signals": {
            "deploy_attempt_count": 0,
            "not_in_deploy_plan_count": 0,
            "not_in_deploy_plan_operators": [],
            "waiting_for_cost_count": 0,
            "waiting_for_cost_operators": [],
            "max_kills_seen": 0,
            "kill_total": None,
            "task_chain_error_seen": False,
            "recognized_operators": [],
            "deployment_attempts": [],
            "first_deploy_delay_seconds": None,
        },
    }


def _seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 3)
    except (TypeError, ValueError):
        return None


def _direction(start: list[int], end: list[int]) -> str:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def _finalize_deploy(stage: dict, pending: dict | None) -> None:
    if not pending:
        return
    signals = stage["behavior_signals"]
    attempts = signals["deployment_attempts"]
    if len(attempts) < 64:
        attempts.append(pending)
    if signals.get("first_deploy_delay_seconds") is None:
        signals["first_deploy_delay_seconds"] = _seconds_between(
            stage.get("seen_at"), pending.get("selected_at")
        )


def _deployment_signature(item: dict) -> str:
    operator = str(item.get("operator") or "unknown")
    target = item.get("screen_target")
    target_text = ",".join(str(value) for value in target) if target else "?"
    return f"{operator}@{target_text}:{item.get('direction') or '?'}"


def _compact_stage_sample(stage: dict, *, result: str, settled_at: str | None) -> dict:
    signals = stage.get("behavior_signals") or {}
    attempts = signals.get("deployment_attempts") or []
    signatures = [_deployment_signature(item) for item in attempts]
    repeats = Counter(signatures)
    total = signals.get("kill_total")
    current = int(signals.get("max_kills_seen", 0) or 0)
    return {
        "result": result,
        "seen_at": stage.get("seen_at"),
        "settled_at": settled_at,
        "recognized_operators": list(signals.get("recognized_operators") or []),
        "deployment_sequence": attempts,
        "deployment_signatures": signatures,
        "first_deploy_delay_seconds": signals.get("first_deploy_delay_seconds"),
        "repeated_deployments": {
            key: value for key, value in repeats.items() if value >= 2
        },
        "not_in_deploy_plan_operators": list(
            signals.get("not_in_deploy_plan_operators") or []
        ),
        "waiting_for_cost_operators": list(
            signals.get("waiting_for_cost_operators") or []
        ),
        "waiting_for_cost_count": int(signals.get("waiting_for_cost_count", 0) or 0),
        "kill_progress": {
            "current": current,
            "total": total,
            "ratio": round(current / total, 4) if total else None,
        },
    }


def _common_prefix(sequences: list[list[str]]) -> list[str]:
    if not sequences:
        return []
    prefix = list(sequences[0])
    for sequence in sequences[1:]:
        length = 0
        for left, right in zip(prefix, sequence):
            if left != right:
                break
            length += 1
        prefix = prefix[:length]
        if not prefix:
            break
    return prefix


def _analyze_stage_samples(samples: list[dict]) -> dict:
    failed = [item for item in samples if item.get("result") == "terminal_collapse"]
    survived = [item for item in samples if item.get("result") == "survived"]
    failed_sequences = [item.get("deployment_signatures") or [] for item in failed]
    survived_sequences = [item.get("deployment_signatures") or [] for item in survived]
    repeated = Counter()
    missing = Counter()
    waiting = Counter()
    for sample in failed:
        repeated.update(sample.get("repeated_deployments") or {})
        missing.update(sample.get("not_in_deploy_plan_operators") or [])
        waiting.update(sample.get("waiting_for_cost_operators") or [])

    causes = []
    if missing:
        causes.append({
            "kind": "stage_plan_does_not_cover_available_operator",
            "evidence": dict(missing.most_common()),
        })
    if repeated:
        causes.append({
            "kind": "same_operator_position_retried_or_redeployed",
            "evidence": dict(repeated.most_common(8)),
        })
    if waiting:
        causes.append({
            "kind": "deployment_order_waited_for_cost",
            "evidence": dict(waiting.most_common()),
        })
    low_progress = [
        item for item in failed
        if item.get("kill_progress", {}).get("ratio") is not None
        and item["kill_progress"]["ratio"] < 0.5
    ]
    if low_progress:
        causes.append({
            "kind": "early_or_mid_battle_defense_collapse",
            "evidence": [item["kill_progress"] for item in low_progress[-3:]],
        })
    failed_prefix = _common_prefix(failed_sequences)
    survived_prefix = _common_prefix(survived_sequences)
    if failed_prefix and survived_prefix and failed_prefix != survived_prefix:
        causes.append({
            "kind": "failed_opening_differs_from_survived_reference",
            "failed_common_opening": failed_prefix[:6],
            "survived_common_opening": survived_prefix[:6],
        })
    if failed and not causes:
        causes.append({
            "kind": "visual_formation_review_required",
            "evidence": "日志未直接暴露阻挡、治疗覆盖或漏怪点；使用该关定时截图复核位置与朝向",
        })
    return {
        "terminal_sample_count": len(failed),
        "survived_reference_count": len(survived),
        "failed_common_opening": failed_prefix[:8],
        "survived_common_opening": survived_prefix[:8],
        "latest_failed_sample": failed[-1] if failed else None,
        "latest_survived_reference": survived[-1] if survived else None,
        "cause_candidates": causes,
    }


def parse_run_log(run_log: str, *, source: str, run_context: dict | None = None) -> dict:
    """Return settlement outcomes plus all observed stage entries.

    A log segment beginning after StageInfo intentionally produces an unknown
    terminal stage.  This fail-closed rule prevents a technical restart from
    attributing a settlement to an unrelated earlier battle.
    """

    stage_sequence: list[dict] = []
    current_stage: dict | None = None
    outcomes: list[dict] = []
    entries: list[dict] = []
    pending_deploy: dict | None = None
    last_deploy_candidate: dict | None = None
    recent_deploy: dict | None = None
    tactical_needs = {"air_defense": False, "blocking": False, "medic": False}

    for line in (run_log or "").splitlines():
        callback = _callback(line)
        what = callback.get("what") if callback else None
        details = callback.get("details") if callback else {}
        details = details if isinstance(details, dict) else {}

        if what == "StageInfo":
            if current_stage is not None:
                _finalize_deploy(current_stage, pending_deploy)
            current_stage = _new_stage(details, line)
            pending_deploy = None
            last_deploy_candidate = None
            recent_deploy = None
            tactical_needs = {"air_defense": False, "blocking": False, "medic": False}
            stage_sequence.append(current_stage)
            entries.append(dict(current_stage))
            continue

        if current_stage is not None:
            signals = current_stage["behavior_signals"]
            best_match = _BEST_MATCH_RE.search(line)
            if best_match:
                operator = best_match.group("operator")
                if operator not in signals["recognized_operators"]:
                    signals["recognized_operators"].append(operator)
            needs = _TACTICAL_NEEDS_RE.search(line)
            if needs:
                tactical_needs = {
                    "air_defense": needs.group("air") == "1",
                    "blocking": needs.group("blocking") == "1",
                    "medic": needs.group("medic") == "1",
                }
            best_oper = _BEST_OPER_RE.search(line)
            if best_oper:
                _finalize_deploy(current_stage, pending_deploy)
                pending_deploy = {
                    "operator": best_oper.group("operator"),
                    "cost": int(best_oper.group("cost")),
                    "selected_at": _timestamp(line),
                    "tactical_needs": dict(tactical_needs),
                    "screen_source": None,
                    "screen_target": None,
                    "direction": None,
                    "operator_evidence": "best_oper_with_cost",
                }
                last_deploy_candidate = {
                    "operator": best_oper.group("operator"),
                    "seen_at": _timestamp(line),
                    "source": "best_oper_with_cost",
                }
            best_deploy = _BEST_DEPLOY_RE.search(line)
            if best_deploy:
                operator = best_deploy.group("operator")
                last_deploy_candidate = {
                    "operator": operator,
                    "seen_at": _timestamp(line),
                    "source": (
                        "waiting_for_cost"
                        if best_deploy.group("waiting")
                        else "post_deploy_confirmation"
                    ),
                }
                if (
                    not best_deploy.group("waiting")
                    and recent_deploy is not None
                    and _seconds_between(
                        recent_deploy.get("selected_at"), _timestamp(line)
                    )
                    is not None
                    and _seconds_between(
                        recent_deploy.get("selected_at"), _timestamp(line)
                    )
                    <= 5
                ):
                    previous_operator = recent_deploy.get("operator")
                    recent_deploy["operator"] = operator
                    recent_deploy["operator_evidence"] = "post_deploy_confirmation"
                    if previous_operator and previous_operator != operator:
                        recent_deploy["pre_confirmation_operator"] = previous_operator
            swipe = _SWIPE_RE.search(line)
            if swipe and pending_deploy is not None:
                start = [int(swipe.group("x1")), int(swipe.group("y1"))]
                end = [int(swipe.group("x2")), int(swipe.group("y2"))]
                if pending_deploy.get("screen_target") is None:
                    pending_deploy["screen_source"] = start
                    pending_deploy["screen_target"] = end
                else:
                    pending_deploy["direction_drag_end"] = end
                    pending_deploy["direction"] = _direction(start, end)
                    _finalize_deploy(current_stage, pending_deploy)
                    recent_deploy = pending_deploy
                    pending_deploy = None
            if "BattleHelper::deploy_oper | enter" in line:
                signals["deploy_attempt_count"] += 1
                signals.setdefault("first_deploy_attempt_at", _timestamp(line))
                if pending_deploy is None:
                    candidate_age = None
                    if last_deploy_candidate is not None:
                        candidate_age = _seconds_between(
                            last_deploy_candidate.get("seen_at"), _timestamp(line)
                        )
                    candidate_is_recent = (
                        candidate_age is not None and 0 <= candidate_age <= 5
                    )
                    pending_deploy = {
                        "operator": (
                            last_deploy_candidate.get("operator")
                            if candidate_is_recent
                            else None
                        ),
                        "cost": None,
                        "selected_at": _timestamp(line),
                        "tactical_needs": dict(tactical_needs),
                        "screen_source": None,
                        "screen_target": None,
                        "direction": None,
                        "operator_evidence": (
                            last_deploy_candidate.get("source")
                            if candidate_is_recent
                            else "awaiting_post_deploy_confirmation"
                        ),
                    }
                    recent_deploy = pending_deploy
            not_in_plan = _NOT_IN_PLAN_RE.search(line)
            if not_in_plan and not_in_plan.group("stage") == current_stage["name"]:
                signals = current_stage["behavior_signals"]
                signals["not_in_deploy_plan_count"] += 1
                operator = not_in_plan.group("operator")
                if operator not in signals["not_in_deploy_plan_operators"]:
                    signals["not_in_deploy_plan_operators"].append(operator)
            waiting = _WAITING_COST_RE.search(line)
            if waiting:
                signals = current_stage["behavior_signals"]
                signals["waiting_for_cost_count"] += 1
                operator = waiting.group("operator")
                if operator not in signals["waiting_for_cost_operators"]:
                    signals["waiting_for_cost_operators"].append(operator)
            kills = _KILLS_RE.search(line)
            if kills:
                signals = current_stage["behavior_signals"]
                signals["max_kills_seen"] = max(
                    int(signals.get("max_kills_seen", 0) or 0),
                    int(kills.group("current")),
                )
                signals["kill_total"] = int(kills.group("total"))
            if "TaskChainError" in line:
                current_stage["behavior_signals"]["task_chain_error_seen"] = True

        if what == "RoguelikeCombatEnd" and current_stage is not None:
            _finalize_deploy(current_stage, pending_deploy)
            pending_deploy = None
            current_stage["combat_end_seen"] = True
            current_stage["combat_end_at"] = _timestamp(line)
            continue

        if what != "RoguelikeSettlement":
            continue

        settled_at = _timestamp(line)
        raw_id = f"{settled_at}|{json.dumps(details, ensure_ascii=False, sort_keys=True)}"
        game_pass = details.get("game_pass")
        terminal = dict(stage_sequence[-1]) if stage_sequence and game_pass is False else None
        if game_pass is True:
            classification = "game_pass"
        elif terminal is not None:
            classification = "terminal_collapse_candidate"
        else:
            classification = "unknown_no_stage_evidence"
        outcome = {
            "event_id": hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:24],
            "settled_at": settled_at,
            "game_pass": game_pass,
            "classification": classification,
            "terminal_stage": terminal,
            "stage_sequence": [dict(item) for item in stage_sequence],
            "settlement_details": details,
            "source": source,
        }
        if run_context:
            outcome["run_context"] = dict(run_context)
        outcomes.append(outcome)
        stage_sequence = []
        current_stage = None
        pending_deploy = None

    active_stage = None
    if current_stage is not None and not current_stage.get("combat_end_seen"):
        active_stage = {
            "name": current_stage.get("name"),
            "seen_at": current_stage.get("seen_at"),
        }
    return {"outcomes": outcomes, "stage_entries": entries, "active_stage": active_stage}


def _deployment_tracking_scope(
    ranked: list[dict], user_optimized_stages: list[str] | None = None
) -> dict:
    """Build the durable evidence scope; the top-four list is only one input."""

    user_optimized = set(
        load_user_optimized_stages()
        if user_optimized_stages is None
        else user_optimized_stages
    )
    reasons: dict[str, list[str]] = defaultdict(list)
    ranking_order = [item["stage"] for item in ranked]

    for stage in ranking_order[:FOCUS_STAGE_LIMIT]:
        reasons[stage].append("top_four_terminal_collapse_risk")

    for item in ranked:
        stage = item["stage"]
        terminal_count = int(item.get("terminal_collapse_count", 0) or 0)
        appearances = int(item.get("appearance_count", 0) or 0)
        failure_rate = item.get("conditional_terminal_collapse_rate")
        if terminal_count >= OPTIMIZATION_MIN_SAMPLES:
            reasons[stage].append("mandatory_three_failure_review")
        if (
            appearances >= 2
            and failure_rate is not None
            and float(failure_rate) > 0.5
        ):
            reasons[stage].append("conditional_pass_rate_below_50_percent")
        if stage in user_optimized and terminal_count >= 2:
            reasons[stage].append("user_optimized_then_repeated_failure")

    # Every explicit per-stage override remains observable after installation.
    # This is what lets the tracker prove whether it still fails, instead of
    # discovering the failure only after the deployment sequence is gone.
    for stage in user_optimized:
        reasons[stage].append("user_optimized_stage_validation")

    ordered = [stage for stage in ranking_order if stage in reasons]
    ordered.extend(sorted(stage for stage in reasons if stage not in ordered))
    return {
        "stages": ordered,
        "reasons": {stage: reasons[stage] for stage in ordered},
        "user_optimized_stages": sorted(user_optimized),
    }


def build_summary(
    outcomes: list[dict], user_optimized_stages: list[str] | None = None
) -> dict:
    appearances: Counter[str] = Counter()
    terminal: Counter[str] = Counter()
    combat_end: Counter[str] = Counter()
    latest: dict[str, str | None] = {}
    direct_signals: dict[str, Counter[str]] = defaultdict(Counter)
    unknown_count = 0
    stage_samples: dict[str, list[dict]] = defaultdict(list)

    for outcome in outcomes:
        seen_names = set()
        sequence = outcome.get("stage_sequence") or []
        terminal_stage = outcome.get("terminal_stage")
        terminal_seen_at = terminal_stage.get("seen_at") if isinstance(terminal_stage, dict) else None
        for stage in sequence:
            name = stage.get("name")
            if name and name != "unknown" and name not in seen_names:
                appearances[name] += 1
                seen_names.add(name)
            if name and name != "unknown":
                result = (
                    "terminal_collapse"
                    if outcome.get("game_pass") is False and stage.get("seen_at") == terminal_seen_at
                    else "survived"
                )
                stage_samples[name].append(
                    _compact_stage_sample(
                        stage, result=result, settled_at=outcome.get("settled_at")
                    )
                )
        stage = terminal_stage
        if outcome.get("game_pass") is False and isinstance(stage, dict):
            name = stage.get("name")
            if name and name != "unknown":
                terminal[name] += 1
                combat_end[name] += int(bool(stage.get("combat_end_seen")))
                latest[name] = outcome.get("settled_at")
                signals = stage.get("behavior_signals") or {}
                direct_signals[name]["not_in_deploy_plan"] += int(
                    signals.get("not_in_deploy_plan_count", 0) or 0
                )
                direct_signals[name]["task_chain_error"] += int(
                    bool(signals.get("task_chain_error_seen"))
                )
                direct_signals[name]["waiting_for_cost"] += int(
                    signals.get("waiting_for_cost_count", 0) or 0
                )
        elif outcome.get("game_pass") is False:
            unknown_count += 1

    ranked = []
    for name, count in terminal.items():
        appearance_count = appearances[name]
        rate = round(count / appearance_count, 4) if appearance_count else None
        deployment_analysis = _analyze_stage_samples(stage_samples.get(name, []))
        evidence_sample_count = sum(
            1
            for item in stage_samples.get(name, [])
            if item.get("result") == "terminal_collapse"
            and any(
                _deployment_attempt_is_reviewable(attempt)
                for attempt in (item.get("deployment_sequence") or [])
            )
        )
        ready = count >= OPTIMIZATION_MIN_SAMPLES
        ranked.append(
            {
                "stage": name,
                "appearance_count": appearance_count,
                "terminal_collapse_count": count,
                "conditional_terminal_collapse_rate": rate,
                "combat_end_evidence_count": combat_end[name],
                "latest_settlement": latest.get(name),
                "direct_behavior_signals": dict(direct_signals[name]),
                "deployment_evidence_sample_count": evidence_sample_count,
                "deployment_failure_analysis": deployment_analysis,
                "optimization_state": (
                    (
                        "ready_for_evidence_backed_optimization"
                        if evidence_sample_count
                        else "ready_for_mandatory_stage_review"
                    )
                    if ready
                    else f"collect_more_terminal_failures_{count}_of_{OPTIMIZATION_MIN_SAMPLES}"
                ),
            }
        )
    ranked.sort(
        key=lambda item: (
            -item["terminal_collapse_count"],
            -(item["conditional_terminal_collapse_rate"] or 0),
            item["stage"],
        )
    )
    focus = [item["stage"] for item in ranked[:FOCUS_STAGE_LIMIT]]
    tracking_scope = _deployment_tracking_scope(ranked, user_optimized_stages)
    return {
        "settlement_count": len(outcomes),
        "failed_settlement_with_terminal_stage": sum(terminal.values()),
        "unknown_terminal_stage_count": unknown_count,
        "optimization_min_samples": OPTIMIZATION_MIN_SAMPLES,
        "focus_tracking_stages": focus,
        "deployment_tracking_stages": tracking_scope["stages"],
        "deployment_tracking_reasons": tracking_scope["reasons"],
        "user_optimized_stages": tracking_scope["user_optimized_stages"],
        "ranked_terminal_collapse_stages": ranked,
        "latest_outcome": outcomes[-1] if outcomes else None,
    }


def update_collapse_tracking(
    run_log: str,
    *,
    run_context: dict | None = None,
    ledger_path: str | Path = DEFAULT_LEDGER,
    source: str = "rotating_current_run",
) -> dict:
    """Merge newly observed evidence and return a compact update result."""

    path = Path(ledger_path)
    ledger = _load_ledger(path)
    parsed = parse_run_log(run_log, source=source, run_context=run_context)
    reviewable_parsed_outcomes = [
        item for item in parsed["outcomes"] if _outcome_is_reviewable_failure(item)
    ]
    known_outcomes = {_outcome_key(item) for item in ledger["outcomes"]}
    new_outcomes = [
        item
        for item in reviewable_parsed_outcomes
        if _outcome_key(item) not in known_outcomes
    ]
    ledger["outcomes"].extend(new_outcomes)
    parsed_by_key = {
        _outcome_key(item): item for item in reviewable_parsed_outcomes
    }
    for index, existing in enumerate(ledger["outcomes"]):
        candidate = parsed_by_key.get(_outcome_key(existing))
        if candidate is None:
            continue
        if _outcome_evidence_score(candidate) > _outcome_evidence_score(existing):
            if existing.get("run_context") and not candidate.get("run_context"):
                candidate["run_context"] = existing["run_context"]
            ledger["outcomes"][index] = candidate

    # Tracked-stage entries are recorded independently so a later settlement
    # can be compared with the exact deployment evidence observed in battle.
    previous_summary = build_summary(ledger["outcomes"])
    focus = set(previous_summary.get("deployment_tracking_stages") or [])
    known_entries = {item.get("entry_id") for item in ledger["focus_entry_events"]}
    new_focus_entries = []
    activity_index = {
        item.get("activity_id"): index
        for index, item in enumerate(ledger["focus_stage_activity"])
        if item.get("activity_id")
    }
    updated_focus_activities = []
    active_stage = parsed.get("active_stage") or {}
    for entry in parsed["stage_entries"]:
        if entry.get("name") not in focus:
            continue
        raw_id = f"{entry.get('seen_at')}|{entry.get('name')}|{source}"
        entry_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:24]
        if entry_id not in known_entries:
            record = {
                "entry_id": entry_id,
                "stage": entry.get("name"),
                "seen_at": entry.get("seen_at"),
                "source": source,
                "tracking_reason": ",".join(
                    previous_summary.get("deployment_tracking_reasons", {}).get(
                        entry.get("name"), ["historical_terminal_collapse_risk"]
                    )
                ),
            }
            ledger["focus_entry_events"].append(record)
            known_entries.add(entry_id)
            new_focus_entries.append(record)

        if (
            entry.get("name") != active_stage.get("name")
            or entry.get("seen_at") != active_stage.get("seen_at")
        ):
            continue

        # Entry metadata is written once, but deployment evidence can grow on
        # every polling pass while the same battle remains active.  Do not tie
        # activity persistence to the one-shot entry event: a later MAA crash
        # must not discard deployments observed after the first poll.
        activity = _focus_activity_record(
            entry, run_context=run_context, source=source
        )
        activity_id = activity["activity_id"]
        existing_index = activity_index.get(activity_id)
        previous_score = -1
        if existing_index is not None:
            previous = ledger["focus_stage_activity"][existing_index]
            previous_score = _stage_evidence_score(
                {
                    "combat_end_seen": previous.get("combat_end_seen"),
                    "behavior_signals": previous.get("behavior_signals") or {},
                }
            )
        current_score = _stage_evidence_score(entry)
        if current_score <= previous_score:
            continue
        if existing_index is None:
            activity_index[activity_id] = len(ledger["focus_stage_activity"])
            ledger["focus_stage_activity"].append(activity)
        else:
            ledger["focus_stage_activity"][existing_index] = activity
        updated_focus_activities.append(activity)

    ledger["summary"] = build_summary(ledger["outcomes"])
    ledger["updated_at"] = datetime.now().astimezone().isoformat()
    _write_ledger(path, ledger)
    return {
        "new_outcomes": new_outcomes,
        "new_focus_entries": new_focus_entries,
        "updated_focus_activities": updated_focus_activities,
        "active_stage": parsed.get("active_stage"),
        "summary": ledger["summary"],
        "ledger_path": str(path),
        "discarded_unreviewable_outcome_count": (
            len(parsed["outcomes"]) - len(reviewable_parsed_outcomes)
        ),
    }


def record_focus_stage_capture(
    *,
    stage: str,
    stage_seen_at: str | None,
    screenshot: str,
    ledger_path: str | Path = DEFAULT_LEDGER,
) -> dict:
    """Attach a non-invasive game screenshot to the active high-risk sample."""

    path = Path(ledger_path)
    ledger = _load_ledger(path)
    record = {
        "stage": stage,
        "stage_seen_at": stage_seen_at,
        "captured_at": datetime.now().astimezone().isoformat(),
        "screenshot": screenshot,
        "purpose": "deployment_order_position_direction_and_collapse_review",
    }
    existing = [
        item for item in ledger["focus_stage_captures"]
        if item.get("stage") == stage and item.get("stage_seen_at") == stage_seen_at
    ]
    if len(existing) >= 6:
        return existing[-1]
    ledger["focus_stage_captures"].append(record)
    ledger["updated_at"] = datetime.now().astimezone().isoformat()
    _write_ledger(path, ledger)
    return record
