"""One owner for daily-task policy: chains, game-day reuse and post-fight tail.

The coordinator decides WHEN to call this; it must not duplicate these rules.
This first adapter takes an already prepared queue port. It cannot farm, change
base strategy, launch the global entry or close the environment.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import Result

CN = timezone(timedelta(hours=8))
CHAINS = ("StartUp", "Infrast", "Recruit", "Mall", "Award")


def stamp(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("daily evidence needs timezone")
    return dt.astimezone(CN)


def game_day(at):
    return (at.astimezone(CN) - timedelta(hours=4)).date().isoformat()


def pending_chains(receipts, *, at, last_fight_at=None):
    """Reuse same-game-day proof; a later fight requires a new final five-chain.

Receipts are per-chain observations supplied by the existing evidence adapter,
not yesterday's overall completed flag. Missing/invalid evidence is unknown.
    """
    if at.tzinfo is None:
        raise ValueError("daily invocation needs timezone")
    last_fight = stamp(last_fight_at) if last_fight_at else None
    if last_fight is not None and last_fight > at:
        raise ValueError("future fight evidence")
    pending, kept = [], []
    for chain in CHAINS:
        row = receipts.get(chain) or {}
        try:
            completed = stamp(row["completed_at"])
            valid = (row.get("verified") is True and bool(row.get("evidence"))
                     and completed <= at and game_day(completed) == game_day(at)
                     and (last_fight is None or completed >= last_fight))
        except (ValueError, KeyError, TypeError):
            valid = False
        (kept if valid else pending).append(chain)
    return {"pending": pending, "preserved": kept, "game_day": game_day(at)}


def run_tasks(port, *, receipts, at, last_fight_at=None):
    """The port runs ONLY selected daily chains and returns fresh chain proof.

Base-product decisions remain in the base module; Infrast uses the prepared
plan. A port must refuse unprepared base configuration before queue mutation.
No stop/cleanup/fallback callback is available on this interface.
    """
    decision = pending_chains(receipts, at=at, last_fight_at=last_fight_at)
    pending = tuple(decision["pending"])
    if not pending:
        evidence = tuple(str(receipts[c]["evidence"]) for c in CHAINS)
        return Result("succeeded", "本游戏日每日任务已有完整证据，未重复执行", evidence,
                      dict(decision, newly_executed=[], reused_previous_effect=True))
    if port.queue_idle() is not True:
        return Result("blocked", "当前队列未空闲，不接管或重启", data=decision)
    executable = pending
    if hasattr(port, "preflight"):
        blocker = port.preflight(pending)
        if blocker is not None:
            if not isinstance(blocker, Result) or blocker.status != "blocked":
                raise TypeError("daily preflight must return a blocked Result or None")
            affected = blocker.data.get("blocked_chains")
            if not affected or not set(affected) <= set(pending):
                return blocker
            executable = tuple(c for c in pending if c not in affected)
            if not executable:
                return blocker
            decision["blocked_chains"] = list(affected)
    fresh = port.execute_daily_chains(executable)
    # Never accept bool/MAA-ended as five completed chains. Exact proof is
    # validated again here, with a lower bound at this invocation's time.
    if not isinstance(fresh, dict):
        return Result("unknown", "每日任务缺少逐链回执，未宣称完成", data=decision)
    finished_at = port.now()
    verified = []
    for chain in pending:
        row = fresh.get(chain) or {}
        try:
            completed = stamp(row["completed_at"])
            ok = (row.get("verified") is True and bool(row.get("evidence"))
                  and at <= completed <= finished_at and game_day(completed) == game_day(at))
        except (ValueError, KeyError, TypeError):
            ok = False
        if ok:
            verified.append(chain)
    missing = [c for c in pending if c not in verified]
    return Result("succeeded" if not missing else "partial",
                  "每日任务本次缺项已完成" if not missing else "每日任务仍有未核验项目",
                  tuple(str(fresh[c]["evidence"]) for c in verified),
                  dict(decision, newly_executed=verified, unverified=missing,
                       new_receipts={c: fresh[c] for c in verified}))


class PreparedDailyQueue:
    """Adapter over a caller-prepared accepted runtime, not legacy mode_daily.

Environment/lease and base-plan preparation are caller responsibilities. This
adapter does not install patches, select a different base strategy or finalise.
It is validation-only until the new daily composition has real acceptance.
    """
    def __init__(self, runtime, output, *, base_plan_ready, base_effect_verified, clock=None):
        self.runtime, self.output = runtime, Path(output)
        self.base_plan_ready, self.base_effect_verified = base_plan_ready, base_effect_verified
        self.clock = clock or (lambda: datetime.now(CN))

    def now(self):
        return self.clock()

    def queue_idle(self):
        return self.runtime._maa_task_queue_running() is False

    def preflight(self, chains):
        if not chains or not set(chains) <= set(CHAINS):
            return Result("blocked", "不是每日任务链清单，未写入队列")
        if "Infrast" in chains and self.base_plan_ready() is not True:
            return Result("blocked", "当前基建方案未准备好，只保留基建缺项",
                          data={"blocked_chains": ["Infrast"]})
        return None

    def execute_daily_chains(self, chains):
        if self.preflight(chains) is not None or not self.queue_idle():
            return {}
        app = self.runtime
        app._initialize_current_run_evidence_boundary()
        if app.run_maa_daily_tasks(enabled_tasks=set(chains)) is not True:
            return {}
        completed = app.wait_maa_complete(timeout=1200, continue_after_chain_error=True,
                                          prestarted_boundary=True)
        if not self.queue_idle():
            return {}  # No forced stop, full-day fallback or environment cleanup.
        text = app._get_current_maa_run_log()
        self.output.mkdir(parents=True, exist_ok=True)
        proof = self.output / "current_daily_queue.log"
        proof.write_text(text, encoding="utf-8")
        now = self.now().isoformat()
        rows = {}
        for chain in chains:
            valid = app._taskchain_status(text, chain).get("ok") is True
            if chain == "Infrast":
                valid = valid and self.base_effect_verified() is True
            rows[chain] = {"verified": valid, "completed_at": now, "queue_returned_complete": completed is True,
                           "evidence": str(proof), "source": "current_queue_boundary"}
        return rows
