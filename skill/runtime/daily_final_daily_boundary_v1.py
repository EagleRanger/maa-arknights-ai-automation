"""Reload MAA after an exact-single stamina drain before final daily chains.

The temporary config context restores ``gui.new.json`` on disk, but the idle
MAA process that executed the last single Fight still keeps the Fight-only
queue in memory.  The next final-daily call can therefore see an unchanged
five-chain file and skip the reload, while the GUI starts the stale Fight
queue.  Close only the now-idle MAA process after a *successful* drain so the
next queue loads the restored five-chain configuration from disk.
"""

from __future__ import annotations


def install(runtime):
    if getattr(runtime, "_daily_final_daily_boundary_v1_installed", False):
        return runtime

    import daily_stamina_exhaustion_v4 as exhaustion

    current = exhaustion.drain_exact_single_battles
    if getattr(current, "_daily_final_daily_boundary_v1", False):
        runtime._daily_final_daily_boundary_v1_installed = True
        return runtime

    def drain_then_reload(*args, **kwargs):
        result = current(*args, **kwargs)
        if result is True:
            runtime.reload_maa_after_config_switch(
                "逐次单场理智闭环完成；最终五链必须重载已恢复的TaskQueue"
            )
            runtime.log("✅ 最终五链边界：已关闭单场Fight的空闲MAA并强制重载配置")
        return result

    drain_then_reload._daily_final_daily_boundary_v1 = True
    drain_then_reload._wrapped = current
    exhaustion.drain_exact_single_battles = drain_then_reload
    runtime._daily_final_daily_boundary_v1_installed = True
    return runtime

