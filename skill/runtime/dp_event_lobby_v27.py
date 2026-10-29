"""V27 live fix for the ``逐影集趣`` lobby entrance.

The lobby contains two OCR matches for ``轻游``: the real bottom-right
``轻游 AMUSEMENT`` button and the locked EX hint ``完成『轻游』后解锁``.
The generic navigator takes the first match, so prefer the unique Latin anchor
on the real button before falling back to the Chinese label.
"""

from __future__ import annotations

from copy import deepcopy


def install_builder_patch():
    import dp_event_route_v26 as v26

    current = v26.build_dp_event
    if getattr(current, "_dp_event_lobby_v27", False):
        return

    def build_dp_event():
        event = deepcopy(current())
        event["combat_keywords"] = ["AMUSE", "轻游", "活动关卡"]
        event["lobby_entry_identity"] = {
            "required_any": ["DOLLY", "逐影集趣"],
            "preferred_anchor": "AMUSE",
            "rejected_context": "完成『轻游』后解锁",
        }
        return event

    build_dp_event._dp_event_lobby_v27 = True
    v26.build_dp_event = build_dp_event


def install(runtime):
    install_builder_patch()
    runtime.log("  [V27] 逐影集趣大厅优先点击AMUSE入口，避开上方EX解锁提示")
    runtime._dp_event_lobby_v27_installed = True
    return runtime
