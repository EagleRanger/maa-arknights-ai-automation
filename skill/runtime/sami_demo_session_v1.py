"""Offline-tested session guard for the existing single Sami composition.

Not a launcher: caller must supply fresh game/owner/recorder checks. The claim
prevents replay of this run, not manual/foreign control of the emulator. No
process enumeration, environment startup, queue takeover or global cleanup.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from threading import Lock

from sami_demo_once_v1 import run_once


_IN_PROCESS = Lock()


def _write(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _sha(data):
    return hashlib.sha256(data).hexdigest().upper()


@contextmanager
def isolated_config(app, session_dir, evidence):
    """Redirect the legacy temporary-config context to our own exact copy.

    Production file is never written or restored. If somebody changes it,
    preserve their edit and report that the baseline changed.
    """
    original_pointer = app.MAA_CONFIG
    original_path = Path(original_pointer) / "gui.new.json"
    original = original_path.read_bytes()
    json.loads(original.decode("utf-8-sig"))
    isolated_dir = Path(session_dir) / "maa-config"
    isolated_dir.mkdir(exist_ok=False)
    isolated_path = isolated_dir / "gui.new.json"
    isolated_path.write_bytes(original)
    evidence.update(source=str(original_path), isolated=str(isolated_path),
                    original_sha256=_sha(original), pointer_restored=False,
                    isolated_restored=False, production_unchanged=None)
    app.MAA_CONFIG = str(isolated_dir)
    try:
        yield
    finally:
        app.MAA_CONFIG = original_pointer
        evidence["pointer_restored"] = app.MAA_CONFIG == original_pointer
        # Restore only the copy owned by this run, including a legacy context
        # which swallowed its restoration error. Never touch the production.
        try:
            isolated_path.write_bytes(original)
            evidence["isolated_restored"] = isolated_path.read_bytes() == original
        except OSError as exc:
            evidence["restore_error"] = f"{type(exc).__name__}: {exc}"
        try:
            evidence["production_unchanged"] = original_path.read_bytes() == original
        except OSError as exc:
            evidence["production_readback_error"] = f"{type(exc).__name__}: {exc}"


def run_session(*, session_dir, app, sami, ready, recording, deadline,
                needs_exploration, clock=None, environment_owner=None):
    """Reserve one run durably BEFORE inputs, then invoke the existing logic.

    A second invocation reads the receipt and returns no_action, even if the
    first process crashed. Unknown prior effects need reconciliation, not an
    automatic second exploration. A new directory is not controller ownership;
    the independent ready callback remains mandatory throughout the operation.
    """
    root = Path(session_dir)
    if not _IN_PROCESS.acquire(blocking=False):
        return {"status": "blocked_before_input", "reason": "demo_already_in_process"}
    receipt = {"status": "preparing", "configuration": {}, "input_phase_started": False,
               "ownership": {"acquired": False, "released": False}}
    owned = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        claim = root / "single_run.claim"
        try:
            with claim.open("x", encoding="utf-8") as stream:
                stream.write("One run reserved. Reconcile receipt before any new attempt.\n")
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            previous = None
            try:
                previous = json.loads((root / "session.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            return {"status": "no_action", "reason": "existing_run_not_replayed",
                    "previous": previous, "prior_effects_unknown": not previous or
                    previous.get("status") not in {"completed", "completed_existing_progress_only",
                        "completed_with_unshown_effects", "blocked_before_input"}}
        _write(root / "session.json", receipt)
        # Never borrow/release an existing caller's handle. Acquire the same
        # project mutex used by daily runs, not a separate roguelike lock.
        external = environment_owner is not None
        external_handle = getattr(app, "_RUN_MUTEX_HANDLE", None)
        if external and (environment_owner.app is not app or not environment_owner.owns()
                         or not external_handle):
            receipt.update(status="blocked_before_input", reason="external_owner_unverified")
            _write(root / "session.json", receipt)
            return receipt
        if not external and getattr(app, "_RUN_MUTEX_HANDLE", None):
            receipt.update(status="blocked_before_input", reason="existing_caller_lease")
            _write(root / "session.json", receipt)
            return receipt
        try:
            acquired = True if external else app.acquire_single_instance()
        except Exception as exc:
            receipt.update(status="blocked_before_input", reason="project_lease_unverified",
                           error={"type": type(exc).__name__, "message": str(exc)})
            _write(root / "session.json", receipt)
            return receipt
        if acquired is not True:
            receipt.update(status="blocked_before_input", reason="project_controller_busy")
            _write(root / "session.json", receipt)
            return receipt
        owned = not external
        receipt["ownership"]["acquired"] = True
        if external:
            receipt["ownership"].update(external_owner=environment_owner.owner,
                                       release_responsibility="outer_environment_owner")

        def save(state):
            receipt["execution"] = state
            receipt["status"] = state["status"]
            # Inputs are potentially possible once navigation starts. This is
            # not proof that an individual click succeeded.
            receipt["input_phase_started"] = state.get("input_phase_started", False)
            _write(root / "session.json", receipt)

        try:
            with isolated_config(app, root, receipt["configuration"]):
                def unchanged_and_ready():
                    cfg = receipt["configuration"]
                    try:
                        unchanged = _sha(Path(cfg["source"]).read_bytes()) == cfg["original_sha256"]
                    except OSError:
                        unchanged = False
                    owner_ok = (not external or (environment_owner.owns() and
                                app._RUN_MUTEX_HANDLE == external_handle))
                    return unchanged and owner_ok and ready() is True
                result = run_once(app=app, sami=sami, ready=unchanged_and_ready, recording=recording,
                                  deadline=deadline, save=save, clock=clock,
                                  needs_exploration=needs_exploration)
            receipt["execution"] = result
            receipt["status"] = result["status"]
            cfg = receipt["configuration"]
            if not all(cfg.get(key) is True for key in (
                    "pointer_restored", "isolated_restored", "production_unchanged")):
                receipt["status"] = "partial"
                receipt["reason"] = "configuration_restore_or_source_changed"
        except Exception as exc:
            receipt.update(status="partial", reason="session_exception",
                           error={"type": type(exc).__name__, "message": str(exc)})
        _write(root / "session.json", receipt)
        return receipt
    finally:
        try:
            if owned:
                try:
                    receipt["ownership"]["released"] = app.release_single_instance() is True
                except Exception as exc:
                    receipt["ownership"]["error"] = f"{type(exc).__name__}: {exc}"
                if receipt["ownership"]["released"] is not True:
                    receipt.update(status="partial", reason="project_lease_release_unverified")
                _write(root / "session.json", receipt)
        finally:
            _IN_PROCESS.release()
