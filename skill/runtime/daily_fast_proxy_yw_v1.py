"""Candidate: fresh YW navigation and native, affordable multi-proxy evidence.

MaaCore's accepted visible-list selector owns clicking the multiplier. This
adapter retains AUTO (not ten forced battles), inspects the detail cost and
current sanity, and reports actual batches rather than configuration values.
"""
from contextlib import contextmanager
from functools import wraps
import re
from unittest.mock import patch


def page_kind(items):
    text = " ".join(str(t) for t, _, _ in items)
    home = [(x, y) for t, x, y in items if str(t).strip() == "首页"
            and 40 <= x <= 280 and 250 <= y <= 500]
    nav = sum(k in text for k in ("终端", "基建", "公开招募", "采购中心", "档案"))
    if len(home) == 1 and nav >= 4:
        return "quick_nav", home[0]
    codes = {str(t).strip().upper() for t, _, _ in items
             if re.fullmatch(r"YW-(?:[1-8]|ST-\d+|TR-\d+)", str(t).strip().upper())}
    if codes and "开始行动" in text and "代理指挥" in text:
        return "yw_detail", None
    if len(codes) >= 2 and ("未来瞻望镜" in text or "FUTURISCOPE" in text.upper()):
        return "yw_map", None
    return "unknown", None


def capacity(sanity, unit_cost, visible_max=10):
    if type(sanity) is not int or sanity < 0 or type(unit_cost) is not int or unit_cost <= 0:
        return None
    if type(visible_max) is not int or not 1 <= visible_max <= 10:
        return None
    return min(visible_max, sanity // unit_cost)


def batch_receipt(farm, before=None):
    batches = farm.get("series_batches") or []
    runs = farm.get("actual_runs")
    verified = (bool(batches) and type(runs) is int and runs > 0
                and all(type(n) is int and 1 <= n <= 10 for n in batches)
                and sum(batches) == runs)
    result = dict(verified=verified, actual_batches=list(batches),
                  actual_runs=runs, basis="current_run_completed_FightTimes_not_AUTO_config")
    if verified and before is not None:
        result.update(first_batch=batches[0], affordable_before=before,
                      first_batch_used_available_capacity=batches[0] == before)
    return result


def install(app):
    original_home = app.goto_main_menu
    original_prepare = app._prepare_event_farm_stage
    original_configure = app._configure_fight
    original_event = app.mode_event

    @wraps(original_home)
    def home(*args, **kwargs):
        if original_home(*args, **kwargs):
            return True
        # One bounded recovery only after the old navigation has failed. Never
        # reuse the preceding state label or act while MaaCore owns the queue.
        if app._maa_task_queue_running():
            return False
        evidence = app._RUN_SUMMARY.setdefault("yw_home_recovery", [])
        for _ in range(3):
            path = app.shot("yw_home_fresh_recovery")
            kind, pos = page_kind(app.ocr(path))
            evidence.append(dict(evidence=path, page=kind))
            if kind == "quick_nav":
                app.tap(*pos)
                app.wait(4)
                # Original chain re-verifies the actual home/terminal, not the
                # fact that a click was sent.
                return original_home(*args, **kwargs)
            if kind in ("yw_map", "yw_detail"):
                app.tap(*app.POS_TOP_HOME)
                app.wait(3)
                continue
            app.log("[活动返回] 当前页不属于已确认YW地图/详情/快捷导航，停止留证", "ERROR")
            return False
        return False

    @wraps(original_prepare)
    def prepare(event, display_name):
        if re.fullmatch(r"YW-[1-8]", str(display_name)):
            from yw_lobby_route_v1 import prepare as direct_prepare
            ready = direct_prepare(app, event, display_name)
        else:
            ready = original_prepare(event, display_name)
        if not ready or not re.fullmatch(r"YW-[1-8]", str(display_name)):
            return ready
        from stage_sanity_cost_yw_v1 import read_cost
        path = app.shot("yw_native_batch_before_maa")
        items = app.ocr(path)
        recognizer = getattr(app._ocr_engine, "text_recognizer", None)
        cost = read_cost(path, items, recognizer) if recognizer else None
        balances = {int(m[1]) for t, x, y in items if x >= 1550 and y <= 110
                    if (m := re.fullmatch(r"(\d{1,3})\s*/\s*210", str(t).strip()))}
        sanity = next(iter(balances)) if len(balances) == 1 else None
        maximum = capacity(sanity, cost["unit_cost"]) if cost else None
        app._RUN_SUMMARY.setdefault("event", {})["native_batch_plan"] = dict(
            stage=display_name, evidence=path, cost_reading=cost, sanity=sanity,
            affordable_up_to=maximum, configured_series=0, max_supported=10,
            selector="accepted_MaaCore_visible_list_AUTO",
            actual_batch_verified=False)
        # This diagnostic does not invent a new stop gate: the accepted stage
        # checks and MaaCore re-read/reduce the multiplier at every start.
        app.log(f"[快速刷取] {display_name}使用原生自动最大倍率，上限10；"
                f"当前理智={sanity}，可负担最多={maximum}份，实际份数以本轮结算为准")
        return ready

    @wraps(original_configure)
    def configure(cfg, stage, times, *args, **kwargs):
        result = original_configure(cfg, stage, times, *args, **kwargs)
        if re.fullmatch(r"YW-[1-8]", str(stage)):
            fight = next(t for t in app._task_queue(cfg) if t.get("TaskType") == "Fight")
            fight.update(Series=0, HideSeries=False, UseMedicine=False,
                         UseExpiringMedicine=False, MedicineCount=0, UseStone=False, StoneCount=0)
        return result

    @wraps(original_event)
    def event(*args, **kwargs):
        result = original_event(*args, **kwargs)
        summary = app._RUN_SUMMARY.get("event") or {}
        plan = summary.get("native_batch_plan") or {}
        farm = summary.get("farm") or {}
        if plan.get("stage") == farm.get("stage") and farm.get("actual_runs", 0) > 0:
            receipt = batch_receipt(farm, plan.get("affordable_up_to"))
            summary["native_batch_receipt"] = receipt
            plan["actual_batch_verified"] = receipt["verified"]
            app.log(f"[快速刷取实绩] 完成批次={receipt['actual_batches']}；"
                    f"次数对账={'通过' if receipt['verified'] else '未通过'}")
        return result

    app.goto_main_menu = home
    app._prepare_event_farm_stage = prepare
    app._configure_fight = configure
    app.mode_event = event
    from yw_stage_detail_input_v1 import install as install_detail_input
    install_detail_input(app)
    from yw_lobby_route_v1 import install as install_lobby
    install_lobby(app)
    return app


@contextmanager
def boundary(app):
    # This is the established late installation seam, after the legacy V6 /
    # DP adapters. Installing only on entry would be overwritten by them.
    import daily_mainline_completion_v1 as completion
    original = completion.install
    names = ("goto_main_menu", "goto_event_map", "_prepare_event_farm_stage", "_configure_fight", "mode_event", "_open_event_stage_detail")
    saved = []

    def late(runtime, *args, **kwargs):
        result = original(runtime, *args, **kwargs)
        saved.extend((name, getattr(runtime, name)) for name in names)
        install(runtime)
        return result

    with patch.object(completion, "install", late):
        try:
            yield
        finally:
            for name, value in reversed(saved):
                setattr(app, name, value)
