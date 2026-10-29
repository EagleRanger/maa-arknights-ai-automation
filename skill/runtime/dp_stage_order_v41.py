"""V41: correct the live-confirmed DP-5 -> DS-1 prerequisite order."""
from __future__ import annotations

from copy import deepcopy

import dp_event_route_v26 as route


ORDER = (
    "DP-1", "DP-2", "DP-3", "DP-4", "DP-5", "DS-1", "DP-6",
    "DP-EX-1", "DP-EX-2", "DP-EX-3", "DP-EX-4", "DS-2",
    "DP-EX-5", "DP-EX-6",
)


def reorder_event(event):
    result = deepcopy(event)
    stages = list(result.get("stages") or [])
    by_name = {str(item.get("display") or ""): item for item in stages}
    if set(by_name) != set(ORDER) or len(stages) != len(ORDER):
        raise ValueError("DP stage graph changed; V41 refuses to guess a new order")
    result["stages"] = [by_name[name] for name in ORDER]
    result["live_prerequisite_evidence"] = {
        "DS-1": "通关DP-5解锁",
        "source": "runtime_screenshots/event_stage_DS-1_0_20_1790041964792312700.png",
    }
    return result


def install_before_runtime():
    current = route.build_dp_event
    if getattr(current, "_dp_stage_order_v41", False):
        return

    def build_dp_event():
        return reorder_event(current())

    build_dp_event._dp_stage_order_v41 = True
    route.build_dp_event = build_dp_event
