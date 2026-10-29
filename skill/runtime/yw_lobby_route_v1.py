"""Recognise the inspected YW lobby and keep farming on its direct route."""
import re
import subprocess


def is_lobby(items):
    text = "".join(str(t) for t, _, _ in items)
    return all(k in text for k in ("劳工配给所", "打捞方案", "雷亚-伊比利亚", "作战结束时间"))


def click_navigation(app, pos, reason):
    try:
        result = subprocess.run([app.ADB,"-s",app.DEVICE,"shell","input","tap",str(pos[0]),str(pos[1])],
                                timeout=15,capture_output=True,text=True)
        if result.returncode or "SecurityException" in (result.stderr or ""):
            app.log(f"[YW导航] {reason}输入被拒绝", "ERROR")
            return False
    except subprocess.TimeoutExpired:
        # Sending another tap here would be an unverified replay. The caller
        # verifies the destination first; its outcome, not transport, decides.
        app.log(f"[YW导航] {reason}指令超时，先核对落点页面", "WARN")
    app.wait(4)
    return True


def prepare(app, event, display_name):
    path=app.shot("yw_direct_farm_detail_probe")
    items=app.ocr(path)
    text=" ".join(str(t) for t,_,_ in items)
    if not app._event_stage_detail_confirmed(text,display_name,items):
        # A wrong open detail must be closed before scanning the map behind it.
        from daily_fast_proxy_yw_v1 import page_kind
        if page_kind(items)[0] == "yw_detail":
            app.back()
            app.wait(3)
        opened=app._open_event_stage_detail(event,display_name,tag="yw_direct_farm",ensure_map=True)
        if not opened:
            return False
        path,items,text=opened
    if (any(k not in text for k in (display_name,"代理指挥","开始行动"))
            or "开始突袭" in text or "附加条件" in text
            or app._event_normal_badges_ratio(path)<.08):
        return False
    if not app._event_proxy_command_selected(path):
        pos=app.find_text(items,"代理指挥",exact=False)
        if not pos or not click_navigation(app,pos,"勾选普通代理"):
            return False
        selected=app.shot("yw_direct_proxy_selected")
        if not app._event_proxy_command_selected(selected):
            return False
    app.log(f"[YW直接交接] {display_name}同关详情/普通三星/代理已确认，不退出地图绕回主页")
    return True


def install(app):
    original_map=app.goto_event_map
    original_home=app.goto_main_menu

    def goto_event_map(event=None):
        event=event or app.get_active_event()
        if (event or {}).get("stage_prefix")!="YW":
            return original_map(event)
        path=app.shot("yw_lobby_map_route")
        items=app.ocr(path)
        if not is_lobby(items):
            return original_map(event)
        if app._maa_task_queue_running():
            return False
        targets=[(x,y) for t,x,y in items if "雷亚-伊比利亚" in str(t)
                 and 1200<=x<=1900 and 700<=y<=1000]
        if len(targets)!=1 or not click_navigation(app,targets[0],"大厅进入雷亚-伊比利亚"):
            return False
        after=app.shot("yw_lobby_map_verified")
        rows=app.ocr(after)
        visible=app._visible_event_stages(rows,event)
        app._RUN_SUMMARY.setdefault("event",{})["lobby_direct_route"]=dict(
            before=path,after=after,visible=visible,verified=bool(visible))
        return bool(visible)

    def goto_main_menu(*args,**kwargs):
        path=app.shot("yw_lobby_home_route")
        if is_lobby(app.ocr(path)):
            if app._maa_task_queue_running() or not click_navigation(app,app.POS_TOP_HOME,"大厅返回首页导航"):
                return False
        return original_home(*args,**kwargs)

    app.goto_event_map=goto_event_map
    app.goto_main_menu=goto_main_menu
    return app
