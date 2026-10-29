"""Close the process-alive-but-still-at-START gap without blind game taps."""

from __future__ import annotations


def install(runtime):
    if getattr(runtime, "_daily_login_recovery_v1_installed", False):
        return runtime
    original = runtime.ensure_env

    def ensure_env():
        if original() is not True:
            return False
        state = runtime.get_state()
        if state != "login":
            return True
        runtime.log("→ 已运行游戏仍停在图形识别的START页，点击START后复核")
        runtime.tap(961, 1028)
        for _ in range(5):
            runtime.wait(5)
            state = runtime.get_state()
            if state == "main_menu":
                return True
            if state in ("announcement", "event_signin", "monthly_sign_in"):
                if not runtime.handle_popups():
                    break
        runtime.log(f"❌ START后未到主页，最后页面={state}；停止后续业务", "ERROR")
        return False

    runtime.ensure_env = ensure_env
    runtime._daily_login_recovery_v1_installed = True
    return runtime
