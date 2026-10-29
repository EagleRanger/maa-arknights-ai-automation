"""Bind manifest metadata to the checked outer workflow without changing effects."""
from contextlib import contextmanager
from functools import wraps
import json
import sys


def stamp(data, binding):
    if "legacy_engine_workflow" not in data:
        data["legacy_engine_workflow"] = data.get("workflow")
    data.update(workflow=binding["workflow"], entrypoint=binding["entrypoint"],
                production_handoff=binding["handoff_id"],
                production_snapshot_sha256=binding["sha256"])


@contextmanager
def boundary(runtime, root, binding):
    import run_daily as base
    old_base, old_runtime, old_settle = base.main, runtime.main, base.settle_manifest
    state = {}

    @wraps(old_base)
    def main(*args, **kwargs):
        if "--run-id" in sys.argv:
            state["run_id"] = sys.argv[sys.argv.index("--run-id") + 1]
        return old_base(*args, **kwargs)

    @wraps(old_runtime)
    def engine(*args, **kwargs):
        run_id = state.get("run_id")
        if run_id:
            path = root/"outputs/run_manifests"/(run_id+".json")
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("run_id") != run_id:
                    raise RuntimeError("Run manifest identity mismatch")
                stamp(data, binding)
                tmp = path.with_suffix(".identity.tmp")
                tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
                tmp.replace(path)
        return old_runtime(*args, **kwargs)

    @wraps(old_settle)
    def settle(data, scope_ok, report):
        old_settle(data, scope_ok, report)
        stamp(data, binding)

    base.main, runtime.main, base.settle_manifest = main, engine, settle
    try:
        yield
    finally:
        base.main, runtime.main, base.settle_manifest = old_base, old_runtime, old_settle
