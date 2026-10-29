"""Accept the actual MiddleBattleRecord product callback, still queue/room bound."""
from contextlib import contextmanager
from unittest.mock import patch
import json
from pathlib import Path
import daily_base_333_verified_execution_v3 as rooms
import daily_base_333_verified_execution_v4 as previous

_verify_v4 = previous.verify_from_files


def verify_from_files(paths, not_before, expected, config):
    # The installed MaaCore returns CombatRecord on inspection, but
    # MiddleBattleRecord after switching to the selected medium record recipe.
    # Scope the alias to this read only; never change the frozen V3 source/table.
    accepted = rooms.PRODUCT_CALLBACK_ALIASES["Battle Record"] | {"MiddleBattleRecord"}
    with patch.dict(rooms.PRODUCT_CALLBACK_ALIASES, {"Battle Record": accepted}):
        receipt = _verify_v4(paths, not_before, expected, config)
    receipt["receipt_version"] = "v5"
    receipt["product_alias_fix"] = "Battle Record:CombatRecord|MiddleBattleRecord"
    return receipt


def drone_log_for_queue(paths, not_before):
    """Read DroneConfirm for the same admitted queue, not a moving log tail."""
    paths = list(paths)
    text, source = previous.collect_infrast(paths, not_before)
    if not source["task_identity"] or not source["append_at"]:
        return text
    for path in map(Path, paths):
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                match = previous.HEADER.match(line)
                if (not match or match["pid"] != source["process_id"]
                        or previous.local_time(match["time"]) < previous.local_time(source["append_at"])
                        or previous.CALLBACK not in line):
                    continue
                event, _, payload = line.split(previous.CALLBACK, 1)[1].partition(" ")
                if event != "SubTaskCompleted":
                    continue
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                if (data.get("taskchain") == "Infrast"
                        and (data.get("uuid"), data.get("taskid")) == tuple(source["task_identity"])
                        and (data.get("details") or {}).get("task") == "DroneConfirm"):
                    text += line
                    return text
    return text


@contextmanager
def engine_boundary():
    # V4's final install dereferences its reader only at actual receipt time.
    with patch.object(previous, "verify_from_files", verify_from_files):
        yield
