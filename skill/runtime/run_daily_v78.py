"""V78: full portable bootstrap, verified Python, durable pre-game failures."""
from __future__ import annotations
from portable_paths import resolve_path as _portable_path

import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
PYTHON = Path(_portable_path('python'))
ENTRYPOINT = "run_daily_v78.py --mode full"


def ensure_interpreter(args):
    if Path(sys.executable).resolve() == PYTHON.resolve():
        return None
    if not PYTHON.is_file():
        raise RuntimeError("Verified daily Python is missing: " + str(PYTHON))
    # Re-enter once, before importing the controller or performing game actions.
    return subprocess.run([str(PYTHON), "-X", "utf8", "-u", str(Path(__file__).resolve()),
                           *args], cwd=ROOT, check=False).returncode


def check_entry(at=None):
    import run_daily_v75 as v75
    import daily_portable_bootstrap_v1 as bootstrap
    from production_component_gate import resolve_production_recipes

    handoff = v75._read(ROOT / ".project-reasoning/AUTOMATION_HANDOFF.json")
    contract = v75._read(ROOT / "PROJECT_CONTRACT.json")
    if handoff.get("status") != "active" or handoff.get("entrypoint") != ENTRYPOINT:
        raise ValueError("Daily V78 is not the active production entry")
    if handoff["workflow_binding"]["contract_goal_revision"] != contract["goal_memory"]["revision"]:
        raise ValueError("V78 contract revision mismatch")
    registry_path = ROOT / ".project-reasoning/COMPONENTS.json"
    gate = resolve_production_recipes(registry_path, handoff["required_recipes"])
    selected = {item for recipe in gate["resolved"] for item in recipe["components"]}
    for component in v75._read(registry_path)["components"]:
        if component["id"] in selected:
            for artifact in component.get("artifacts", []):
                path = (ROOT / artifact["path"]).resolve()
                path.relative_to(ROOT)
                if v75._sha(path) != artifact["sha256"].upper():
                    raise ValueError("Production artifact changed: " + artifact["path"])
    if v75._sha(__file__) != handoff["production_snapshot_sha256"].upper():
        raise ValueError("V78 entry snapshot changed")
    return {"status": "PASS", "entrypoint": ENTRYPOINT,
            "checked_at": (at or datetime.now().astimezone()).isoformat(),
            "maa": bootstrap.preflight(), "game_actions": 0}


def _save(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def full():
    # This receipt exists even when an adapter fails before the engine manifest.
    run_id = "daily-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid4().hex[:8]
    receipt_path = ROOT / "outputs/bootstrap_receipts" / (run_id + ".json")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = ROOT / "outputs/run_manifests" / (run_id + ".json")
    data = {"run_id": run_id, "entrypoint": ENTRYPOINT, "status": "preparing",
            "created_at": datetime.now().astimezone().isoformat(),
            "manifest_path": str(manifest), "business_complete": False}
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    old_argv = list(sys.argv)
    old_check = None
    previous = None
    try:
        check_entry()
        import run_daily_v77 as previous
        import daily_portable_bootstrap_v1 as bootstrap
        old_check = previous.check_entry
        previous.check_entry = check_entry
        sys.argv = [str(Path(__file__)), "--mode", "full", "--run-id", run_id]
        with bootstrap.resource_paths():
            result = previous.full()
        data.update(status="execution_result_unverified", exit_code=result)
        if manifest.exists():
            actual = json.loads(manifest.read_text(encoding="utf-8"))
            if actual.get("run_id") == run_id:
                data.update(status=actual.get("status", "execution_result_unverified"),
                            business_complete=actual.get("business_complete") is True,
                            cleanup_verified=actual.get("cleanup_verified") is True)
        return result
    except BaseException as exc:
        data.update(status="execution_failed" if manifest.exists() else "blocked_before_game_action",
                    error=f"{type(exc).__name__}: {exc}",
                    traceback=traceback.format_exc())
        if not manifest.exists():
            data.update(game_actions=0, current_run_verified_fights=0,
                        current_sanity=None, sanity_consumed=0,
                        recovery="Repair bootstrap; do not infer prior game effects or daily completion.")
        traceback.print_exc()
        return 1
    finally:
        sys.argv = old_argv
        if previous is not None and old_check is not None:
            previous.check_entry = old_check
        data["finished_at"] = datetime.now().astimezone().isoformat()
        _save(receipt_path, data)
        print(json.dumps({"bootstrap_receipt": str(receipt_path), "status": data["status"]},
                         ensure_ascii=False))


def cli(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    rc = ensure_interpreter(args)
    if rc is not None:
        return rc
    if args == ["--check-only"]:
        print(json.dumps(check_entry(), ensure_ascii=False))
        return 0
    if args == ["--mode", "full"]:
        return full()
    raise SystemExit("V78 accepts --mode full or --check-only")


if __name__ == "__main__":
    raise SystemExit(cli())
