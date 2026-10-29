"""Bind one inventory decision to one MAA base plan and verify its effects.

The former dynamic 333 file stored four *production modes* as four MAA
rotation plans.  MAA advances ``PlanSelect`` after every completed Infrast
chain, so a successful gold-drain run left the UI pointing at an orundum
plan.  This adapter separates the two concepts:

* inventory policy selects one production mode;
* the selected mode is materialized as a one-plan runtime file;
* MAA may still rotate operators, but auto-advance wraps to the same plan;
* completion is accepted only when the current MaaCore log proves the plan,
  room products and operator confirmations.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_CONFIG = ROOT / "config" / "base_333_inventory_balance_v2.json"
ACTIVE_CONFIG = ROOT / "runtime_state" / "base_333_active_single_plan.json"

PRODUCT_ALIASES = {
    "Pure Gold": "PureGold",
    "Battle Record": "CombatRecord",
    "Originium Shard": "OriginStone",
    "LMD": "LMD",
    "Orundum": "SyntheticJade",
}
CHANGE_PROOFS = {
    "Pure Gold": ("ChangeProductToPureGold", "ProductFinalConfirm"),
    "Battle Record": ("ChangeProductToMiddleBattleRecord", "ProductFinalConfirm"),
    "Originium Shard": ("ChangeProductToOriginStone", "ProductFinalConfirm"),
    "LMD": ("ChangeToMoneyOrder", "VerifyTradeOrderChangedToMoney"),
    "Orundum": (
        "ChangeToSyntheticJadeFlagOrder",
        "VerifyTradeOrderChangedToSyntheticJade",
    ),
}


def build_single_plan_config(source, plan_index):
    plans = list((source or {}).get("plans") or [])
    if not isinstance(plan_index, int) or not 0 <= plan_index < len(plans):
        raise ValueError("selected 333 plan index is invalid")
    payload = deepcopy(source)
    selected = deepcopy(plans[plan_index])
    payload["title"] = f"库存平衡333：当日固定方案{plan_index}"
    payload["description"] = (
        f"由实时库存选择原方案{plan_index}；本文件只含一个生产方案，"
        "防止MAA把生产模式误当轮班并自动跳到下一模式。"
    )
    payload["id"] = int(source.get("id", 2026092001)) * 10 + plan_index
    payload["planTimes"] = "当日单方案"
    payload["selected_source_plan_index"] = plan_index
    payload["plans"] = [selected]
    return payload


def expected_products(payload):
    plans = list((payload or {}).get("plans") or [])
    if len(plans) != 1:
        raise ValueError("active 333 payload must contain exactly one plan")
    rooms = plans[0].get("rooms") or {}
    result = {}
    for facility, room_key in (("Mfg", "manufacture"), ("Trade", "trading")):
        for index, room in enumerate(rooms.get(room_key) or []):
            product = room.get("product")
            if product not in PRODUCT_ALIASES:
                raise ValueError(f"unsupported {facility} product: {product}")
            result[(facility, index)] = product
    if set(result) != {
        ("Mfg", 0), ("Mfg", 1), ("Mfg", 2),
        ("Trade", 0), ("Trade", 1), ("Trade", 2),
    }:
        raise ValueError("active 333 payload is not a complete 333 layout")
    return result


def _selected_config(runtime, decision):
    source_path = Path(getattr(runtime, "DYNAMIC_333_CONFIG", SOURCE_CONFIG))
    source = runtime._read_json_file(str(source_path), {}) or {}
    payload = build_single_plan_config(source, decision["plan_index"])
    ACTIVE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    runtime._atomic_write_json(str(ACTIVE_CONFIG), payload)
    readback = runtime._read_json_file(str(ACTIVE_CONFIG), {}) or {}
    if readback != payload:
        raise RuntimeError("single-plan 333 config readback mismatch")
    return payload


def apply_single_plan_config(runtime, decision):
    """Write and read back one exact production mode into MAA's task config."""

    summary = runtime._RUN_SUMMARY.setdefault("base_333", {})
    plan_index = (decision or {}).get("plan_index")
    if not isinstance(plan_index, int) or not 0 <= plan_index <= 2:
        summary.update(status="failed", reason="inventory_decision_unverified_or_plan3_forbidden")
        return False
    try:
        payload = _selected_config(runtime, decision)
        products = expected_products(payload)
        config_path = Path(runtime.MAA_CONFIG) / "gui.new.json"
        cfg = runtime._read_json_file(str(config_path), {}) or {}
        infrast = next(
            item for item in runtime._task_queue(cfg)
            if item.get("TaskType") == "Infrast"
        )
        backup_dir = Path(runtime.OUTPUT_DIR) / "maa_config_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / (
            "gui.new.before_base333_single_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
        runtime._atomic_write_json(str(backup_path), cfg)
        infrast.update(
            {
                "Mode": "Custom",
                "UsesOfDrones": "SyntheticJade" if plan_index else "Money",
                "OriginiumShardAutoReplenishment": True,
                "CustomFileType": "user_defined",
                "Filename": str(ACTIVE_CONFIG.resolve()),
                "PlanSelect": 0,
            }
        )
        runtime._atomic_write_json(str(config_path), cfg)
        readback = runtime._read_json_file(str(config_path), {}) or {}
        selected = next(
            item for item in runtime._task_queue(readback)
            if item.get("TaskType") == "Infrast"
        )
        required = {
            "Mode": "Custom",
            "Filename": str(ACTIVE_CONFIG.resolve()),
            "PlanSelect": 0,
        }
        if any(selected.get(key) != value for key, value in required.items()):
            raise RuntimeError("MAA Infrast config readback mismatch")
    except Exception as exc:
        summary.update(status="failed", reason=f"single_plan_config_failed: {exc}")
        runtime.log(f"❌ 动态333单方案落盘失败: {exc}", "ERROR")
        return False

    summary.update(
        {
            "status": "configured_verified",
            "layout": "333",
            "decision": deepcopy(decision),
            "source_plan_index": plan_index,
            "maa_plan_index": 0,
            "config": str(ACTIVE_CONFIG.resolve()),
            "config_sha256": hashlib.sha256(ACTIVE_CONFIG.read_bytes()).hexdigest().upper(),
            "expected_products": {
                f"{facility}:{index}": product
                for (facility, index), product in products.items()
            },
            "config_readback": True,
            "backup": str(backup_path),
        }
    )
    runtime.log(
        f"✅ 动态333库存方案{plan_index}已固化为MAA单方案；"
        "产品决策与干员轮班已分离"
    )
    return True


