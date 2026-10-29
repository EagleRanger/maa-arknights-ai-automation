"""Run Sami Integrated Strategies with UI-verified settlement and growth service.

The MAA queue owns an exploration only while it is active.  At a task-chain
error the supervisor never clicks through an unknown game page.  It drains only
known settlement layers, checks Culture Comparison at the safe theme home, and
starts the next bounded exploration afterwards.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from sami_run_records import bind_manifest, persist_terminal
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.environ.setdefault("ARKNIGHTS_AUTO_BASE", str(BASE))
sys.path.insert(0, str(BASE))

import arknights_auto as ark  # noqa: E402

CHECKPOINT = BASE / "outputs" / "sami_until_deadline_checkpoint.json"
SUPERVISOR_LOG = BASE / "outputs" / "sami_until_deadline.log"
FEEDBACK_OUTBOX = BASE / "outputs" / "sami_codex_feedback.json"
THEME = "Sami"
THEME_NAME = "探索者的银凇止境"
MAX_FAST_RECOVERIES = 3
CLEANUP_BUFFER = 60
TECHNICAL_COOLDOWN = 10 * 60
ATTENTION_STATUSES = {
    "single_instance_blocked",
    "environment_failed",
    "startup_page_unverified",
    "startup_rewards_unverified",
    "startup_culture_unverified",
    "record_rewards_unverified",
    "culture_upgrade_unverified",
    "technical_recovery_page_unverified",
    "supervisor_exception",
    "manifest_write_failed",
}


def now_iso():
    return datetime.now().astimezone().isoformat()


def note(message):
    line = f"[{now_iso()}] {message}"
    print(line, flush=True)
    SUPERVISOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SUPERVISOR_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def write_checkpoint(state):
    if not state.get('manifest_write_failed'):
        try:
            persist_terminal(state)
        except (OSError, ValueError) as exc:
            # 保留业务/清理事实；写回失败后交上层对账，不自动重写终态快照。
            state['manifest_write_failed'] = True
            state['manifest_write_warning'] = str(exc)
            state['receipt_status'] = 'manifest_write_failed'
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    temp = CHECKPOINT.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CHECKPOINT)


def terminal_exit_code(state):
    return 10 if state.get('manifest_write_failed') else 0


def _feedback_reason(state, status=None):
    status = status or state.get("status")
    if status == 'manifest_write_failed':
        return state.get('manifest_write_warning') or '清单未写回，需上层对账'
    # Report the failing service, not a successful service from an older round.
    service_keys = {
        "record_rewards_unverified": ("last_reward_service", "startup_rewards"),
        "culture_upgrade_unverified": ("last_culture_service", "startup_culture"),
    }.get(status, ())
    for key in service_keys:
        value = state.get(key)
        if isinstance(value, dict) and value.get("ok") is False and value.get("reason"):
            return str(value["reason"])
    last_session = state.get("last_session")
    if isinstance(last_session, dict) and last_session.get("technical_failure"):
        recovery = last_session.get("recovery_navigation")
        if isinstance(recovery, dict):
            navigation = recovery.get("navigation")
            if isinstance(navigation, dict) and navigation.get("reason"):
                return str(navigation["reason"])
            if recovery.get("reason"):
                return str(recovery["reason"])
        drained = last_session.get("settlement_drain")
        if isinstance(drained, dict) and drained.get("reason"):
            return str(drained["reason"])
        if last_session.get("maa_status"):
            return str(last_session["maa_status"])
    for key in (
        "last_culture_service",
        "last_reward_service",
        "startup_culture",
        "startup_rewards",
        "post_cooldown_navigation",
        "startup_navigation",
    ):
        value = state.get(key)
        if isinstance(value, dict) and value.get("reason"):
            return str(value["reason"])
    return None


def emit_attention_feedback(state, status, detail):
    """Persist one project-lane feedback packet for a genuine terminal blocker.

    The Python supervisor deliberately does not write into Codex's private task
    storage. The existing daily execution task relays pending packets through
    Codex's supported thread tool. Normal/deadline exits stay silent.
    """
    if status not in ATTENTION_STATUSES:
        return None
    reason = _feedback_reason(state, status)
    event_basis = {
        "started_at": state.get("started_at"),
        "status": status,
        "detail": detail,
        "reason": reason,
    }
    event_id = hashlib.sha256(
        json.dumps(event_basis, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    existing = None
    try:
        existing = json.loads(FEEDBACK_OUTBOX.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    if isinstance(existing, dict) and existing.get("event_id") == event_id:
        return existing
    packet = {
        "schema_version": 1,
        "project_loop_id": "auto-arknights-project-loop",
        "source": "run_sami_until_deadline.py",
        "destination": "project_lane",
        "event_id": event_id,
        "created_at": now_iso(),
        "needs_attention": True,
        "delivery_status": "pending",
        "status": status,
        "detail": detail,
        "reason": reason,
        "cleanup_finished": bool(state.get("cleanup_finished")),
        "business_status": state.get("status"),
        "run_id": state.get("run_id"),
        "run_manifest": state.get("run_manifest"),
        "receipt_status": state.get("receipt_status"),
        "cleanup_finished_at": state.get("cleanup_finished_at"),
        "checkpoint": str(CHECKPOINT),
        "supervisor_log": str(SUPERVISOR_LOG),
    }
    FEEDBACK_OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    temp = FEEDBACK_OUTBOX.with_suffix(".tmp")
    temp.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(FEEDBACK_OUTBOX)
    note(f"异常反馈待投递: {status} / {reason or detail}")
    return packet


def safe_emit_attention_feedback(state, status, detail):
    try:
        return emit_attention_feedback(state, status, detail)
    except Exception as exc:
        state["feedback_warning"] = f"{type(exc).__name__}: {exc}"
        write_checkpoint(state)
        return None


def next_deadline(value, now=None):
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value or ""))
    if not match:
        raise ValueError("截止时间必须为 HH:MM")
    hour, minute = map(int, match.groups())
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("截止时间超出有效范围")
    now = now or datetime.now().astimezone()
    result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if result <= now:
        result += timedelta(days=1)
    return result


def round_run_timeout(deadline, now=None):
    """Use the whole remaining control window for one MaaCore exploration.

    A Sami exploration can legitimately run for longer than one hour. The
    supervisor's 11:30 cleanup boundary is the only hard stop; applying an
    additional 3600-second cap can interrupt MaaCore in the middle of battle.
    """
    now_ts = time.time() if now is None else (
        now.timestamp() if hasattr(now, "timestamp") else float(now)
    )
    return max(30, int(deadline.timestamp() - now_ts) - CLEANUP_BUFFER)


def page(tag):
    path = ark.shot(tag)
    items = ark.ocr(path)
    text = " ".join(str(label or "") for label, _, _ in items)
    return path, items, text


def is_sami_home(text):
    # Full-title OCR sometimes drops 淞.  A suspended exploration changes the
    # primary action from 开始探索 to 继续探索, but the two independent service
    # controls remain stable and theme-specific.
    return (
        "探险手册" in text
        and "文化比较" in text
        and any(marker in text for marker in ("开始探索", "继续探索"))
    )


def is_culture_page(text):
    compact = re.sub(r"\s+", "", str(text or ""))
    # Real Sami screenshots have repeatedly produced the OCR variant 理性视阀.
    # The independent 0-43 counter keeps this tolerant title match scoped to
    # the culture page instead of turning it into a generic fuzzy match.
    return (
        any(marker in compact for marker in ("理性视阈", "理性视阀", "理性视阐"))
        and ("/43" in compact or "已比较" in compact)
    )


def is_sami_daily_sync_dialog(text, now=None):
    """Recognise only the exact 04:00 server-reset interruption."""
    now = now or datetime.now()
    compact = re.sub(r"\s+", "", str(text or ""))
    minute_of_day = now.hour * 60 + now.minute
    return (
        (3 * 60 + 59) <= minute_of_day <= (4 * 60 + 10)
        and "数据已更新" in compact
        and "即将进行同步" in compact
    )


def is_sami_network_disconnect(text):
    compact = re.sub(r"\s+", "", str(text or ""))
    return "与神经网络连接丢失" in compact and "错误号" in compact


def recover_sami_network_disconnect(text):
    """Confirm only the observed reconnect dialog after MaaCore is idle."""
    if not is_sami_network_disconnect(text):
        return None
    if ark._maa_task_queue_running():
        return {
            "ok": False,
            "reason": "network_disconnect_seen_while_maa_running",
            "actions": [],
        }
    position = (960, 735)
    ark.tap(*position)
    ark.wait(8)
    path, _, after_text = page("sami_network_reconnect_after")
    if is_sami_network_disconnect(after_text):
        return {
            "ok": False,
            "reason": "sami_network_reconnect_unverified",
            "actions": [{"kind": "confirm_network_reconnect", "position": position}],
            "screenshot": path,
        }
    return {
        "ok": True,
        "reason": "sami_network_reconnect_dialog_closed",
        "actions": [{"kind": "confirm_network_reconnect", "position": position}],
        "screenshot": path,
    }

def is_p3_login_overlay(text):
    """The observed P3 login calendar, not arbitrary reward/announcement text."""
    compact = re.sub(r"\s+", "", str(text or "")).upper()
    return all(marker in compact for marker in (
        "P3", "此夜同行", "LOGIN", "结束时间", "本活动中应急理智浓缩液",
    ))


def dismiss_p3_login_overlay(path, text):
    """Close one already-claimed calendar; navigation must verify the next page."""
    if not is_p3_login_overlay(text):
        return None
    result = {"ok": False, "screenshot": path, "actions": []}
    if ark._maa_task_queue_running():
        return dict(result, reason="p3_login_overlay_maa_running")
    if "物资已领取" not in re.sub(r"\s+", "", text):
        return dict(result, reason="p3_login_reward_claim_unverified")
    from PIL import Image
    with Image.open(path) as image:
        if image.size != (1920, 1080):
            return dict(result, reason="p3_login_overlay_size_unverified")
    # Exact close-circle position in the 2026-09-05 saved failure frame.
    position = (1849, 151)
    ark.tap(*position)
    ark.wait(3)
    after_path, _, after_text = page("sami_p3_login_closed")
    result.update({
        "actions": [{"kind": "close_claimed_p3_login", "position": position}],
        "after_screenshot": after_path,
        "ok": not is_p3_login_overlay(after_text),
    })
    result["reason"] = (
        "p3_login_overlay_closed" if result["ok"]
        else "p3_login_overlay_close_unverified"
    )
    return result


def recover_sami_daily_sync(text, now=None, timeout=240):
    """Acknowledge the verified reset dialog and return to the Sami home."""
    if not is_sami_daily_sync_dialog(text, now=now):
        return None
    if ark._maa_task_queue_running():
        return {
            "ok": False,
            "reason": "daily_sync_dialog_seen_while_maa_running",
            "actions": [],
        }

    actions = [{"kind": "confirm_daily_sync", "position": (960, 735)}]
    ark.tap(960, 735)
    deadline = time.time() + timeout
    display_launch_attempted = False
    while time.time() < deadline:
        ark.wait(5)
        state = ark.get_state()
        if state == "main_menu":
            navigation = navigate_to_sami_home()
            return {
                "ok": bool(navigation.get("ok")),
                "reason": (
                    "daily_sync_recovered_to_sami_home"
                    if navigation.get("ok")
                    else "daily_sync_sami_navigation_unverified"
                ),
                "actions": actions,
                "navigation": navigation,
            }
        if state == "login":
            ark.tap(*ark.POS_LOGIN_START)
            actions.append({"kind": "login_after_daily_sync", "position": ark.POS_LOGIN_START})
            ark.wait(10)
            continue
        if state == "announcement":
            if not ark._dismiss_announcement_overlay():
                return {
                    "ok": False,
                    "reason": "daily_sync_announcement_close_unconfirmed",
                    "actions": actions,
                }
            actions.append({"kind": "dismiss_announcement_after_daily_sync"})
            continue
        if state == "network_error":
            path, items, _ = page("sami_daily_sync_network")
            position = (
                ark.find_text(items, "重新连接", exact=True)
                or ark.find_text(items, "重试", exact=True)
                or ark.find_text(items, "确定", exact=True)
            )
            if not position:
                return {
                    "ok": False,
                    "reason": "daily_sync_network_action_unconfirmed",
                    "actions": actions,
                    "screenshot": path,
                }
            ark.tap(*position)
            actions.append({"kind": "network_retry_after_daily_sync", "position": position})
            continue
        if state == "home_screen" and not display_launch_attempted:
            display_launch_attempted = True
            if not ark.ensure_env():
                return {
                    "ok": False,
                    "reason": "daily_sync_game_relaunch_failed",
                    "actions": actions,
                }
            actions.append({"kind": "relaunch_game_after_daily_sync"})
            continue
        path, _, overlay_text = page("sami_daily_sync_overlay")
        overlay = dismiss_p3_login_overlay(path, overlay_text)
        if overlay is not None:
            actions.append({"kind": "p3_login_recovery", "result": overlay})
            if not overlay.get("ok"):
                return {"ok": False, "reason": overlay["reason"], "actions": actions}
            continue
        if state == "unknown" and ark.handle_popups():
            actions.append({"kind": "dismiss_verified_popup_after_daily_sync"})
            continue
    return {
        "ok": False,
        "reason": "daily_sync_recovery_timeout",
        "actions": actions,
    }

def sami_theme_entry_position(items):
    """Return only the entry button belonging to a visible Sami theme card."""
    titles = [
        (cx, cy)
        for label, cx, cy in (items or [])
        if any(
            marker in str(label or "").upper()
            for marker in (
                "银凇",
                "银淞",
                "银松",
                "银止境",
                "探索者",
                "索者的银",
                "JOKLUMARKAR",
                "JQKLUMARKAR",
                "JCKLUMARKAR",
                "SAM",
            )
        )
    ]
    buttons = [
        (cx, cy)
        for label, cx, cy in (items or [])
        if "进入主题" in str(label or "")
    ]
    if not titles or not buttons:
        return None
    title_x = min(titles, key=lambda pos: pos[1])[0]
    return min(buttons, key=lambda pos: abs(pos[0] - title_x))


def navigate_to_sami_home(max_steps=18):
    """Reach Sami through verified UI states, never the last-theme shortcut."""
    theme_swipes = 0
    evidence = []
    actions = []
    for step in range(max_steps):
        path, items, text = page(f"sami_home_nav_{step + 1}")
        evidence.append(path)
        overlay = dismiss_p3_login_overlay(path, text)
        if overlay is not None:
            actions.append({"kind": "p3_login_recovery", "result": overlay})
            if not overlay.get("ok"):
                return {"ok": False, "reason": overlay["reason"],
                        "actions": actions, "evidence": evidence, "screenshot": path}
            continue
        if is_sami_home(text):
            return {
                "ok": True,
                "state": "sami_home",
                "steps": step,
                "actions": actions,
                "evidence": evidence,
                "screenshot": path,
            }

        if is_culture_page(text):
            ark.tap(*ark.POS_BACK)
            ark.wait(4)
            actions.append({"kind": "culture_back"})
            continue

        network_recovery = recover_sami_network_disconnect(text)
        if network_recovery is not None:
            actions.append({"kind": "network_recovery", "result": network_recovery})
            if not network_recovery.get("ok"):
                return {
                    "ok": False,
                    "reason": network_recovery.get("reason"),
                    "actions": actions,
                    "evidence": evidence,
                    "screenshot": network_recovery.get("screenshot") or path,
                }
            continue

        if "获得物资" in text or "首次获得" in text:
            ark.tap(*ark.POS_DISMISS)
            ark.wait(3)
            actions.append({"kind": "reward_dismiss"})
            continue

        announcement_markers = sum(
            marker in text for marker in ("活动公告", "系统公告", "资讯速报")
        )
        if announcement_markers >= 2:
            if not ark._dismiss_announcement_overlay():
                return {
                    "ok": False,
                    "reason": "announcement_close_unconfirmed",
                    "actions": actions,
                    "evidence": evidence,
                    "screenshot": path,
                }
            actions.append({"kind": "dismiss_login_announcement"})
            continue

        terminal = ark.find_text(items, "终端", exact=True)
        if terminal and any(marker in text for marker in ("编队", "干员", "公开招募")):
            ark.tap(*terminal)
            ark.wait(6)
            actions.append({"kind": "open_terminal", "position": terminal})
            continue

        if "ATTENTION" in text and "集成战略" in text:
            ark.tap(1435, 1000)
            ark.wait(6)
            actions.append({"kind": "open_integrated_strategies"})
            continue

        if "长期探索" in text and "集成战略" in text and "查看全部主题" in text:
            view_all = [
                (cx, cy)
                for label, cx, cy in items
                if "查看全部主题" in str(label or "") and cx < 1100
            ]
            if view_all:
                position = min(view_all, key=lambda pos: pos[0])
                ark.tap(*position)
                ark.wait(6)
                actions.append({"kind": "view_all_themes", "position": position})
                continue

        theme_entry = sami_theme_entry_position(items)
        if theme_entry:
            ark.tap(*theme_entry)
            ark.wait(7)
            actions.append({"kind": "enter_sami", "position": theme_entry})
            continue

        if "进入主题" in text and theme_swipes < 4:
            ark.swipe(500, 850, 1600, 850, 800)
            theme_swipes += 1
            ark.wait(5)
            actions.append({"kind": "theme_swipe", "count": theme_swipes})
            continue

        recovery = ark._close_roguelike_interruption_once()
        if recovery:
            actions.append(recovery)
            continue
        return {
            "ok": False,
            "reason": "sami_home_unknown_page",
            "actions": actions,
            "evidence": evidence,
            "screenshot": path,
        }
    return {
        "ok": False,
        "reason": "sami_home_step_limit",
        "actions": actions,
        "evidence": evidence,
    }


def establish_sami_home():
    """Normalise a safe settlement or navigate from the ordinary main menu."""
    drained = drain_safe_settlement()
    if drained.get("ok"):
        return {"ok": True, "source": "safe_settlement", "settlement": drained}
    navigation = navigate_to_sami_home()
    return {
        "ok": bool(navigation.get("ok")),
        "source": "verified_navigation",
        "initial_settlement": drained,
        "navigation": navigation,
    }


def is_expedition_records_page(text):
    compact = re.sub(r"\s+", "", str(text or ""))
    return (
        "购买等级" in compact
        and any(marker in compact for marker in ("列表中查看", "可获取主题干员", "可领取"))
        and any(marker in compact for marker in ("一键领取", "EXP", "LV"))
    )


def expedition_claimable_count(items):
    return sum(
        1
        for label, _, _ in (items or [])
        if re.sub(r"\s+", "", str(label or "")) == "可领取"
    )


def sami_record_outfit_layer(text):
    """Only the Typhon outfit observed in the Sami reward claim chain."""
    compact = re.sub(r"\s+", "", str(text or "")).upper()
    if all(marker in compact for marker in ("VITAFIELD", "FLOT", "北地引路人", "提丰", "穿戴")):
        return "ready"
    if all(marker in compact for marker in ("VITAFIELD", "FLOT", "BRANDNEWOUTFIT")):
        return "animation"
    return None


def service_expedition_records(max_layers=8):
    """Claim the permanent expedition-record rewards and prove the pending count fell."""
    result = {"ok": False, "screenshots": [], "actions": []}
    nav = establish_sami_home()
    result["navigation"] = nav
    if not nav.get("ok"):
        result["reason"] = "sami_home_not_reached_for_records"
        return result

    home_path, home_items, home_text = page("sami_records_home")
    result["screenshots"].append(home_path)
    if not is_sami_home(home_text):
        result["reason"] = "sami_home_not_confirmed_for_records"
        return result
    entry = next(
        (
            (int(x), int(y))
            for label, x, y in home_items
            if "科考记录" in str(label or "") and int(x) >= 1450 and int(y) <= 180
        ),
        None,
    )
    if not entry:
        result["reason"] = "expedition_records_entry_not_found"
        return result
    ark.tap(*entry)
    ark.wait(5)

    path, items, text = page("sami_records_open")
    result["screenshots"].append(path)
    if not is_expedition_records_page(text):
        result["reason"] = "expedition_records_page_not_confirmed"
        return result

    pending_before = expedition_claimable_count(items)
    result["pending_before"] = pending_before
    if pending_before <= 0:
        result.update({"ok": True, "reason": "no_claimable_record_rewards", "pending_after": 0})
    else:
        claim = (
            ark.find_text(items, "一键领取", exact=True)
            or ark.find_text(items, "一键领取")
        )
        if not claim:
            result["reason"] = "records_one_key_claim_not_found"
            return result
        ark.tap(*claim)
        ark.wait(4)
        result["actions"].append({"kind": "one_key_claim", "position": claim})

        outfit_dismissed = False
        for layer in range(int(max_layers)):
            path, items, text = page(f"sami_records_claim_{layer}")
            result["screenshots"].append(path)
            if is_expedition_records_page(text):
                pending_after = expedition_claimable_count(items)
                result["pending_after"] = pending_after
                if pending_after < pending_before:
                    result.update({
                        "ok": True,
                        "reason": "record_rewards_claimed_verified",
                    })
                else:
                    result["reason"] = "record_reward_effect_unverified"
                break

            outfit = sami_record_outfit_layer(text)
            if outfit:
                if ark._maa_task_queue_running():
                    result["reason"] = "records_maa_busy"
                    break
                if outfit == "animation":
                    # Let the reveal finish; never click moving artwork.
                    ark.wait(3)
                    continue
                if outfit_dismissed:
                    result["reason"] = "record_outfit_dismiss_unverified"
                    break
                from PIL import Image
                with Image.open(path) as reward_image:
                    reward_size = reward_image.size
                if reward_size != (1920, 1080):
                    result["reason"] = "record_outfit_resolution_unverified"
                    break
                # Existing neutral dismissal area, well away from Wear.
                ark.tap(*ark.POS_DISMISS)
                ark.wait(3)
                outfit_dismissed = True
                result["actions"].append({"kind": "dismiss_record_outfit", "position": ark.POS_DISMISS})
                continue

            compact = re.sub(r"\s+", "", text)
            if any(marker in compact for marker in (
                "获得物资", "获得奖励", "奖励获得", "首次获得", "已获得",
            )):
                dismiss = (
                    ark.find_text(items, "确定", exact=True)
                    or ark.find_text(items, "确认", exact=True)
                    or ark.find_text(items, "收下", exact=True)
                    or ark.POS_DISMISS
                )
                ark.tap(*dismiss)
                ark.wait(3)
                result["actions"].append({
                    "kind": "dismiss_record_reward",
                    "position": dismiss,
                })
                continue

            result["reason"] = "record_reward_unknown_layer"
            result["unknown_screenshot"] = path
            break
        else:
            result["reason"] = "record_reward_layer_limit"

    path, _, text = page("sami_records_before_back")
    if is_expedition_records_page(text):
        ark.tap(*ark.POS_BACK)
        ark.wait(4)
    home_path, _, home_text = page("sami_records_home_after")
    result["screenshots"].append(home_path)
    result["home_confirmed_after"] = is_sami_home(home_text)
    if not result["home_confirmed_after"]:
        result["navigation_reason"] = "home_not_reached_after_records"
        if result.get("ok") or not result.get("reason"):
            result["reason"] = "home_not_reached_after_records"
        result["ok"] = False
    return result


def culture_progress(text):
    matches = re.findall(r"(\d{1,2})\s*/\s*43", str(text or ""))
    for raw in matches:
        value = int(raw)
        if 0 <= value <= 43:
            return value
        # On the Sami counter OCR can merge the decorative vertical stroke
        # after a one-digit value into a trailing 1: real 6/43 -> 61 /43.
        if len(raw) == 2 and raw.endswith("1") and 0 <= int(raw[0]) <= 9:
            return int(raw[0])
    return None


def culture_points(path, items):
    for label, x, y in items:
        match = re.fullmatch(r"\s*(\d{1,2})\s*", str(label or ""))
        if match and int(x) >= 1740 and int(y) <= 130:
            return int(match.group(1))
    try:
        import cv2
        import numpy as np

        data = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        roi = image[5:95, 1800:1915]
        enlarged = cv2.resize(roi, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        encoded = cv2.imencode(".png", enlarged)[1]
        crop_path = str(Path(path).with_name(Path(path).stem + "_points.png"))
        encoded.tofile(crop_path)
        for label, _, _ in ark.ocr(crop_path):
            match = re.search(r"\d{1,2}", str(label or ""))
            if match:
                return int(match.group())

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = ((hsv[:, :, 1] <= 70) & (hsv[:, :, 2] >= 175)).astype("uint8") * 255
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        components = [stats[i] for i in range(1, count) if int(stats[i, 4]) >= 80]
        if len(components) == 1:
            _, _, width, height, area = [int(v) for v in components[0]]
            ratio = width / max(1, height)
            if area >= 180 and 0.62 <= ratio <= 1.05:
                return 0
    except Exception:
        pass
    return None


def cyan_node_candidates(path):
    """Find real Sami culture node polygons; small connector arrows are excluded."""
    try:
        import cv2
        import numpy as np

        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return []
        gray = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (7, 7), 1.5)
        edges = cv2.Canny(gray, 50, 140)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(
            edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )
        height, width = image.shape[:2]
        candidates = []
        for contour in contours:
            x, y, box_width, box_height = cv2.boundingRect(contour)
            area = float(cv2.contourArea(contour))
            aspect = box_width / max(1, box_height)
            vertices = len(
                cv2.approxPolyDP(
                    contour,
                    0.03 * cv2.arcLength(contour, True),
                    True,
                )
            )
            if not (
                80 <= box_width <= 170
                and 75 <= box_height <= 170
                and 0.65 <= aspect <= 1.40
                and area >= 2200
                and 4 <= vertices <= 14
                and 140 <= x <= width - 150
                and 150 <= y <= height - 160
            ):
                continue
            candidates.append((
                int(x + box_width / 2),
                int(y + box_height / 2),
                area,
            ))

        deduped = []
        for cx, cy, area in sorted(candidates, key=lambda item: item[2], reverse=True):
            if any(abs(cx - ox) < 45 and abs(cy - oy) < 45 for ox, oy, _ in deduped):
                continue
            deduped.append((cx, cy, area))
        return [
            (cx, cy)
            for cx, cy, _ in sorted(deduped, key=lambda item: (item[0], item[1]))
        ]
    except Exception:
        return []


def culture_upgrade_glow_candidates(path):
    """Find dark culture nodes surrounded by the translucent upgrade halo."""
    try:
        import cv2
        import numpy as np

        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return []
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hue, saturation, value = cv2.split(hsv)
        cyan = (
            (hue >= 75)
            & (hue <= 105)
            & (saturation >= 40)
            & (value >= 45)
        )
        yy, xx = np.ogrid[: image.shape[0], : image.shape[1]]
        scored = []
        for cx, cy in cyan_node_candidates(path):
            radius_sq = (xx - cx) ** 2 + (yy - cy) ** 2
            inner = radius_sq <= 35 ** 2
            halo = (radius_sq >= 50 ** 2) & (radius_sq <= 65 ** 2)
            if not inner.any() or not halo.any():
                continue
            inner_cyan_ratio = float((cyan & inner).sum() / inner.sum())
            halo_cyan_ratio = float((cyan & halo).sum() / halo.sum())
            halo_value = float(value[halo].mean())
            if (
                inner_cyan_ratio < 0.08
                and halo_cyan_ratio >= 0.35
                and halo_value >= 38.0
            ):
                score = halo_cyan_ratio + min(halo_value, 100.0) / 200.0
                scored.append((cx, cy, score))
        return [
            (cx, cy)
            for cx, cy, _ in sorted(scored, key=lambda item: item[2], reverse=True)
        ]
    except Exception:
        return []

def open_culture_view(section, max_sections=18):
    """Open one deterministic horizontal viewport of the Sami culture graph."""
    nav = establish_sami_home()
    if not nav.get("ok"):
        return {"ok": False, "reason": "sami_home_not_reached", "navigation": nav}
    home_path, home_items, home_text = page(f"sami_culture_grid_home_s{section}")
    if not is_sami_home(home_text):
        return {
            "ok": False,
            "reason": "sami_home_not_confirmed",
            "navigation": nav,
            "screenshot": home_path,
        }
    entry = (
        ark.find_text(home_items, "文化比较", exact=True)
        or ark.find_text(home_items, "文化比较")
    )
    if not entry:
        return {
            "ok": False,
            "reason": "culture_entry_not_found",
            "navigation": nav,
            "screenshot": home_path,
        }
    ark.wait(2)
    ark.tap(*entry)
    ark.wait(5)
    path, items, text = page(f"sami_culture_grid_open_s{section}")
    if not is_culture_page(text):
        return {
            "ok": False,
            "reason": "culture_page_not_confirmed",
            "navigation": nav,
            "screenshot": path,
        }

    # Reset to the left boundary, then advance with overlapping 360 px steps.
    # The old 1050 px jump skipped upgradeable nodes in the front/middle tree.
    for _ in range(8):
        ark.swipe(500, 540, 1550, 540, 550)
        ark.wait(0.35)
    for _ in range(int(section)):
        ark.swipe(1220, 540, 860, 540, 500)
        ark.wait(0.8)

    path, items, text = page(f"sami_culture_grid_s{section}")
    if not is_culture_page(text):
        return {
            "ok": False,
            "reason": "culture_page_not_confirmed_after_pan",
            "navigation": nav,
            "screenshot": path,
        }
    return {
        "ok": True,
        "navigation": nav,
        "screenshot": path,
        "items": items,
        "text": text,
        "section": int(section),
    }


def advance_culture_view(section):
    """Advance exactly one overlapping viewport without leaving the culture graph."""
    ark.swipe(1220, 540, 860, 540, 500)
    ark.wait(0.8)
    path, items, text = page(f"sami_culture_grid_s{section}")
    if not is_culture_page(text):
        return {
            "ok": False,
            "reason": "culture_page_not_confirmed_after_incremental_pan",
            "screenshot": path,
            "section": int(section),
        }
    return {
        "ok": True,
        "screenshot": path,
        "items": items,
        "text": text,
        "section": int(section),
    }


def spend_one_culture_point(before_progress, before_points, tree_path, excluded_candidates=None):
    excluded_candidates = tuple(excluded_candidates or ())
    candidates = [
        point
        for point in culture_upgrade_glow_candidates(tree_path)
        if all(
            (point[0] - rejected[0]) ** 2 + (point[1] - rejected[1]) ** 2 > 45 ** 2
            for rejected in excluded_candidates
        )
    ]
    if not candidates:
        return {"ok": False, "reason": "no_upgrade_glow_candidate"}

    # Sami uses a two-stage node selection. The first tap recentres the graph;
    # only a second tap on the freshly relocated same node opens the action.
    # Never reuse the pre-recentre coordinates.
    candidate = candidates[0]
    recentered_candidate = None
    ark.tap(*candidate)
    ark.wait(2)
    detail_path, detail_items, detail_text = page("sami_culture_node_recentered")
    compact = re.sub(r"\s+", "", detail_text)
    if "当前在探索中" in compact:
        return {
            "ok": False,
            "reason": "culture_locked_by_active_exploration",
            "candidate": candidate,
            "screenshot": detail_path,
        }
    if any(marker in compact for marker in ("未解锁", "理性视阈不足", "理性视阐不足", "升级任意前置节点后", "自动解锁")):
        return {
            "ok": False,
            "reason": "glow_candidate_not_upgradeable",
            "candidate": candidate,
            "screenshot": detail_path,
        }
    action = next(
        (
            (x, y)
            for label, x, y in detail_items
            if re.sub(r"\s+", "", str(label or ""))
            in {"比较", "确认比较", "解锁", "确认升级"}
        ),
        None,
    )
    if not action:
        relocated = culture_upgrade_glow_candidates(detail_path)
        same_row = [point for point in relocated if abs(point[1] - candidate[1]) <= 35]
        if not same_row:
            return {
                "ok": False,
                "reason": "recentered_glow_candidate_not_found",
                "candidate": candidate,
                "screenshot": detail_path,
            }
        recentered_candidate = same_row[0]
        ark.tap(*recentered_candidate)
        ark.wait(2)
        detail_path, detail_items, detail_text = page("sami_culture_node_detail")
        compact = re.sub(r"\s+", "", detail_text)
        if "当前在探索中" in compact:
            return {
                "ok": False,
                "reason": "culture_locked_by_active_exploration",
                "candidate": candidate,
                "recentered_candidate": recentered_candidate,
                "screenshot": detail_path,
            }
        if any(marker in compact for marker in ("未解锁", "理性视阈不足", "理性视阐不足", "升级任意前置节点后", "自动解锁")):
            return {
                "ok": False,
                "reason": "glow_candidate_not_upgradeable",
                "candidate": candidate,
                "recentered_candidate": recentered_candidate,
                "screenshot": detail_path,
            }
        action = next(
            (
                (x, y)
                for label, x, y in detail_items
                if re.sub(r"\s+", "", str(label or ""))
                in {"比较", "确认比较", "解锁", "确认升级"}
            ),
            None,
        )
    if not action:
        return {
            "ok": False,
            "reason": "glow_candidate_missing_upgrade_action",
            "candidate": candidate,
            "recentered_candidate": recentered_candidate,
            "screenshot": detail_path,
        }
    ark.tap(*action)
    ark.wait(3)
    confirm_path, confirm_items, confirm_text = page("sami_culture_upgrade_confirm")
    confirm = next(
        (
            (x, y)
            for label, x, y in confirm_items
            if re.sub(r"\s+", "", str(label or "")) in {"确认", "确定", "确认比较"}
        ),
        None,
    )
    if confirm and any(marker in confirm_text for marker in ("理性视阈", "理性视阀", "理性视阐")):
        ark.tap(*confirm)
        ark.wait(4)
        confirm_path, confirm_items, confirm_text = page("sami_culture_upgrade_after")
    after_progress = culture_progress(confirm_text)
    after_points = culture_points(confirm_path, confirm_items)
    if (
        after_progress is not None
        and after_progress > before_progress
        and after_points is not None
        and after_points < before_points
    ):
        return {
            "ok": True,
            "candidate": candidate,
            "recentered_candidate": recentered_candidate,
            "progress_before": before_progress,
            "progress_after": after_progress,
            "points_before": before_points,
            "points_after": after_points,
        }
    return {
        "ok": False,
        "reason": "upgrade_effect_unverified",
        "candidate": candidate,
        "screenshot": confirm_path,
    }

def service_culture(max_upgrades=43, max_sections=18):
    """Spend every currently available culture point using verified graph viewports."""
    result = {"ok": False, "upgrades": [], "scans": [], "screenshots": []}
    for upgrade_index in range(int(max_upgrades) + 1):
        purchased = False
        before_progress = None
        before_points = None
        seen_view_signatures = set()
        for section in range(int(max_sections)):
            view = (
                open_culture_view(0, max_sections=max_sections)
                if section == 0
                else advance_culture_view(section)
            )
            result["navigation"] = view.get("navigation", result.get("navigation"))
            path = view.get("screenshot")
            if path:
                result["screenshots"].append(path)
            if not view.get("ok"):
                result["reason"] = view.get("reason") or "culture_view_unverified"
                return result

            items = view["items"]
            text = view["text"]
            progress = culture_progress(text)
            points = culture_points(path, items)
            if before_progress is None:
                before_progress = progress
                before_points = points
                result.update({
                    "progress": progress,
                    "points_remaining": points,
                })
                if progress is None or points is None:
                    result["reason"] = "culture_counter_unverified"
                    return result
                if points <= 0 or progress >= 43:
                    ark.tap(*ark.POS_BACK)
                    ark.wait(4)
                    _, _, home_text = page("sami_culture_home_complete")
                    result.update({
                        "ok": is_sami_home(home_text),
                        "reason": "no_points" if points <= 0 else "culture_complete",
                        "home_confirmed_after": is_sami_home(home_text),
                    })
                    return result

            geometry_candidates = cyan_node_candidates(path)
            candidates = culture_upgrade_glow_candidates(path)
            result["scans"].append({
                "upgrade": upgrade_index,
                "section": section,
                "progress": progress,
                "points": points,
                "candidates": candidates,
                "geometry_candidates": geometry_candidates,
            })
            signature = tuple(
                (round(x / 20), round(y / 20))
                for x, y in geometry_candidates
            )
            if signature in seen_view_signatures:
                result["scans"][-1]["duplicate_view"] = True
                break
            seen_view_signatures.add(signature)
            excluded_candidates = []
            while True:
                upgrade = spend_one_culture_point(
                    before_progress,
                    before_points,
                    path,
                    excluded_candidates=excluded_candidates,
                )
                upgrade["section"] = section
                if upgrade.get("ok"):
                    result["upgrades"].append(upgrade)
                    result.update({
                        "progress": upgrade.get("progress_after"),
                        "points_remaining": upgrade.get("points_after"),
                    })
                    purchased = True
                    break

                reason = upgrade.get("reason")
                if reason in {
                    "culture_locked_by_active_exploration",
                    "upgrade_effect_unverified",
                }:
                    result["upgrades"].append(upgrade)
                    result["reason"] = reason
                    return result
                if reason not in {
                    "glow_candidate_not_upgradeable",
                    "glow_candidate_missing_upgrade_action",
                    "recentered_glow_candidate_not_found",
                }:
                    break

                result.setdefault("candidate_rejections", []).append(upgrade)
                rejected = upgrade.get("candidate")
                if not rejected:
                    break
                excluded_candidates.append(tuple(rejected))
                refresh = open_culture_view(section, max_sections=max_sections)
                refresh_path = refresh.get("screenshot")
                if refresh_path:
                    result["screenshots"].append(refresh_path)
                if not refresh.get("ok"):
                    result["reason"] = refresh.get("reason") or "culture_view_refresh_unverified"
                    return result
                refresh_progress = culture_progress(refresh["text"])
                refresh_points = culture_points(refresh_path, refresh["items"])
                if refresh_progress != before_progress or refresh_points != before_points:
                    result["reason"] = "culture_counter_changed_without_verified_upgrade"
                    return result
                path = refresh_path
            if purchased:
                break

        if purchased:
            continue

        home = establish_sami_home()
        home_ok = bool(home.get("ok"))
        result.update({
            "ok": home_ok,
            "reason": (
                "no_currently_unlockable_culture_node"
                if home_ok
                else "home_not_reached_after_culture_scan"
            ),
            "progress": before_progress,
            "points_remaining": before_points,
            "home_confirmed_after": home_ok,
        })
        return result

    result["reason"] = "culture_upgrade_budget_exhausted"
    return result

def drain_safe_settlement(max_steps=10):
    actions = []
    for index in range(max_steps):
        _, _, text = page(f"sami_settlement_drain_{index}")
        if is_sami_home(text):
            return {"ok": True, "state": "sami_home", "actions": actions}
        if is_culture_page(text):
            ark.tap(*ark.POS_BACK)
            ark.wait(4)
            actions.append({"kind": "culture_back"})
            continue
        network_recovery = recover_sami_network_disconnect(text)
        if network_recovery is not None:
            actions.append({"kind": "network_recovery", "result": network_recovery})
            if network_recovery.get("ok"):
                continue
            return {
                "ok": False,
                "state": "network_recovery_failed",
                "actions": actions,
                "reason": network_recovery.get("reason"),
            }
        daily_sync = recover_sami_daily_sync(text)
        if daily_sync is not None:
            actions.append({"kind": "daily_sync_recovery", "result": daily_sync})
            if daily_sync.get("ok"):
                return {
                    "ok": True,
                    "state": "sami_home",
                    "actions": actions,
                    "daily_sync_recovery": daily_sync,
                }
            return {
                "ok": False,
                "state": "daily_sync_recovery_failed",
                "actions": actions,
                "daily_sync_recovery": daily_sync,
            }
        recovery = ark._close_roguelike_interruption_once()
        if not recovery:
            return {"ok": False, "state": "unknown", "actions": actions}
        actions.append(recovery)
    return {"ok": False, "state": "step_limit", "actions": actions}


def cleanup(state, status, detail):
    state.update({"status": status, "detail": detail, "finished_at": now_iso()})
    write_checkpoint(state)
    try:
        if ark._maa_task_queue_running():
            ark._stop_maa_task_queue(timeout=45)
    finally:
        ark.cleanup_after_task(check_badges=False)
        ark.stop_log_viewer()
        try:
            ark.record_long_term_handoff("sami", status, detail=detail, cleanup_finished=True)
        except Exception as exc:
            state["handoff_warning"] = str(exc)
        state.update({"cleanup_finished": True, "cleanup_finished_at": now_iso()})
        write_checkpoint(state)
        if state.get('manifest_write_failed'):
            safe_emit_attention_feedback(state, 'manifest_write_failed',
                f'清理事实已保留，但运行清单未写回；原终态={status}；{detail}。需上层对账，禁止当作完整收口。')
        else:
            safe_emit_attention_feedback(state, status, detail)


def release_environment_for_cooldown(state, detail):
    state.update({"status": "technical_cooldown", "detail": detail, "cooldown_started_at": now_iso()})
    write_checkpoint(state)
    if ark._maa_task_queue_running():
        ark._stop_maa_task_queue(timeout=45)
    ark.cleanup_after_task(check_badges=False)
    ark.stop_log_viewer()
    state["environment_released_for_cooldown"] = True
    state["environment_released_at"] = now_iso()
    write_checkpoint(state)


def run(deadline, core_char, squad, roles, no_viewer=False, run_manifest=None, run_id=None):
    state = {
        "started_at": now_iso(),
        "deadline": deadline.isoformat(),
        "status": "preparing",
        "policy": {
            "theme": THEME,
            "difficulty": "highest_unlocked",
            "mode": "Exp",
            "starts_count": 1,
            "core_char": core_char,
            "squad": squad,
            "roles": roles,
            "reward_service": "startup_and_after_every_safe_settlement",
            "culture_service": "startup_and_after_every_safe_settlement",
            "use_foldartal": False,
            "execution_backend": "MaaCore",
            "technical_fast_recoveries": MAX_FAST_RECOVERIES,
            "technical_cooldown_seconds": TECHNICAL_COOLDOWN,
            "round_timeout_policy": "global_cleanup_boundary_only",
        },
        "sessions": [],
    }
    state.update(bind_manifest(run_manifest, run_id))
    current = datetime.now().astimezone()
    if (11, 30) <= (current.hour, current.minute) < (12, 0):
        print("每日任务准备窗口：本次不启动肉鸽，不排队补跑。", flush=True)
        return 2
    if not ark.acquire_single_instance():
        # A duplicate/waiter must never overwrite the active supervisor's file.
        return 2
    write_checkpoint(state)
    try:
        assert ark.compile_execution_plan("roguelike", theme="sami") is not None
        if not no_viewer:
            ark.stop_log_viewer()
            ark.start_log_viewer(
                log_file=str(SUPERVISOR_LOG),
                title="明日方舟银淞肉鸽运行日志",
                status_text="银淞止境：单轮探索 / 结算核验 / 文化比较加点",
            )
        if not ark.ensure_env():
            cleanup(state, "environment_failed", "环境启动失败")
            return 3
        if ark._maa_task_queue_running():
            state["status"] = "existing_queue_running"
            write_checkpoint(state)
            while time.time() < deadline.timestamp() and ark._maa_task_queue_running():
                time.sleep(15)
        startup = establish_sami_home()
        state["startup_navigation"] = startup
        write_checkpoint(state)
        if not startup.get("ok"):
            cleanup(state, "startup_page_unverified", "启动页不是已验证银淞安全边界")
            return 4
        state["startup_rewards"] = service_expedition_records()
        write_checkpoint(state)
        if not state["startup_rewards"].get("ok"):
            cleanup(state, "startup_rewards_unverified", "启动前科考记录奖励未闭环")
            return 8
        state["startup_culture"] = service_culture()
        write_checkpoint(state)
        if not state["startup_culture"].get("ok"):
            cleanup(state, "startup_culture_unverified", "启动前文化比较未完成真实加点闭环")
            return 9

        fast_recoveries = 0
        while time.time() < deadline.timestamp() - CLEANUP_BUFFER:
            remaining = round_run_timeout(deadline)
            state.update({"status": "running", "updated_at": now_iso()})
            write_checkpoint(state)
            ok = ark.mode_roguelike(
                theme="sami",
                difficulty=2147483647,
                starts_count=1,
                max_tutorial_recoveries=2,
                core_char=core_char,
                squad=squad,
                roles=roles,
                mode="Exp",
                use_foldartal=False,
                run_timeout=remaining,
            )
            summary = dict(ark._RUN_SUMMARY.get("roguelike", {}))
            drained = drain_safe_settlement()
            session = {
                "finished_at": now_iso(),
                "maa_result": bool(ok),
                "maa_status": summary.get("status"),
                "actual_difficulty": summary.get("actual_difficulty"),
                "game_pass": bool(summary.get("game_pass")),
                "settlement_drain": drained,
            }
            state["sessions"].append(session)
            state["last_session"] = session
            write_checkpoint(state)
            if drained.get("ok"):
                session["reward_service"] = service_expedition_records()
                state["last_reward_service"] = session["reward_service"]
                write_checkpoint(state)
                if not session["reward_service"].get("ok"):
                    cleanup(state, "record_rewards_unverified", "结算后科考记录奖励未闭环")
                    return 8
                session["culture_service"] = service_culture()
                state["last_culture_service"] = session["culture_service"]
                write_checkpoint(state)
                if not session["culture_service"].get("ok"):
                    cleanup(state, "culture_upgrade_unverified", "结算后文化比较未完成真实加点闭环")
                    return 9
                fast_recoveries = 0
                time.sleep(5)
                continue

            fast_recoveries += 1
            session["technical_failure"] = True
            state["consecutive_fast_recoveries"] = fast_recoveries
            write_checkpoint(state)
            if fast_recoveries <= MAX_FAST_RECOVERIES:
                if ark._maa_task_queue_running():
                    ark._stop_maa_task_queue(timeout=45)
                ark.reload_maa_after_config_switch("银淞肉鸽技术恢复")
                if not ark.ensure_env():
                    break
                recovery_startup = establish_sami_home()
                session["recovery_navigation"] = recovery_startup
                write_checkpoint(state)
                if not recovery_startup.get("ok"):
                    cleanup(
                        state,
                        "technical_recovery_page_unverified",
                        "技术恢复后页面未确认，已保留证据并停止",
                    )
                    return 7
                time.sleep(5)
                continue

            release_environment_for_cooldown(state, "连续技术错误，完整释放环境后冷却10分钟")
            wake = min(deadline.timestamp() - CLEANUP_BUFFER, time.time() + TECHNICAL_COOLDOWN)
            while time.time() < wake:
                time.sleep(min(15, wake - time.time()))
            if time.time() >= deadline.timestamp() - CLEANUP_BUFFER:
                cleanup(state, "deadline_stopped", "到达截止时间，已释放每日自动化控制权")
                return terminal_exit_code(state)
            if not ark.ensure_env():
                cleanup(state, "environment_failed", "技术冷却后环境启动失败")
                return 5
            recovery_startup = establish_sami_home()
            state["post_cooldown_navigation"] = recovery_startup
            write_checkpoint(state)
            if not recovery_startup.get("ok"):
                cleanup(state, "startup_page_unverified", "冷却恢复后未到达银淞安全边界")
                return 4
            if not no_viewer:
                ark.start_log_viewer(
                    log_file=str(SUPERVISOR_LOG),
                    title="明日方舟银淞肉鸽运行日志",
                    status_text="银淞止境：技术冷却结束，恢复单轮探索",
                )
            state.pop("environment_released_for_cooldown", None)
            fast_recoveries = 0

        cleanup(state, "deadline_stopped", "到达截止时间，已释放每日自动化控制权")
        return terminal_exit_code(state)
    except Exception as exc:
        state["error"] = f"{type(exc).__name__}: {exc}"
        try:
            cleanup(state, "supervisor_exception", state["error"])
        except Exception as cleanup_exc:
            state["cleanup_error"] = str(cleanup_exc)
            write_checkpoint(state)
        return 6
    finally:
        ark.release_single_instance()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deadline", default="11:30")
    parser.add_argument("--core-char", default="维什戴尔")
    parser.add_argument("--squad", default="指挥分队")
    parser.add_argument("--roles", default="稳扎稳打")
    parser.add_argument("--no-viewer", action="store_true")
    # 当前项目合同要求每个真实运行先创建具名清单；只约束本监督器CLI。
    parser.add_argument("--run-manifest", required=True, help="本次已创建的精确运行清单路径")
    parser.add_argument("--run-id", required=True, help="本次精确运行身份，不按文件名或时间猜测")
    args = parser.parse_args()
    return run(next_deadline(args.deadline), args.core_char, args.squad, args.roles,
               args.no_viewer, args.run_manifest, args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
