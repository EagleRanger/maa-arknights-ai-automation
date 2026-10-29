"""V2 zero-sanity classifier with live OCR prefix-loss recovery."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import zero_sanity_event_policy_v1 as v1


LIVE_OCR_ALIASES = (
    "量突破#3拟生态",
    "量突破3拟生态",
)


def classify_zero_sanity_event(name, *, at=None):
    direct = v1.classify_zero_sanity_event(name, at=at)
    if direct:
        direct["classifier_version"] = "v2"
        return direct
    normalized = v1._normalize(name)
    if normalized not in {v1._normalize(alias) for alias in LIVE_OCR_ALIASES}:
        return None
    record = deepcopy(v1.ZERO_SANITY_EVENTS[0])
    if not v1._active(record, at=at):
        return None
    record.update({
        "classifier_version": "v2",
        "match_kind": "live_verified_prefix_loss_alias",
        "matched_ocr": str(name or ""),
    })
    return record


def install(runtime):
    if getattr(runtime, "_zero_sanity_event_policy_v2_installed", False):
        return runtime

    original_classifier = runtime._non_stamina_activity_from_name
    original_detect = runtime.detect_terminal_limited_event

    def classify(name):
        special = classify_zero_sanity_event(name)
        return special if special else original_classifier(name)

    def detect():
        result = original_detect()
        special = None
        if isinstance(result, dict) and result.get("status") == "open":
            special = classify_zero_sanity_event(result.get("name"))
        if special:
            result.update({
                "classification": "zero_sanity_special_event",
                "canonical_name": special["name"],
                "ignored_for_stamina_routing": True,
                "progression_status": special["progression"],
                "consumes_sanity": False,
                "policy_id": special["id"],
                "classifier_version": "v2",
                "match_kind": special.get("match_kind", "exact_alias"),
            })
            runtime._RUN_SUMMARY["zero_sanity_event"] = {
                "status": "recognized_nonblocking",
                "name": special["name"],
                "observed_name": result.get("name"),
                "policy_id": special["id"],
                "classifier_version": "v2",
                "match_kind": special.get("match_kind", "exact_alias"),
                "progression": special["progression"],
                "maa_route": special["maa_route"],
                "stamina_routing": "continue_existing_no_stamina_event_policy",
                "evidence": list(special["evidence"]),
                "classified_at": datetime.now().astimezone().isoformat(),
            }
        return result

    classify._zero_sanity_event_policy_v2 = True
    detect._zero_sanity_event_policy_v2 = True
    runtime._non_stamina_activity_from_name = classify
    runtime.detect_terminal_limited_event = detect
    runtime._zero_sanity_event_policy_v2_installed = True
    runtime.log("  [V71] 零理智活动V2已前置：支持实机OCR首字漏识别，未知活动仍冻结")
    return runtime

