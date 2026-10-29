"""Recover compact, queue-bound Infrast evidence across MaaCore log rotation.

No game actions. The old polling cache is intentionally bounded, but a moving
2,000-line rotation tail is not a complete six-room acceptance receipt.
"""
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
import json
import re

import daily_base_333_verified_execution_v1 as legacy
import daily_base_333_verified_execution_v3 as previous

HEADER = re.compile(r"^\[(?P<time>[\d-]+ [\d:.]+)\].*?\[Px(?P<pid>\d+)\]")
CALLBACK = "Assistant::append_callback | "
WANTED = {"ProductOfFacility", "ProductChanged", "InfrastConfirmButton"}
MAX_RECEIPT_CHARS = 512 * 1024


def local_time(value):
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if stamp.tzinfo:
        stamp = stamp.astimezone().replace(tzinfo=None)
    return stamp


def collect_infrast(paths, not_before):
    """Stream oldest-to-newest files; retain only the latest admitted queue.

    A newer append always invalidates the previous candidate. Never fill a
    missing room from another task ID/process/UUID or from before this call.
    """
    threshold = local_time(not_before)
    rows, refs, pid, identity, appended = [], [], None, None, None
    chars = 0
    for path in map(Path, paths):
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as stream:
            for index, line in enumerate(stream, 1):
                match = HEADER.match(line)
                if not match or local_time(match["time"]) < threshold:
                    continue
                keep = False
                if "append_task Infrast {" in line:
                    rows, refs, chars = [], [], 0
                    pid, identity, appended = match["pid"], None, match["time"]
                    keep = True
                elif pid == match["pid"] and CALLBACK in line:
                    event, _, payload_text = line.split(CALLBACK, 1)[1].partition(" ")
                    try:
                        payload = json.loads(payload_text)
                    except ValueError:
                        continue
                    if payload.get("taskchain") != "Infrast":
                        continue
                    key = (payload.get("uuid"), payload.get("taskid"))
                    if event == "TaskChainStart" and identity is None:
                        if not key[0] or key[1] is None:
                            continue
                        identity, keep = key, True
                    elif identity is not None and key == identity:
                        keep = (event in {"TaskChainCompleted", "TaskChainError", "TaskChainStopped"}
                                or (event == "SubTaskExtraInfo" and payload.get("what") in WANTED))
                if keep:
                    rows.append(line)
                    refs.append({"path": str(path), "line": index, "time": match["time"]})
                    chars += len(line)
                    if chars > MAX_RECEIPT_CHARS:
                        raise ValueError("Infrast semantic evidence exceeds bound; no truncated acceptance")
    return "".join(rows), {"not_before": threshold.isoformat(), "append_at": appended,
                            "process_id": pid, "task_identity": identity, "lines": refs,
                            "retained_chars": chars, "reader": "rotation_stream_v4"}


def verify_from_files(paths, not_before, expected, config):
    text, evidence = collect_infrast(paths, not_before)
    receipt = previous.verify_infrast_execution(text, expected, config)
    receipt["evidence_source"] = evidence
    receipt["receipt_version"] = "v4"
    # A task that stopped/errored cannot pass merely because an earlier complete
    # token exists. The six-room parser continues to own product semantics.
    terminal = re.findall(r"\| (TaskChainCompleted|TaskChainError|TaskChainStopped) ", text)
    if not terminal or terminal[-1] != "TaskChainCompleted":
        receipt.update(status="execution_unverified", task_chain_completed=False,
                       reason="infrast_terminal_not_completed")
    return receipt


def install(runtime):
    old_run = runtime.run_maa_daily_tasks
    fallback = legacy.verify_infrast_execution
    state = {}

    @wraps(old_run)
    def run(*args, **kwargs):
        state["not_before"] = datetime.now()
        return old_run(*args, **kwargs)

    def verify(text, expected, config=legacy.ACTIVE_CONFIG):
        lower = state.get("not_before")
        if lower is None:
            # No newly dispatched queue: do not borrow another queue's files.
            return fallback(text, expected, config)
        path = Path(runtime.MAA_LOG)
        try:
            return verify_from_files([path.with_name("asst.bak.log"), path], lower, expected, config)
        except (OSError, ValueError) as exc:
            return {"status": "execution_unverified", "receipt_version": "v4",
                    "products_verified": False, "operator_rotation_verified": False,
                    "reason": "queue_evidence_unavailable:" + str(exc)}

    runtime.run_maa_daily_tasks = run
    legacy.verify_infrast_execution = verify
    runtime._RUN_SUMMARY.setdefault("base_333_policy", {}).update(
        receipt_version="v4", rotation_safe_stream=True)
    return run, verify


@contextmanager
def engine_boundary(runtime):
    old_main, old_run, old_verify = runtime.main, runtime.run_maa_daily_tasks, legacy.verify_infrast_execution

    @wraps(old_main)
    def main(*args, **kwargs):
        install(runtime)
        return old_main(*args, **kwargs)

    runtime.main = main
    try:
        yield
    finally:
        runtime.main, runtime.run_maa_daily_tasks = old_main, old_run
        legacy.verify_infrast_execution = old_verify
