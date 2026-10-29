"""Tighten V54 base receipts so an empty product expectation cannot pass.

V1 correctly verifies operator rotation, but an inventory-refresh failure can
leave ``expected_products`` empty.  The empty set then vacuously satisfies the
old product predicate.  V2 keeps the proven V1 executor and adds a complete
six-room expectation gate before accepting any product receipt.
"""

from __future__ import annotations

from pathlib import Path

import daily_base_333_verified_execution_v1 as legacy


_LEGACY_VERIFY = legacy.verify_infrast_execution
REQUIRED_PRODUCT_ROOMS = {
    ("Mfg", 0), ("Mfg", 1), ("Mfg", 2),
    ("Trade", 0), ("Trade", 1), ("Trade", 2),
}


def _unverified(reason, expected):
    return {
        "status": "execution_unverified",
        "config_loaded": False,
        "products_verified": False,
        "operator_rotation_verified": False,
        "task_chain_completed": False,
        "product_receipts": {},
        "rotation_confirmations": [],
        "expected_product_rooms": [
            f"{facility}:{index}" for facility, index in sorted(expected)
        ],
        "reason": reason,
    }


def verify_infrast_execution(log_text, expected, active_config=legacy.ACTIVE_CONFIG):
    expected = dict(expected or {})
    if set(expected) != REQUIRED_PRODUCT_ROOMS:
        missing = REQUIRED_PRODUCT_ROOMS - set(expected)
        extra = set(expected) - REQUIRED_PRODUCT_ROOMS
        return _unverified(
            "expected_products_incomplete:missing="
            + ",".join(f"{facility}:{index}" for facility, index in sorted(missing))
            + ";extra="
            + ",".join(f"{facility}:{index}" for facility, index in sorted(extra)),
            expected,
        )
    receipt = _LEGACY_VERIFY(log_text, expected, active_config)
    # MaaCore reports an already-correct LMD trading post as ``Money`` while
    # older fixtures and some callback versions use ``LMD``.  Preserve the V1
    # result when it passes; otherwise retry only the parser with MaaCore's
    # runtime alias.  The global alias is restored immediately so frozen V1
    # callers remain compatible with both historical and current logs.
    if receipt.get("products_verified") is not True:
        previous_lmd_alias = legacy.PRODUCT_ALIASES.get("LMD")
        legacy.PRODUCT_ALIASES["LMD"] = "Money"
        try:
            money_receipt = _LEGACY_VERIFY(log_text, expected, active_config)
        finally:
            legacy.PRODUCT_ALIASES["LMD"] = previous_lmd_alias
        if money_receipt.get("products_verified") is True:
            receipt = money_receipt
    product_receipts = receipt.get("product_receipts") or {}
    if set(product_receipts) != {
        f"{facility}:{index}" for facility, index in REQUIRED_PRODUCT_ROOMS
    }:
        receipt["status"] = "execution_unverified"
        receipt["products_verified"] = False
        receipt["reason"] = "product_receipts_incomplete"
    receipt["expected_product_rooms"] = [
        f"{facility}:{index}" for facility, index in sorted(REQUIRED_PRODUCT_ROOMS)
    ]
    return receipt


def install(runtime):
    legacy.install(runtime)
    legacy.verify_infrast_execution = verify_infrast_execution
    runtime._daily_base_333_verified_execution_v2_installed = True
    runtime._RUN_SUMMARY.setdefault("base_333_policy", {}).update(
        {
            "receipt_version": "v2",
            "empty_expected_products_forbidden": True,
            "required_product_rooms": 6,
        }
    )
    runtime.log("  [V57] 基建产品验收改为6房间完整回执；空预期禁止通过")
    return runtime
