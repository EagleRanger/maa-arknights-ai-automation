"""Verify each 333 production room from current MaaCore callbacks.

V2 retried the LMD/Money alias only when the entire six-room receipt could
pass.  That coupled unrelated rooms: one genuine manufacturing parser miss
kept already-correct Money trading posts marked as failures.  V3 evaluates
each room independently and treats a matching ``ProductChanged`` callback as
the strongest proof of a successful product switch.
"""

from __future__ import annotations

import daily_base_333_verified_execution_v1 as legacy
import daily_base_333_verified_execution_v2 as previous


REQUIRED_PRODUCT_ROOMS = previous.REQUIRED_PRODUCT_ROOMS
PRODUCT_CALLBACK_ALIASES = {
    "Pure Gold": {"PureGold"},
    "Battle Record": {"CombatRecord"},
    "Originium Shard": {"OriginStone", "OriginiumShard"},
    "LMD": {"LMD", "Money"},
    "Orundum": {"SyntheticJade"},
}


def _room_key(details):
    return details.get("facility"), details.get("index")


def verify_infrast_execution(log_text, expected, active_config=legacy.ACTIVE_CONFIG):
    expected = dict(expected or {})
    receipt = previous.verify_infrast_execution(log_text, expected, active_config)
    if set(expected) != REQUIRED_PRODUCT_ROOMS:
        return receipt

    window = legacy._last_infrast_window(log_text)
    if not window:
        return receipt

    product_events = legacy._callbacks(window, "ProductOfFacility")
    positions = [position for position, _ in product_events] + [len(window)]
    direct_receipts = dict(receipt.get("product_receipts") or {})

    for number, (position, payload) in enumerate(product_events):
        details = payload.get("details") or {}
        key = _room_key(details)
        if key not in expected:
            continue
        desired = expected[key]
        accepted = PRODUCT_CALLBACK_ALIASES[desired]
        observed_before = details.get("product")
        item = dict(direct_receipts.get(f"{key[0]}:{key[1]}") or {})
        item.update(expected=desired, observed_before=observed_before)

        if observed_before in accepted:
            item.update(ok=True, proof="already_correct_callback")
        else:
            segment = window[position:positions[number + 1]]
            changed = [
                changed_payload
                for _, changed_payload in legacy._callbacks(segment, "ProductChanged")
                if _room_key(changed_payload.get("details") or {}) == key
                and (changed_payload.get("details") or {}).get("product") in accepted
            ]
            if changed:
                observed_after = (changed[-1].get("details") or {}).get("product")
                item.update(
                    ok=True,
                    proof="changed_and_callback_verified",
                    observed_after=observed_after,
                )
        direct_receipts[f"{key[0]}:{key[1]}"] = item

    receipt["product_receipts"] = direct_receipts
    receipt["products_verified"] = bool(
        set(direct_receipts)
        == {f"{facility}:{index}" for facility, index in REQUIRED_PRODUCT_ROOMS}
        and all(item.get("ok") is True for item in direct_receipts.values())
    )
    required = (
        "config_loaded",
        "products_verified",
        "operator_rotation_verified",
        "task_chain_completed",
    )
    if all(receipt.get(name) is True for name in required):
        receipt["status"] = "applied_verified"
        receipt["reason"] = "config_products_rotation_and_completion_verified_v3"
    else:
        failed = [name for name in required if receipt.get(name) is not True]
        receipt["status"] = "execution_unverified"
        receipt["reason"] = "missing:" + ",".join(failed)
    receipt["receipt_version"] = "v3"
    return receipt


def install(runtime):
    previous.install(runtime)
    legacy.verify_infrast_execution = verify_infrast_execution
    runtime._daily_base_333_verified_execution_v3_installed = True
    runtime._RUN_SUMMARY.setdefault("base_333_policy", {}).update(
        {
            "receipt_version": "v3",
            "room_local_aliases": True,
            "product_changed_callback_required_for_switch": True,
            "required_product_rooms": 6,
        }
    )
    runtime.log("  [V62] 基建产品验收改为逐房间别名与ProductChanged直接回执")
    return runtime
