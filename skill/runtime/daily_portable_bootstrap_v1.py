"""Scope every legacy bootstrap resource writer to the selected MAA tree.

Changing runtime globals alone does not change Python's bound default arguments
or a function imported with ``from ... import ...``. Preserve the frozen
adapters, but supply their resource paths explicitly for the whole full run.
"""
from __future__ import annotations

import importlib
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from uuid import uuid4

import maa_portable_runtime_v1 as portable

RESOURCE_MODULES = (
    "maa_resource_compat_v23", "maa_series_resource_v1",
    "maa_series_resource_v2", "maa_series_resource_v3",
)


def preflight(root=portable.PORTABLE_ROOT):
    result = portable.preflight(root)
    root = Path(result["root"])
    tasks = root / "resource/tasks/tasks.json"
    if not tasks.is_file():
        raise RuntimeError("portable MAA tasks.json missing")
    probe = tasks.parent / (".codex-write-probe-" + uuid4().hex)
    try:
        with probe.open("x", encoding="utf-8") as stream:
            stream.write("portable resource write probe\n")
    finally:
        probe.unlink(missing_ok=True)
    return {**result, "tasks_writable": True, "tasks_path": str(tasks)}


@contextmanager
def resource_paths(root=portable.PORTABLE_ROOT):
    root = Path(root).resolve()
    root.relative_to(portable.ROOT)
    tasks = root / "resource/tasks/tasks.json"
    config = root / "config/gui.new.json"
    originals = []

    def replace(module, name, wrapper):
        originals.append((module, name, getattr(module, name)))
        setattr(module, name, wrapper)

    def resource_wrapper(original):
        @wraps(original)
        def install(runtime, *, tasks_path=None):
            if Path(runtime.MAA_ROOT).resolve() != root:
                raise ValueError("MAA resource root disagrees with runtime root")
            if tasks_path is not None and Path(tasks_path).resolve() != tasks:
                raise ValueError("MAA adapter requested a different resource tree")
            return original(runtime, tasks_path=tasks)
        return install

    try:
        for name in RESOURCE_MODULES:
            module = importlib.import_module(name)
            replace(module, "install", resource_wrapper(module.install))
        recruit = importlib.import_module("maa_recruit_preferences_v1")
        v3 = importlib.import_module("run_daily_v3")
        original_recruit = recruit.ensure_preferences

        @wraps(original_recruit)
        def preferences(config_path=None):
            if config_path is not None and Path(config_path).resolve() != config:
                raise ValueError("Recruit preferences requested a different MAA tree")
            return original_recruit(config)

        replace(recruit, "ensure_preferences", preferences)
        replace(v3, "ensure_preferences", preferences)
        yield {"root": str(root), "tasks_path": str(tasks), "config_path": str(config)}
    finally:
        for module, name, original in reversed(originals):
            setattr(module, name, original)
