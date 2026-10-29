"""Explicit custom-plan drones; keep accepted 333 products and rotations.

MaaCore ignores its generic ``drones`` parameter in Custom mode. The plan
must have its own drones object. This module never changes inventory policy.
The drone-only repair uses pre + skip, which MaaCore executes before its
skip-room branch, so an accepted daily rotation is not repeated.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import argparse
import json
import re

import daily_base_333_verified_execution_v1 as base

ROOT = Path(__file__).resolve().parent


def drone_target(payload):
    plans = payload.get("plans") or []
    if len(plans) != 1:
        raise ValueError("drone binding requires the selected single 333 plan")
    rooms = plans[0].get("rooms", {}).get("trading") or []
    if len(rooms) != 3:
        raise ValueError("333 trading layout is incomplete")
    # The existing policy selected SyntheticJade when a jade line exists.
    for product in ("Orundum", "LMD"):
        for index, room in enumerate(rooms, 1):
            if room.get("product") == product:
                return {"enable": True, "room": "trading", "index": index, "order": "post"}
    raise ValueError("no accepted trading product for acceleration")


def with_drones(payload, only=False, target=None):
    result = deepcopy(payload)
    target = deepcopy(target) if target is not None else drone_target(result)
    rooms = result["plans"][0]["rooms"].get(target.get("room")) or []
    if (target.get("room") not in {"trading", "manufacture"}
            or type(target.get("index")) is not int
            or not 1 <= target["index"] <= len(rooms)):
        raise ValueError("drone target must identify a real selected-plan room")
    # MAA 6.18 executes pre drones before the skip branch. The actual failure
    # was the assistance ROI, not skipped rooms. Repairs must not rotate twice.
    if only:
        target['order'] = 'pre'
        for rooms in result['plans'][0]['rooms'].values():
            for room in rooms:
                room['skip'] = True
    result["plans"][0]["drones"] = target
    return result


def build_single_plan_config(source, index):
    return with_drones(base.build_single_plan_config(source, index))


@contextmanager
def engine_boundary(runtime):
    """Compose outside existing daily entry; frozen base modules stay intact."""
    original = base.build_single_plan_config

    def build(source, index):
        return with_drones(original(source, index))

    base.build_single_plan_config = build
    try:
        yield
    finally:
        base.build_single_plan_config = original


def parse_balance(text):
    """Read the base's unique drone ratio, including the observed 225 cap.

    Power (810/810), room occupancy and sanity (x/210) are not drones.
    Accept capacity steps of 25 rather than treating the old 200 as eternal.
    """
    text = str(text or "")
    if not any(anchor in text for anchor in ("控制中枢", "进驻总览", "建造模式", "无人机")):
        return None
    pairs = re.findall(r"(?<!\d)(\d{1,3})\s*[/／]\s*(\d{3})(?!\d)", text)
    values = [(int(x), int(cap)) for x, cap in pairs
              if 200 <= int(cap) <= 500 and int(cap) % 25 == 0
              and 0 <= int(x) <= int(cap)]
    return values[0] if len(values) == 1 else None


def parse_count(text):
    balance = parse_balance(text)
    return balance[0] if balance is not None else None


def observe(runtime, phase):
    samples = []
    # The first base frame can still be animating with its toolbar absent.
    # Wait read-only for two stable observations; never click for a count.
    for _ in range(4):
        path = runtime.shot("drones_" + phase)
        text = runtime.ocr_text(path) if path else ""
        balance = parse_balance(text)
        samples.append({"value": balance[0] if balance else None,
                        "capacity": balance[1] if balance else None, "screenshot": path, "ocr": text,
                        "observed_at": datetime.now().astimezone().isoformat()})
        if (len(samples) >= 2 and balance is not None
                and samples[-2]["value"] == balance[0]
                and samples[-2]["capacity"] == balance[1]):
            break
        runtime.wait(1)
    value = samples[-1]["value"]
    capacity = samples[-1]["capacity"]
    return {"phase": phase, "samples": samples, "value": value, "capacity": capacity,
            "verified": isinstance(value, int) and samples[-2]["value"] == value
            and samples[-2]["capacity"] == capacity}


def verify_usage(before, after, log_text):
    b, a = before.get("value"), after.get("value")
    cap = before.get("capacity", 200)
    same_cap = after.get("capacity", 200) == cap
    observed = (before.get("verified") is True and after.get("verified") is True
                and type(cap) is int and 200 <= cap <= 500 and cap % 25 == 0
                and same_cap and type(b) is int and type(a) is int
                and 0 <= a <= cap and 0 <= b <= cap)
    confirmed = bool(re.search(r'"task"\s*:\s*"DroneConfirm"', log_text))
    completed = bool(re.search(r'TaskChainCompleted.*"taskchain"\s*:\s*"Infrast"', log_text))
    applied = bool(observed and b > a and confirmed and completed)
    # Never call a decrease "used up" while a material balance remains.
    exhausted = bool(applied and a <= 2)
    return {"status": "used_up_verified" if exhausted else "partial" if applied else "unverified",
            "before": before, "after": after, "drone_confirm": confirmed,
            "infrast_completed": completed, "usage_verified": applied,
            "used_up_verified": exhausted, "remaining": a if observed else None,
            "observed_net_decrease": b - a if observed else None}


def prepare_drone_only(runtime, output, target=None):
    """Idle-only configuration write; no game or MAA starts in this function."""
    if runtime._maa_task_queue_running() is True:
        raise RuntimeError("MAA queue active; do not replace the live configuration")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    gui_path = Path(runtime.MAA_CONFIG) / "gui.new.json"
    cfg = runtime._read_json_file(str(gui_path), {})
    payload = runtime._read_json_file(str(base.ACTIVE_CONFIG), {})
    corrected = with_drones(payload, target=target)
    repair = with_drones(payload, only=True, target=target)
    old_infrast = deepcopy(next(x for x in runtime._task_queue(cfg) if x.get("TaskType") == "Infrast"))
    backup = output / "gui.before_drone_only.json"
    runtime._atomic_write_json(str(backup), cfg)
    repair_path = output / "drone_only_plan.json"
    runtime._atomic_write_json(str(repair_path), repair)
    runtime._atomic_write_json(str(base.ACTIVE_CONFIG), corrected)
    infrast = next(x for x in runtime._task_queue(cfg) if x.get("TaskType") == "Infrast")
    infrast.update(Mode="Custom", Filename=str(repair_path.resolve()), PlanSelect=0,
                   RoomList=[{"Room": "Mfg" if repair["plans"][0]["drones"]["room"] == "manufacture" else "Trade"}],
                   OriginiumShardAutoReplenishment=False)
    runtime._atomic_write_json(str(gui_path), cfg)
    readback = runtime._read_json_file(str(gui_path), {})
    actual = next(x for x in runtime._task_queue(readback) if x.get("TaskType") == "Infrast")
    if actual != infrast or runtime._read_json_file(str(repair_path), {}) != repair:
        raise RuntimeError("drone-only configuration readback failed")
    # Even an idle existing MAA window retains its old in-memory parameters.
    if runtime._maa_process_exists() is True:
        runtime.reload_maa_after_config_switch("无人机专项参数重载")
    receipt = {"status": "configured_only", "plan": str(repair_path),
               "backup": str(backup), "target": repair["plans"][0]["drones"],
               "previous_infrast": old_infrast, "accepted_products_unchanged":
               base.expected_products(corrected) == base.expected_products(payload)}
    runtime._atomic_write_json(str(output / "configuration_receipt.json"), receipt)
    return receipt


def restore_infrast(runtime, receipt):
    if runtime._maa_task_queue_running() is True:
        raise RuntimeError("cannot restore configuration while MAA runs")
    gui_path = Path(runtime.MAA_CONFIG) / "gui.new.json"
    cfg = runtime._read_json_file(str(gui_path), {})
    task = next(x for x in runtime._task_queue(cfg) if x.get("TaskType") == "Infrast")
    task.clear()
    task.update(deepcopy(receipt["previous_infrast"]))
    runtime._atomic_write_json(str(gui_path), cfg)
    check = runtime._read_json_file(str(gui_path), {})
    return next(x for x in runtime._task_queue(check) if x.get("TaskType") == "Infrast") == task


def open_base(runtime):
    """Existing home navigation followed by the visible base label only."""
    path = runtime.shot("drones_page_before_navigation")
    if parse_count(runtime.ocr_text(path)) is not None:
        return True
    if not runtime.goto_main_menu():
        return False
    path = runtime.shot("drones_home_for_base_label")
    candidates = [(x, y) for text, x, y in runtime.ocr(path)
                  if re.sub(r"\s+", "", text).rstrip(">›》") == "基建"]
    if len(candidates) != 1:
        return False
    runtime.tap(*candidates[0])
    runtime.wait(3)
    return True


def _execute_drone_only(runtime, output, target=None):
    """One supervised current-balance repair, no daily or resource farming."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if runtime._maa_task_queue_running() is True:
        raise RuntimeError("current queue still owns the game")
    if not runtime.detect_mumu_adb_port() or not open_base(runtime):
        result = {"status": "unverified", "reason": "base_not_reached", "game_actions": "navigation_only"}
        runtime._atomic_write_json(str(output / "receipt.json"), result)
        return result
    before = observe(runtime, "before")
    runtime._atomic_write_json(str(output / "before.json"), before)
    if not before["verified"]:
        result = {"status": "unverified", "reason": "current_drone_balance_unverified", "before": before}
        runtime._atomic_write_json(str(output / "receipt.json"), result)
        return result
    receipt = prepare_drone_only(runtime, output, target=target)
    try:
        if before["value"] == 0:
            result = {"status": "already_empty_verified", "before": before,
                      "usage_verified": False, "used_up_verified": True, "remaining": 0}
        elif not runtime.run_maa_daily_tasks(enabled_tasks={"Infrast"}):
            result = {"status": "unverified", "reason": "infrast_start_failed", "before": before}
        else:
            completed = runtime.wait_maa_complete(timeout=600, prestarted_boundary=True)
            idle = runtime._maa_task_queue_running() is False
            after = observe(runtime, "after") if completed is True and idle and open_base(runtime) else {
                "verified": False, "value": None, "reason": "base_not_reached_after"}
            result = verify_usage(before, after, runtime._get_current_maa_run_log())
            result["wait_result"] = completed
            if completed is not True:
                result.update(status="unverified", usage_verified=False, used_up_verified=False)
        result["configuration"] = receipt
        result["restored_infrast"] = (restore_infrast(runtime, receipt)
                                      if runtime._maa_task_queue_running() is False else False)
        runtime._atomic_write_json(str(output / "receipt.json"), result)
        return result
    except BaseException:
        # Never overwrite parameters while the queue still controls the game.
        if runtime._maa_task_queue_running() is False:
            restore_infrast(runtime, receipt)
        raise


def execute_drone_only(runtime, output, target=None):
    if target is not None and target.get("room") == "manufacture":
        # Manufacturing has its own assistance UI; do not mutate Trade ROI.
        return _execute_drone_only(runtime, output, target=target)
    from daily_trade_drone_roi_v1 import resource_boundary
    with resource_boundary(runtime, output) as roi:
        result = _execute_drone_only(runtime, output, target=target)
    result['roi_resource_restored'] = roi['restored']
    runtime._atomic_write_json(str(Path(output) / 'receipt.json'), result)
    return result


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-drone-only", action="store_true", required=True)
    parser.add_argument("--output", default="outputs/drone_repair_20261005")
    args = parser.parse_args()
    from vector_special_runtime_v1 import runtime
    result = execute_drone_only(runtime(), ROOT / args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("used_up_verified") is True else 2


if __name__ == "__main__":
    raise SystemExit(cli())