def _callbacks(log_text, what):
    marker = "Assistant::append_callback | SubTaskExtraInfo "
    found = []
    for match in re.finditer(re.escape(marker) + r"(\{.*\})", log_text or ""):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if payload.get("what") == what:
            found.append((match.start(), payload))
    return found


def _last_infrast_window(log_text):
    starts = [m.start() for m in re.finditer(r"append_task Infrast \{", log_text or "")]
    if not starts:
        return ""
    start = starts[-1]
    completed = (log_text or "").find(
        'TaskChainCompleted {"taskchain":"Infrast"', start
    )
    if completed < 0:
        return (log_text or "")[start:]
    return (log_text or "")[start:completed + 256]


def verify_infrast_execution(log_text, expected, active_config=ACTIVE_CONFIG):
    """Return a direct-evidence receipt for products and operator rotation."""

    window = _last_infrast_window(log_text)
    receipt = {
        "status": "execution_unverified",
        "config_loaded": False,
        "products_verified": False,
        "operator_rotation_verified": False,
        "product_receipts": {},
        "rotation_confirmations": [],
        "reason": "infrast_window_missing",
    }
    if not window:
        return receipt
    append = re.search(r"append_task Infrast (\{.*\})", window)
    if not append:
        receipt["reason"] = "infrast_append_missing"
        return receipt
    try:
        task = json.loads(append.group(1))
    except json.JSONDecodeError:
        receipt["reason"] = "infrast_append_invalid"
        return receipt
    receipt["config_loaded"] = bool(
        os.path.normcase(task.get("filename", ""))
        == os.path.normcase(str(Path(active_config).resolve()))
        and task.get("plan_index") == 0
    )

    product_events = _callbacks(window, "ProductOfFacility")
    positions = [position for position, _ in product_events] + [len(window)]
    for number, (position, payload) in enumerate(product_events):
        details = payload.get("details") or {}
        key = (details.get("facility"), details.get("index"))
        if key not in expected:
            continue
        desired = expected[key]
        observed = details.get("product")
        segment = window[position:positions[number + 1]]
        if observed == PRODUCT_ALIASES[desired]:
            ok = True
            proof = "already_correct"
        else:
            required = CHANGE_PROOFS[desired]
            ok = all(token in segment for token in required)
            proof = "changed_and_confirmed" if ok else "change_not_proven"
        receipt["product_receipts"][f"{key[0]}:{key[1]}"] = {
            "expected": desired,
            "observed_before": observed,
            "ok": ok,
            "proof": proof,
        }

    receipt["products_verified"] = bool(
        len(receipt["product_receipts"]) == len(expected)
        and all(item["ok"] for item in receipt["product_receipts"].values())
    )
    confirmations = set()
    for _, payload in _callbacks(window, "InfrastConfirmButton"):
        details = payload.get("details") or {}
        confirmations.add((details.get("facility"), details.get("index")))
    required_rotation = {
        ("Mfg", 0), ("Mfg", 1), ("Mfg", 2),
        ("Trade", 0), ("Trade", 1), ("Trade", 2),
        ("Control", 0),
        ("Power", 0), ("Power", 1), ("Power", 2),
        ("Reception", 0), ("Office", 0),
        ("Dorm", 0), ("Dorm", 1), ("Dorm", 2), ("Dorm", 3),
    }
    receipt["rotation_confirmations"] = [
        f"{facility}:{index}" for facility, index in sorted(confirmations)
    ]
    receipt["operator_rotation_verified"] = required_rotation.issubset(confirmations)
    receipt["task_chain_completed"] = (
        'TaskChainCompleted {"taskchain":"Infrast"' in window
    )
    if all(
        (
            receipt["config_loaded"],
            receipt["products_verified"],
            receipt["operator_rotation_verified"],
            receipt["task_chain_completed"],
        )
    ):
        receipt["status"] = "applied_verified"
        receipt["reason"] = "config_products_rotation_and_completion_verified"
    else:
        failed = [
            name
            for name in (
                "config_loaded", "products_verified",
                "operator_rotation_verified", "task_chain_completed",
            )
            if not receipt.get(name)
        ]
        receipt["reason"] = "missing:" + ",".join(failed)
    return receipt


