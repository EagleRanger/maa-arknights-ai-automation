"""所有集成战略主题共用的终局暴毙证据账本。

这个模块只复用 MaaCore 日志里的客观战斗事件，不复用任何主题专属
招募、路线或部署结论。每个主题写入独立账本；技术错误不计作战斗失败，
同关同难度至少积累三次有效终局失败后才进入自动优化候选。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import phantom_collapse_tracking as battle_evidence


BASE = Path(__file__).resolve().parent
SCHEMA_VERSION = 1
OPTIMIZATION_MIN_SAMPLES = 3
LOW_PASS_MIN_APPEARANCES = 3
LEGACY_PHANTOM_LEDGER = BASE / "outputs" / "phantom_collapse_tracking.json"

THEME_ALIASES = {
    "phantom": "Phantom",
    "mizuki": "Mizuki",
    "sami": "Sami",
    "sarkaz": "Sarkaz",
    "jiegarden": "JieGarden",
    "garden": "JieGarden",
}


def normalize_theme(theme: str) -> str:
    value = str(theme or "").strip()
    canonical = THEME_ALIASES.get(value.lower(), value)
    if canonical not in set(THEME_ALIASES.values()):
        raise ValueError(f"unsupported roguelike theme: {theme!r}")
    return canonical


def ledger_path_for(theme: str) -> Path:
    canonical = normalize_theme(theme)
    return BASE / "outputs" / f"roguelike_collapse_{canonical.lower()}.json"


def _outcome_key(outcome: dict) -> str:
    return "|".join(
        (
            str(outcome.get("settled_at") or ""),
            json.dumps(
                outcome.get("settlement_details") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    )


def _is_reviewable(outcome: dict) -> bool:
    """保留真实成功和可定位终局关的真实失败，丢弃技术终止。"""

    if not isinstance(outcome, dict):
        return False
    if outcome.get("game_pass") is True:
        return bool(outcome.get("stage_sequence"))
    return battle_evidence._outcome_is_reviewable_failure(outcome)


def _difficulty_value(outcome: dict):
    context = outcome.get("run_context") or {}
    value = context.get("actual_difficulty")
    if value is None:
        value = (outcome.get("settlement_details") or {}).get("difficulty")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _difficulty_bucket(outcome: dict) -> str:
    actual = _difficulty_value(outcome)
    if actual is not None:
        return f"difficulty_{actual}"
    context = outcome.get("run_context") or {}
    target = context.get("difficulty_target")
    if target == 2147483647 or context.get("difficulty_policy") == "highest_unlocked":
        return "highest_unlocked_unverified"
    try:
        return f"difficulty_{int(target)}"
    except (TypeError, ValueError):
        return "difficulty_unknown"


def _load(path: Path, theme: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    # 傀影旧账本是这套通用规则的历史来源。只在新主题账本首次创建时
    # 单向导入真实失败样本；旧记录没有明确难度的继续留在未验证桶，
    # 绝不伪造难度，也不把傀影数据复制给其他主题。
    if (
        not value
        and theme == "Phantom"
        and path.resolve() == ledger_path_for("Phantom").resolve()
        and LEGACY_PHANTOM_LEDGER.exists()
    ):
        try:
            legacy = json.loads(LEGACY_PHANTOM_LEDGER.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            legacy = {}
        if isinstance(legacy, dict):
            value["outcomes"] = [
                item
                for item in (legacy.get("outcomes") or [])
                if battle_evidence._outcome_is_reviewable_failure(item)
            ]
            value["migration"] = {
                "source": str(LEGACY_PHANTOM_LEDGER),
                "rule": "failure_samples_only_keep_unknown_difficulty_when_missing",
            }
    stored_theme = value.get("theme")
    if stored_theme and normalize_theme(stored_theme) != theme:
        raise ValueError(
            f"ledger theme mismatch: expected {theme}, found {stored_theme}"
        )
    value["schema_version"] = SCHEMA_VERSION
    value["theme"] = theme
    value["policy"] = {
        "scope": "all_roguelike_progression",
        "theme_isolation": "每个主题独立账本，禁止跨主题合并失败样本或战术结论",
        "terminal_stage_definition": "失败结算前最后一个StageInfo；缺失时不归因",
        "technical_error_rule": "TaskChainError、进程退出、网络或无真实结算不得计作战斗失败",
        "difficulty_isolation": "优化触发按主题+实际难度+关卡分别统计；实际难度缺失时单列未验证桶",
        "optimization_min_samples": OPTIMIZATION_MIN_SAMPLES,
        "optimization_trigger": "同关同难度累计3次有效终局失败，或至少3次出现且通过率低于50%，进入最小关内优化候选",
        "evidence_required": "记录编队上下文、部署干员、顺序、坐标、朝向、费用等待、击杀进度和结算",
        "change_boundary": "只生成该主题该难度该关的最小部署候选；不得在正在进行的战斗中热改，不得改变总目标、资源用途或停止条件",
        "validation": "候选在后续独立探索中验证；成功与失败都入账，未改善则回滚或继续采样",
    }
    outcomes = value.get("outcomes")
    value["outcomes"] = outcomes if isinstance(outcomes, list) else []
    return value


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _deployment_sample(stage: dict | None) -> dict | None:
    if not isinstance(stage, dict):
        return None
    signals = stage.get("behavior_signals") or {}
    attempts = list(signals.get("deployment_attempts") or [])
    return {
        "seen_at": stage.get("seen_at"),
        "combat_end_seen": bool(stage.get("combat_end_seen")),
        "deployments": attempts,
        "recognized_operators": list(signals.get("recognized_operators") or []),
        "waiting_for_cost_count": int(signals.get("waiting_for_cost_count", 0) or 0),
        "waiting_for_cost_operators": list(signals.get("waiting_for_cost_operators") or []),
        "not_in_deploy_plan_operators": list(signals.get("not_in_deploy_plan_operators") or []),
        "max_kills_seen": int(signals.get("max_kills_seen", 0) or 0),
        "kill_total": signals.get("kill_total"),
    }


def _summarize_rows(outcomes: list[dict], *, split_difficulty: bool) -> list[dict]:
    appearances = Counter()
    collapses = Counter()
    passes = Counter()
    latest = {}
    samples = defaultdict(list)

    for outcome in outcomes:
        bucket = _difficulty_bucket(outcome) if split_difficulty else "all_difficulties"
        sequence = outcome.get("stage_sequence") or []
        terminal = outcome.get("terminal_stage") if outcome.get("game_pass") is False else None
        terminal_name = terminal.get("name") if isinstance(terminal, dict) else None
        seen = set()
        for stage in sequence:
            name = stage.get("name")
            if not name or name == "unknown" or name in seen:
                continue
            seen.add(name)
            key = (bucket, name)
            appearances[key] += 1
            if name == terminal_name:
                collapses[key] += 1
                sample = _deployment_sample(stage)
                if sample:
                    sample["settled_at"] = outcome.get("settled_at")
                    sample["actual_difficulty"] = _difficulty_value(outcome)
                    samples[key].append(sample)
            else:
                passes[key] += 1
            latest[key] = outcome.get("settled_at")

    rows = []
    for key, appearance_count in appearances.items():
        bucket, stage = key
        collapse_count = collapses[key]
        survived_count = passes[key]
        collapse_rate = collapse_count / appearance_count if appearance_count else 0.0
        pass_rate = survived_count / appearance_count if appearance_count else 0.0
        enough_failures = collapse_count >= OPTIMIZATION_MIN_SAMPLES
        low_pass = (
            appearance_count >= LOW_PASS_MIN_APPEARANCES and pass_rate < 0.5
        )
        deployment_samples = [
            item for item in samples[key] if item.get("deployments")
        ]
        if enough_failures or low_pass:
            optimization_state = (
                "ready_for_minimal_stage_optimization"
                if deployment_samples
                else "review_required_but_deployment_evidence_missing"
            )
        else:
            optimization_state = (
                f"collect_more_evidence_{collapse_count}_of_{OPTIMIZATION_MIN_SAMPLES}_failures"
            )
        rows.append(
            {
                "difficulty_bucket": bucket,
                "stage": stage,
                "appearance_count": appearance_count,
                "survived_count": survived_count,
                "terminal_collapse_count": collapse_count,
                "pass_rate": round(pass_rate, 4),
                "terminal_collapse_rate": round(collapse_rate, 4),
                "deployment_evidence_sample_count": len(deployment_samples),
                "latest_settlement": latest.get(key),
                "optimization_state": optimization_state,
                "trigger_reasons": [
                    reason
                    for reason, active in (
                        ("three_terminal_failures", enough_failures),
                        ("pass_rate_below_50_percent", low_pass),
                    )
                    if active
                ],
                "terminal_deployment_samples": samples[key][-3:],
            }
        )
    rows.sort(
        key=lambda row: (
            -int(bool(row["trigger_reasons"])),
            -row["terminal_collapse_count"],
            row["pass_rate"],
            row["stage"],
        )
    )
    return rows


def build_summary(outcomes: list[dict]) -> dict:
    by_difficulty = _summarize_rows(outcomes, split_difficulty=True)
    aggregate = _summarize_rows(outcomes, split_difficulty=False)
    candidates = [row for row in by_difficulty if row["trigger_reasons"]]
    return {
        "settlement_count": len(outcomes),
        "game_pass_count": sum(item.get("game_pass") is True for item in outcomes),
        "failed_settlement_count": sum(item.get("game_pass") is False for item in outcomes),
        "optimization_min_samples": OPTIMIZATION_MIN_SAMPLES,
        "optimization_candidate_count": len(candidates),
        "optimization_candidates": candidates,
        "ranked_by_difficulty_stage": by_difficulty,
        "ranked_stage_totals_for_observation_only": aggregate,
        "latest_outcome": outcomes[-1] if outcomes else None,
    }


def update_collapse_tracking(
    run_log: str,
    *,
    theme: str,
    run_context: dict | None = None,
    ledger_path: str | Path | None = None,
    source: str = "current_maa_run",
) -> dict:
    """把一段单次肉鸽日志合并到主题独立账本。重复调用安全。"""

    canonical = normalize_theme(theme)
    path = Path(ledger_path) if ledger_path else ledger_path_for(canonical)
    ledger = _load(path, canonical)
    context = dict(run_context or {})
    context["theme"] = canonical
    parsed = battle_evidence.parse_run_log(
        run_log, source=source, run_context=context
    )
    eligible = [item for item in parsed["outcomes"] if _is_reviewable(item)]
    known = {_outcome_key(item) for item in ledger["outcomes"]}
    new_outcomes = [item for item in eligible if _outcome_key(item) not in known]
    ledger["outcomes"].extend(new_outcomes)
    ledger["summary"] = build_summary(ledger["outcomes"])
    ledger["updated_at"] = datetime.now().astimezone().isoformat()
    _write(path, ledger)
    return {
        "theme": canonical,
        "ledger_path": str(path),
        "new_outcomes": new_outcomes,
        "summary": ledger["summary"],
        "discarded_noncombat_or_unattributed_count": len(parsed["outcomes"])
        - len(eligible),
    }
