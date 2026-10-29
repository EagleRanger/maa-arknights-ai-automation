"""Keep the verified event stage detail open and hand it directly to MAA."""

from __future__ import annotations


def configure_farm_in_place(app, event):
    from event_availability_v12 import choose_activity_material
    from stage_sanity_cost_v2 import read_cost

    tip = app._refresh_depot_for_dynamic_333()
    choice = choose_activity_material(event, tip)
    if not choice:
        app.log("❌ 新活动材料库存尚未由本轮仓库刷新确认，不猜收益关", "ERROR")
        return False
    stage = choice["stage"]
    opened = app._open_event_stage_detail(event, stage, tag="new_event_farm_acceptance")
    if not opened:
        return False
    path, items, _text = opened
    recognizer = getattr(app._ocr_engine, "text_recognizer", None)
    if not recognizer:
        app.log("❌ 当前OCR没有小ROI文本识别接口", "ERROR")
        return False
    cost_reading = read_cost(path, items, recognizer)
    cost = cost_reading["unit_cost"] if cost_reading else None
    cleared = app._event_normal_badges_ratio(path) >= 0.08
    if not cleared or cost is None or not 1 <= cost <= 40:
        app.log(
            f"❌ {stage}材料关详情三星/单次理智未闭环: cleared={cleared},cost={cost}",
            "ERROR",
        )
        return False
    event.update(farm_stage=stage, farm_cost=cost)
    app._RUN_SUMMARY.setdefault("event", {})["farm_selection"] = dict(
        choice,
        verified=True,
        cost=cost,
        cost_reading=cost_reading,
        evidence=path,
        inventory_sync_time=tip["depot"]["sync_time"],
        detail_left_open_for_maa=True,
    )
    app.log(
        f"✅ 本轮库存选择{stage}：{choice['drop']}库存{choice['inventory']}；"
        f"三星与单次理智{cost}已核验，保留详情直接交给MAA"
    )
    return True


def current_detail_ready(app, display_name):
    path = app.shot(f"event_farm_handoff_{display_name}")
    items = app.ocr(path)
    text = " ".join(str(t) for t, _x, _y in items)
    if not app._event_stage_detail_confirmed(text, display_name, items):
        return False
    required = (display_name, "代理指挥", "开始行动")
    if any(marker not in text for marker in required):
        return False
    if "开始突袭" in text or "附加条件" in text:
        return False
    if app._event_normal_badges_ratio(path) < 0.08:
        return False
    if not app._event_proxy_command_selected(path):
        return False
    return True


def install_event_farm_detail_handoff(app):
    original_prepare = app._prepare_event_farm_stage
    if getattr(original_prepare, "_event_detail_handoff_v1", False):
        return original_prepare

    def prepare(event, display_name):
        if current_detail_ready(app, display_name):
            app.log(
                f"✅ {display_name}沿用刚核验的普通三星/代理详情，"
                "不退出地图重复定位"
            )
            return True
        return original_prepare(event, display_name)

    prepare._event_detail_handoff_v1 = True
    prepare._event_detail_handoff_original = original_prepare
    app._configure_new_event_farm_from_live_inventory = (
        lambda event: configure_farm_in_place(app, event)
    )
    app._prepare_event_farm_stage = prepare
    return prepare
