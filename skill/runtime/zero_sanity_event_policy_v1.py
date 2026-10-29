"""Keep verified zero-sanity events separate from the stamina router.

The terminal uses the same limited-event card for ordinary stamina events and
special modes.  Treating every card as a SideStory made an unsupported special
mode freeze all stamina.  This overlay admits only exact, reviewed aliases and
keeps the special-mode progress pending while restoring the existing no-event
stamina policy.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re


ZERO_SANITY_EVENTS = (
    {
        "id": "vector-breakthrough-03-2026",
        "name": "矢量突破#3 拟生态",
        "aliases": (
            "矢量突破#3拟生态",
            "矢量突破 #3 拟生态",
            "矢量突破3拟生态",
            "矢量突破拟生态",
        ),
        "starts_at": "2026-09-29T16:00:00+08:00",
        "expires_at": "2026-10-20T03:59:00+08:00",
        "consumes_sanity": False,
        "progression": "separate_non_stamina_pending",
        "maa_route": "no_current_unique_full_event_route",
        "evidence": (
            "https://ak.hypergryph.com/news/1455",
            "https://arknights.wiki.gg/wiki/Vector_Breakthrough",
        ),
    },
)


def _normalize(value):
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(value or "")).lower()


def _active(record, at=None):
    at = at or datetime.now().astimezone()
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    start = datetime.fromisoformat(record["starts_at"])
    end = datetime.fromisoformat(record["expires_at"])
    return start <= at.astimezone(start.tzinfo) < end


def classify_zero_sanity_event(name, *, at=None):
    """Return an exact reviewed special-event record, never a fuzzy guess."""

    normalized = _normalize(name)
    if not normalized:
        return None
    for record in ZERO_SANITY_EVENTS:
        if not _active(record, at=at):
            continue
        for alias in record["aliases"]:
            token = _normalize(alias)
            if token and token == normalized:
                return deepcopy(record)
    return None


def install(runtime):
    """Install the classification ahead of generic event discovery."""

    if getattr(runtime, "_zero_sanity_event_policy_v1_installed", False):
        return runtime

    original_classifier = runtime._non_stamina_activity_from_name
    original_detect = runtime.detect_terminal_limited_event

    def classify(name):
        special = classify_zero_sanity_event(name)
        if special:
            return special
        return original_classifier(name)

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
            })
            runtime._RUN_SUMMARY["zero_sanity_event"] = {
                "status": "recognized_nonblocking",
                "name": special["name"],
                "policy_id": special["id"],
                "progression": special["progression"],
                "maa_route": special["maa_route"],
                "stamina_routing": "continue_existing_no_stamina_event_policy",
                "evidence": list(special["evidence"]),
            }
        return result

    classify._zero_sanity_event_policy_v1 = True
    detect._zero_sanity_event_policy_v1 = True
    runtime._non_stamina_activity_from_name = classify
    runtime.detect_terminal_limited_event = detect
    runtime._zero_sanity_event_policy_v1_installed = True
    runtime.log(
        "  [V70] 零理智特殊活动与理智路线已分账；仅精确白名单可放行库存路由"
    )
    return runtime