def install(runtime):
    if getattr(runtime, "_daily_base_333_verified_execution_v1_installed", False):
        return runtime

    runtime._apply_dynamic_333_infrast_config = (
        lambda decision: apply_single_plan_config(runtime, decision)
    )
    original_run = runtime.run_maa_daily_tasks
    original_wait = runtime.wait_maa_complete

    def run_with_scope(*args, **kwargs):
        enabled = kwargs.get("enabled_tasks")
        runtime._base333_active_maa_scope = set(enabled or [])
        return original_run(*args, **kwargs)

    def wait_with_base_receipt(*args, **kwargs):
        result = original_wait(*args, **kwargs)
        scope = set(getattr(runtime, "_base333_active_maa_scope", set()) or set())
        if result is not True or "Infrast" not in scope:
            return result
        summary = runtime._RUN_SUMMARY.setdefault("base_333", {})
        products = {
            tuple(key.split(":", 1)): value
            for key, value in (summary.get("expected_products") or {}).items()
        }
        products = {(facility, int(index)): value for (facility, index), value in products.items()}
        receipt = verify_infrast_execution(
            runtime._get_current_maa_run_log(), products, summary.get("config") or ACTIVE_CONFIG
        )
        summary["execution_receipt"] = receipt
        summary["status"] = receipt["status"]
        if receipt["status"] != "applied_verified":
            runtime.log(
                "⛔ 基建队列结束但333产品/轮班未形成直接证据：" + receipt["reason"],
                "ERROR",
            )
            return "base333_execution_unverified"
        # A single-plan file forces MAA's automatic next-plan save to wrap to 0.
        cfg = runtime._read_json_file(str(Path(runtime.MAA_CONFIG) / "gui.new.json"), {}) or {}
        infrast = next(
            (item for item in runtime._task_queue(cfg) if item.get("TaskType") == "Infrast"),
            {},
        )
        summary["post_run_plan_select"] = infrast.get("PlanSelect")
        summary["post_run_config_stable"] = bool(
            infrast.get("PlanSelect") == 0
            and os.path.normcase(infrast.get("Filename", ""))
            == os.path.normcase(str(ACTIVE_CONFIG.resolve()))
        )
        if not summary["post_run_config_stable"]:
            summary["status"] = "execution_unverified"
            return "base333_post_run_config_drift"
        runtime.log("✅ 基建333产品、全设施轮班及任务后方案稳定性均已直接核验")
        return result

    run_with_scope._daily_base_333_verified_execution_v1 = True
    wait_with_base_receipt._daily_base_333_verified_execution_v1 = True
    runtime.run_maa_daily_tasks = run_with_scope
    runtime.wait_maa_complete = wait_with_base_receipt
    runtime._daily_base_333_verified_execution_v1_installed = True
    runtime.log("  [V54] 333单方案、产品回执与全设施轮班验收已启用")
    return runtime

