"""Base workers. No daily orchestrator, environment launch or finalisation."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re

from .core import Result

CN = timezone(timedelta(hours=8))


def observe_frame(items, screenshot, *, width, height, observed_at, historical=False):
    """Read only this frame. Old orders never determine the current product."""
    headers = []
    for text, x, y in items:
        match = re.fullmatch(r"(贸易站|制造站|活动室)(B\d{3})[0OIl1|]*", re.sub(r"\s+", "", str(text)))
        if match and y < height * .15:
            headers.append(match.groups())
    if len(headers) != 1:
        return Result("partial", "当前画面未确认唯一房间，不点击、不跳转",
                      (str(screenshot),), {"historical_replay": historical, "room_verified": False})
    facility, room = headers[0]
    product, proof = None, None
    text = " ".join(str(t) for t, _, _ in items)
    if facility == "贸易站" and "谈判策略" in text:
        # Negotiation is a right-hand setting, not the visible old order cards.
        setting = "".join(re.sub(r"\s+", "", str(t)) for t, x, y in items
                          if x > width * .72 and y > height * .72)
        if "龙门商法" in setting:
            product, proof = "LMD", "current_order_setting"
        elif "开采协力" in setting:
            product, proof = "Orundum", "current_order_setting"
    elif facility == "制造站":
        # Header + product title are necessary. Overview totals/old completion
        # toasts alone must not be interpreted as the current manufacturing job.
        detail = "".join(re.sub(r"\s+", "", str(t)) for t, x, y in items
                         if width * .2 < x < width * .75 and height * .15 < y < height * .8)
        candidates = [(label, value) for label, value in
                      (("赤金", "Pure Gold"), ("中级作战记录", "Battle Record"),
                       ("源石碎片", "Originium Shard")) if label in detail]
        if "当前制造" in detail and len(candidates) == 1:
            product, proof = candidates[0][1], "manufacturing_product_detail"
    data = {"room_id": room, "facility": facility, "header": facility + room,
            "room_verified": True, "current_product": product, "proof": proof,
            "observed_at": observed_at, "screenshot": str(screenshot),
            "historical_replay": historical, "six_rooms_verified": False,
            "game_inputs": 0, "sanity_spent": 0}
    verified = product is not None
    return Result("succeeded" if verified else "partial",
                  f"已识别{facility}{room}" + (f"，当前产品{product}" if verified else "，当前设置仍待核验"),
                  (str(screenshot),), data)


def observe_current(capture, read_items, dimensions):
    """Dependency-injected visual port: it has no click/cleanup capability."""
    path = capture("base_module_current")
    if not path or not Path(path).is_file():
        return Result("blocked", "没有取得游戏截图，未启动或关闭任何程序")
    width, height = dimensions(path)
    return observe_frame(read_items(path), path, width=width, height=height,
                         observed_at=datetime.now(CN).isoformat())


def plan(tip, *, now=None):
    """Reuse accepted 333 policy. A calculation is not a changed live product."""
    from daily_base_333_flow_balance_v1 import decide
    now = now or datetime.now(CN)
    depot = (tip or {}).get("depot") or {}
    try:
        stamp = datetime.fromisoformat(depot["sync_time"])
        fresh = stamp.tzinfo is not None and 0 <= (now - stamp).total_seconds() <= 3600
    except (KeyError, ValueError, TypeError):
        fresh = False
    if not fresh or depot.get("fresh") is not True:
        return Result("blocked", "库存不是当前新鲜数据，不调整产线")
    decision = decide(tip)
    if decision.get("status") != "selected":
        return Result("partial", "库存不足以形成排班结论", data={"decision": decision})
    return Result("succeeded", "已计算排班建议，尚未更改游戏产线",
                  ("inventory_sync:" + depot["sync_time"],),
                  {"decision": decision, "products_applied": False, "game_inputs": 0})


def use_drones(runtime, output, target, *, activity_rooms=None,
               rooms_complete=False, now=None):
    """Reuse the drone-only worker, never its CLI or the daily main()."""
    from activity_room_plan_v2 import all_rooms_max
    stamp = (now or datetime.now(CN)).isoformat()
    if not all_rooms_max(activity_rooms or [], at=stamp, rooms_complete=rooms_complete):
        return Result("blocked", "活动室升级完成证据不足，无人机仍预留；其它每日任务继续",
                      data={"before_action": True})
    if not target:
        return Result("blocked", "无人机生产目标尚未确认，仅保留本项", data={"before_action": True})
    from daily_base_333_drones_v1 import execute_drone_only
    if runtime._maa_task_queue_running() is not False:
        return Result("blocked", "其他队列仍持有游戏，本项未执行", data={"before_action": True})
    result = execute_drone_only(runtime, output, target=target)
    roi_ok = target is not None and target.get("room") == "manufacture" or result.get("roi_resource_restored") is True
    ok = (result.get("used_up_verified") is True and result.get("restored_infrast") is True
          and roi_ok)
    # Restoration failures are visible; they never trigger a whole-day retry.
    return Result("succeeded" if ok else "partial",
                  "无人机加速及配置恢复已核验" if ok else "无人机任务尚未完整核验，保留现场",
                  (str(Path(output) / "receipt.json"),), result)


def upgrade_activity_room(runtime, expected, output):
    """One prepared modal only; caller owns navigation and same-room readback."""
    from activity_room_upgrade_v1 import commit_one
    result = commit_one(runtime, expected, output)
    return Result('partial' if result.get('confirmation_sent') else 'blocked',
                  '已发单次升级确认，仍须同房等级回读' if result.get('confirmation_sent') else '升级页面未通过，未确认',
                  (str(Path(output)/'upgrade_receipt.json'),), result)


def synthesize_upgrade_material(runtime, expected, output):
    """No auto recipe/worker search, raw-material battle or cleanup."""
    from workshop_synthesis_v1 import commit_one
    result = commit_one(runtime, expected, output)
    return Result('partial' if result.get('confirmation_sent') else 'blocked',
                  '已发单批加工确认，仍须成品及库存回读' if result.get('confirmation_sent') else '加工产品/数量/资源未通过，未确认',
                  (str(Path(output)/'synthesis_receipt.json'),), result)


def invite_activity_user(runtime, room, name, output, *, trust_percent=0):
    """Reuse the accepted empty-room invitation; never recall an incumbent."""
    from activity_room_invite_v1 import commit_one
    result = commit_one(runtime, room, name, output, trust_percent=trust_percent)
    ok = result.get('status') == 'invited_verified'
    return Result('succeeded' if ok else 'partial' if result.get('confirmation_sent') else 'blocked',
                  '同房新使用者已回读' if ok else '活动室邀请未完整核验，不追加操作',
                  (str(Path(output)/'invite_receipt.json'),), result)


def service_activity_empty_room(runtime, position, output):
    """Reuse one accepted empty-room composition, no daily or lifecycle."""
    from run_activity_room_service_v1 import service
    result = service(runtime, position, Path(output))
    ok = result.get('status') == 'invited_verified'
    if result.get('replay_suppressed'):
        result['reused_previous_effect'] = True
    return Result('succeeded' if ok else 'partial' if result.get('confirmation_sent') else 'blocked',
                  '保留已完成邀请，本次未重复操作' if result.get('replay_suppressed') else
                  '空活动室信赖培养已同房回读' if ok else '本房尚未完成同房回读，不追加其他业务',
                  (str(Path(output)/'invite_receipt.json'),), result)
