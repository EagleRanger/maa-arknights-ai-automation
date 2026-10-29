"""V42: keep verified DP checkpoints durable and block accidental replays."""
from __future__ import annotations

import dp_progress_evidence_v38 as v38


FROZEN_NUMERIC_STAGES = {"DP-1", "DP-2", "DP-3", "DP-4"}


def _descendant_reverifies_prerequisite(runtime, event_name, stage_name, mode):
    if event_name != v38.EVENT_NAME or stage_name != "DP-1" or mode != "normal":
        return False
    state = v38._load_mode_state(runtime, event_name, stage_name, mode)
    evidence = state.get("evidence") or {}
    if state.get("status") != "cleared":
        return False
    if evidence.get("schema") != "dp_prerequisite_descendant_v1":
        return False
    descendant = str(evidence.get("descendant_stage") or "")
    if descendant != "DP-2":
        return False
    # DP-2 cannot be entered or cleared before DP-1.  Re-verify DP-2's own
    # immutable result+map pair instead of trusting a prose checkpoint.
    return v38._images_reverify_dp_clear(
        runtime, event_name, descendant, "normal"
    )


def install(runtime):
    if getattr(runtime, "_dp_checkpoint_guard_v42_installed", False):
        return runtime
    original_trusted = runtime._event_mode_has_trusted_clear_evidence
    original_clear = runtime.clear_event_stage

    def trusted_clear(event_name, stage_name, mode):
        if original_trusted(event_name, stage_name, mode):
            return True
        cache_key = (event_name, stage_name, mode)
        cache = getattr(runtime, "_dp_v42_descendant_cache", {})
        if cache_key not in cache:
            cache[cache_key] = _descendant_reverifies_prerequisite(
                runtime, event_name, stage_name, mode
            )
            runtime._dp_v42_descendant_cache = cache
        if cache[cache_key]:
            runtime.log(
                "  [V42断点] DP-2持久双截图重新核验通过，线性前置证明DP-1已完成"
            )
            return True
        return False

    def clear_event_stage(event, stage, mode="normal", *args, **kwargs):
        event_name = str((event or {}).get("name") or "")
        stage_name = str((stage or {}).get("display") or "")
        if (
            event_name == v38.EVENT_NAME
            and stage_name in FROZEN_NUMERIC_STAGES
            and trusted_clear(event_name, stage_name, mode)
        ):
            runtime.log(
                f"  [V42硬门] {stage_name}已有持久可复核完成证据，禁止进入编队或重新战斗"
            )
            return True
        return original_clear(event, stage, mode=mode, *args, **kwargs)

    runtime._event_mode_has_trusted_clear_evidence = trusted_clear
    runtime.clear_event_stage = clear_event_stage
    runtime._dp_checkpoint_guard_v42_installed = True
    runtime.log("  [V42] DP持久证据与已完成关卡重打硬门已安装")
    return runtime
