"""Recover the verified Moon-on-Water event lobby before daily startup."""

from __future__ import annotations


def is_sr_event_lobby(text):
    compact = "".join(str(text or "").split())
    stable = all(marker in compact for marker in ("旅行计划", "校园商店", "通学路"))
    identity = "月行水上" in compact or "SURLUN" in compact.upper()
    return stable and identity


def sr_special_route_locked(text):
    compact = "".join(str(text or "").split())
    return is_sr_event_lobby(text) and "9月11日16:00:00后开启" in compact


def install_event_lobby_recovery(app):
    original = app.goto_main_menu
    if getattr(original, "_event_lobby_recovery_v1", False):
        return original

    def goto_main_menu():
        path = app.shot("event_lobby_startup_probe")
        text = app.ocr_text(path)
        if is_sr_event_lobby(text):
            if app._maa_task_queue_running():
                app.log("  [回主界面] 月行水上大厅已确认，但MAA仍运行，不干预游戏", "WARN")
                return False
            locked = sr_special_route_locked(text)
            app.tap(*app.POS_TOP_HOME)
            app.log(
                "  [回主界面] 已识别月行水上活动大厅并点击顶部主页；"
                + ("特殊路线当前仍锁定" if locked else "特殊路线未显示锁定")
            )
            app.wait(4)
        return original()

    goto_main_menu._event_lobby_recovery_v1 = True
    goto_main_menu._event_lobby_recovery_original = original
    app.goto_main_menu = goto_main_menu
    return goto_main_menu
