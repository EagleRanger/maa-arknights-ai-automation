"""Explicit task dispatch; workers cannot implicitly advance or finalise a day.

This is an execution contract, not a scheduler or an authorization service.
The existing project handoff remains authoritative for real runs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Mapping
import hashlib
import json
import os


STATUSES = {"succeeded", "partial", "blocked", "failed", "interrupted", "unknown", "skipped"}


@dataclass(frozen=True)
class Result:
    status: str
    detail: str
    evidence: tuple[str, ...] = ()
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError("invalid module status: " + self.status)
        if self.status == "succeeded" and not self.evidence:
            raise ValueError("success requires evidence, not a truthy return value")


@dataclass(frozen=True)
class Step:
    key: str
    module: str
    inputs: dict = field(default_factory=dict)
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class Module:
    run: Callable[[dict], Result]
    # Reading a new screen can repeat; an uncertain mutation cannot.
    read_only: bool = False


class ReceiptStore:
    """One caller-owned run receipt; no second project state or scheduler."""
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None

    def save(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)


class Dispatcher:
    """Only named steps run. No fallback, daily main(), popup or game cleanup."""
    def __init__(self, modules: Mapping[str, Module]):
        self.modules = dict(modules)

    def run(self, steps, *, store=None, on_result=None):
        steps = tuple(steps)
        keys = set()
        for step in steps:
            if not step.key or step.key in keys:
                raise ValueError("missing or duplicate step key")
            if step.module not in self.modules:
                raise ValueError("unknown module: " + step.module)
            if not set(step.requires) <= keys:
                raise ValueError("dependencies must name earlier explicit steps")
            keys.add(step.key)
        shape = [asdict(step) for step in steps]
        fingerprint = hashlib.sha256(json.dumps(shape, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        receipt = store.load() if store else None
        if receipt is not None and receipt.get("plan_sha256") != fingerprint:
            raise ValueError("receipt belongs to a different task plan; do not reuse it")
        receipt = receipt or {"schema_version": 1, "plan_sha256": fingerprint, "steps": {}}
        results = {}
        for step in steps:
            module = self.modules[step.module]
            old = receipt["steps"].get(step.key)
            if old and not module.read_only and old["status"] != "blocked":
                # A previous success is preserved as historical execution. All
                # uncertain mutations require reconciliation, never auto-retry.
                if old["status"] == "succeeded":
                    result = Result("succeeded", old["detail"], tuple(old["evidence"]),
                                    dict(old.get("data", {}), reused_previous_effect=True))
                else:
                    result = Result("unknown", "上次执行结果待对账，未重复操作", data={"previous": old})
                results[step.key] = result
                if on_result: on_result(step.key, result)
                continue
            if any(results[key].status != "succeeded" for key in step.requires):
                result = Result("skipped", "依赖任务尚未完成，本项未执行")
                # An unattempted dependency skip is not a mutation receipt.
                results[step.key] = result
                if on_result: on_result(step.key, result)
                continue
            receipt["steps"][step.key] = {"status": "running", "module": step.module}
            if store:
                store.save(receipt)  # Persist before a possibly committing action.
            try:
                result = module.run(dict(step.inputs))
                if not isinstance(result, Result):
                    raise TypeError("module must return Result; bool/None is not completion")
            except (KeyboardInterrupt, SystemExit):
                receipt["steps"][step.key] = asdict(Result("interrupted", "任务被中断，现场未自动关闭"))
                if store:
                    store.save(receipt)
                raise
            except Exception as exc:
                # A thrown exception cannot prove that an external action failed
                # before taking effect. Preserve unknown for mutating modules.
                result = Result("failed" if module.read_only else "unknown",
                                type(exc).__name__ + ": " + str(exc))
            results[step.key] = result
            if on_result: on_result(step.key, result)
            receipt["steps"][step.key] = asdict(result)
            if store:
                store.save(receipt)
        return results


class DailyCoordinator:
    """Composition only; daily task semantics live in daily_tasks.py.

Finalisation is explicit and separate. Calling a worker never calls this.
No result is upgraded to success because the environment was closed.
"""
    def __init__(self, dispatcher, finalise):
        self.dispatcher, self.finalise = dispatcher, finalise

    def run(self, steps, *, store, close_environment=False):
        results = self.dispatcher.run(steps, store=store)
        finalisation = None
        if close_environment:
            receipt = store.load()
            previous = receipt.get("finalisation")
            if previous is not None:
                finalisation = dict(previous, reused=True)
            else:
                # A crash after a popup/close must not replay it on resume.
                receipt["finalisation"] = {"status": "running"}
                store.save(receipt)
                try:
                    finalisation = self.finalise(results)
                    if not isinstance(finalisation, dict):
                        raise TypeError("finalisation must return an evidence record")
                    finalisation = dict(finalisation, status="returned")
                except (KeyboardInterrupt, SystemExit):
                    receipt["finalisation"] = {"status": "interrupted", "needs_reconciliation": True}
                    store.save(receipt)
                    raise
                except Exception as exc:
                    finalisation = {"status": "unknown", "needs_reconciliation": True,
                                    "detail": type(exc).__name__ + ": " + str(exc)}
                receipt["finalisation"] = finalisation
                store.save(receipt)
        return results, finalisation
