"""V34: recover the real DP-TR-1 clear and classify its custom result page."""
from __future__ import annotations
import dp_tutorial_v29 as v29
import dp_tutorial_v33 as v33


def install(runtime):
    if getattr(runtime,"_dp_tutorial_v34_installed",False): return runtime
    v33.install(runtime)
    original_state=runtime.get_state
    original_clear=runtime.clear_event_stage

    def get_state():
        state=original_state()
        if state!="unknown": return state
        page=runtime.shot("dp_tr1_v34_result_probe")
        text=v29._compact_text(runtime.ocr(page))
        if "挑战成功" in text and "DP-TR-1" in text.upper():
            runtime.log("  [V34教程] 识别逐影集趣专用DP-TR-1挑战成功页")
            return "victory"
        return state

    def clear_event_stage(event,stage,mode="normal",max_attempts=None,force_replay=False):
        if v29._is_target(event,stage,mode) and not runtime._event_mode_has_trusted_clear_evidence(v29.EVENT_NAME,v29.TUTORIAL,"normal"):
            if v29._confirm_dp1_unlocked(runtime,event):
                runtime._update_event_progress(v29.EVENT_NAME,v29.TUTORIAL,"cleared","V34真实地图已显示DP-1，回收上一轮DP-TR-1挑战成功",mode="normal")
                runtime.log("✅ [V34教程] DP-1已真实解锁，补记DP-TR-1完成且不重打")
                return True
        return original_clear(event,stage,mode=mode,max_attempts=max_attempts,force_replay=force_replay)

    runtime.get_state=get_state
    runtime.clear_event_stage=clear_event_stage
    runtime._dp_tutorial_v34_installed=True
    runtime.log("  [V34] DP-TR-1专用挑战成功页识别+DP-1地图恢复已安装")
    return runtime
