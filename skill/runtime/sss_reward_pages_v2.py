"""保全奖励服务V2：用一键领取闭环会消失的周期清理记录卡片。"""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

import sss_reward_pages_v1 as v1


def _token(text):
    return re.sub(r"\s+", "", str(text))


def _record_header(items):
    text = " ".join(str(t) for t, _, _ in items or [])
    return "所有已完成的奖励" in text and "COMPLETED" in text.upper()


def _one_click(items):
    return next(
        ((x, y) for t, x, y in items or [] if _token(t) in {"一键领取", "全部领取"}),
        None,
    )


def _individual_claim_rows(items):
    return [
        (t, x, y)
        for t, x, y in items or []
        if _token(t) in {"领取", "领取奖励", "领取报酬"}
        and 1300 < x < 1650
        and 250 < y < 1000
    ]


def _record_rows(items):
    """兼容实机的一键领取后大号 COMPLETED 覆盖层。

    V1 只在右侧窄按钮列寻找状态；实机领取后的白色 COMPLETED 会横跨
    每张记录卡中部，中心可能落在 x=1100..1300。阶段说明仍是稳定锚点，
    因此只在同一阶段行附近放宽横坐标，且明确排除 UNCOMPLETED。
    """
    rows = v1.record_rows(items)
    for text, x, y in items or []:
        match = re.search(r"单次作战清理进度达到第([1-6])阶段", str(text))
        if not match or not (250 < x < 1100 and 150 < y < 1000):
            continue
        for status, sx, sy in items or []:
            token = _token(status).upper()
            if (
                re.fullmatch(r"[A-Z]?COMPLETED", token)
                and "UNCOMPLETED" not in token
                and 1000 < sx < 1800
                and abs(sy - y) < 90
            ):
                rows[int(match.group(1))] = {
                    "state": "completed",
                    "position": [sx, sy],
                }
                break
    return rows


def _orange_claim_cards(path):
    """返回任务页上橙色高亮的“整卡可领取”矩形。

    #12 实机并不总显示“领取”文字：已达成未领取的任务会让整张卡的边框、
    进度条和底部奖励栏连成一块橙色大区域；已领取卡只有若干分离的小橙块。
    这里只接受完整位于画面内、尺寸接近任务卡的大连通域。
    """
    import cv2
    import numpy as np
    from PIL import Image

    with Image.open(Path(path)) as image:
        rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    mask = (
        (rgb[:, :, 0] > 180)
        & (rgb[:, :, 1] > 55)
        & (rgb[:, :, 1] < 180)
        & (rgb[:, :, 2] < 90)
    ).astype("uint8")
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    cards = []
    for x, y, box_width, box_height, pixels in stats[1:count]:
        if not (
            0.20 * width < box_width < 0.32 * width
            and 0.45 * height < box_height < 0.70 * height
            and 0.10 * height < y < 0.35 * height
            and pixels > 0.006 * width * height
            and x > 25
            and x + box_width < width - 25
        ):
            continue
        cards.append(
            {
                "bounds": [int(x), int(y), int(x + box_width), int(y + box_height)],
                "position": [int(x + box_width / 2), int(y + box_height / 2)],
                "orange_pixels": int(pixels),
            }
        )
    return sorted(cards, key=lambda card: card["bounds"][0])


def _same_visual_card(before, after):
    left, _, right, _ = before["bounds"]
    return any(
        abs(card["bounds"][0] - left) < 80
        and abs(card["bounds"][2] - right) < 80
        for card in after
    )


def _task_fraction(app, path, items):
    """读取任务进度；保留V1路径，并修复8/8在拉伸裁剪中漏掉首位数字。"""
    value = v1.task_fraction(app, path, items)
    if value is not None:
        return value

    import cv2
    import numpy as np
    from PIL import Image

    with Image.open(Path(path)) as image:
        width, height = image.size
        crop = image.convert("RGB").crop(
            (
                int(1740 * width / 1920),
                int(980 * height / 1080),
                int(1895 * width / 1920),
                int(1065 * height / 1080),
            )
        )
    image_array = np.asarray(crop)[:, :, ::-1].copy()
    image_array = cv2.resize(image_array, None, fx=3, fy=3)
    rows, _ = app._ocr_engine.text_recognizer(image_array)
    for text, score in rows or []:
        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})", _token(text))
        if match and score >= 0.65:
            completed, total = int(match.group(1)), int(match.group(2))
            if total > 0 and 0 <= completed <= total:
                return completed, total
    return None


def scan_tasks(app):
    """领取文字按钮和橙色整卡两种周期任务，最后完整横向复核。"""
    out = {
        "verified": False,
        "claimable": None,
        "incomplete": None,
        "cards": [],
        "evidence": [],
        "claims": [],
    }
    path = app.shot("sss_tasks_v2_start")
    items = app.ocr(path)
    if not any("当前任务进度" in text for text, _, _ in items):
        out["reason"] = "task_page_unverified"
        return out

    for _ in range(7):
        app.swipe(650, 760, 1350, 760, 900)
        app.wait(2)
        next_path = app.shot("sss_tasks_v2_reset")
        if v1.visually_still(path, next_path, (60, 470, 1870, 850)):
            path = next_path
            break
        path = next_path
    else:
        out["reason"] = "task_left_edge_unverified"
        return out

    stable = 0
    for index in range(16):
        path = app.shot(f"sss_tasks_v2_audit_{index}")
        items = app.ocr(path)
        out["evidence"].append(path)
        if not any("当前任务进度" in text for text, _, _ in items):
            out["reason"] = "task_page_lost"
            return out
        progress = _task_fraction(app, path, items)
        if progress is not None:
            out["progress"] = {"completed": progress[0], "total": progress[1]}
            out["incomplete"] = progress[1] - progress[0]

        visual_cards = _orange_claim_cards(path)
        if visual_cards:
            if progress is None:
                out["reason"] = "visual_claim_progress_unreadable"
                return out
            target = visual_cards[0]
            app.tap(*target["position"])
            app.wait(2)
            app._drain_reward_sequence()
            after_path = app.shot("sss_task_v2_visual_claim_verify")
            after_items = app.ocr(after_path)
            after_progress = _task_fraction(app, after_path, after_items)
            after_visual = _orange_claim_cards(after_path)
            out["evidence"].append(after_path)
            if (
                after_progress is None
                or after_progress[1] != progress[1]
                or after_progress[0] != progress[0] + 1
                or _same_visual_card(target, after_visual)
            ):
                out["reason"] = "visual_task_claim_unverified"
                return out
            out["claims"].append(
                {
                    "method": "orange_card",
                    "before_progress": list(progress),
                    "after_progress": list(after_progress),
                    "position": target["position"],
                    "before": path,
                    "after": after_path,
                }
            )
            out["progress"] = {
                "completed": after_progress[0],
                "total": after_progress[1],
            }
            out["incomplete"] = after_progress[1] - after_progress[0]
            stable = 0
            continue

        out["cards"].extend(v1.task_cards(items))
        buttons = [
            row
            for row in v1.task_rows(items)["buttons"]
            if 100 < row[1] < 1880 and 250 < row[2] < 900
        ]
        if buttons:
            _, x, y = buttons[0]
            card = next(
                (
                    candidate
                    for candidate in v1.task_cards(items)
                    if candidate["bounds"][0] < x < candidate["bounds"][1]
                ),
                None,
            )
            if card is None:
                out["reason"] = "claim_card_unlocated"
                return out
            app.tap(x, y)
            app.wait(2)
            app._drain_reward_sequence()
            after_path = app.shot("sss_task_v2_text_claim_verify")
            after_items = app.ocr(after_path)
            if not v1.same_task_claimed(card, v1.task_cards(after_items)):
                out["reason"] = "task_claim_unverified"
                out["evidence"].append(after_path)
                return out
            out["claims"].append({"method": "text_button", "before": path, "after": after_path})
            stable = 0
            continue

        app.swipe(1450, 760, 750, 760, 900)
        app.wait(2)
        next_path = app.shot("sss_tasks_v2_next")
        stable = stable + 1 if v1.visually_still(path, next_path, (60, 470, 1870, 850)) else 0
        if stable >= 2:
            out.update(
                verified=out["incomplete"] is not None,
                claimable=0,
                reason="full_task_list_scanned",
            )
            return out
    out["reason"] = "task_scan_budget_exhausted"
    return out


def scan_records(app):
    """领取区域周期记录；按钮语义和领取后消失共同构成直接证据。"""
    out = {"verified": False, "claimable": None, "rows": {}, "evidence": [], "claims": []}
    for index in range(10):
        path = app.shot(f"sss_record_v2_audit_{index}")
        items = app.ocr(path)
        out["evidence"].append(path)
        rows = _record_rows(items)
        for stage, row in rows.items():
            if out["rows"].get(stage, {}).get("state") != "claimed":
                out["rows"][stage] = row

        pending = [(stage, row) for stage, row in rows.items() if row["state"] == "claimable"]
        one_click = _one_click(items)
        if pending and one_click:
            before_stages = sorted(stage for stage, _ in pending)
            app.tap(*one_click)
            app.wait(2)
            app._drain_reward_sequence()
            after_path = app.shot("sss_record_v2_claim_all_verify")
            after_items = app.ocr(after_path)
            out["evidence"].append(after_path)
            after_rows = _record_rows(after_items)
            # 实机有两种已观测结果：旧界面删除可领卡片；当前界面保留阶段卡，
            # 并覆盖大号 COMPLETED。两者都必须同时满足“领取按钮已消失”，
            # 且由同页标题或至少一个带阶段锚点的 COMPLETED 行证明仍在记录页。
            if (
                _individual_claim_rows(after_items)
                or (not _record_header(after_items) and not after_rows)
                or any(row.get("state") == "claimable" for row in after_rows.values())
            ):
                out["reason"] = "record_claim_all_unverified"
                return out
            out["claims"].append(
                {
                    "method": "one_click",
                    "visible_stages_before": before_stages,
                    "before": path,
                    "after": after_path,
                }
            )
            if not after_rows:
                for stage in range(1, 7):
                    out["rows"][stage] = {"state": "claimed", "position": None}
                out.update(
                    verified=True,
                    claimable=0,
                    reason="one_click_claimed_and_cards_disappeared",
                )
                return out
            for stage, row in after_rows.items():
                out["rows"][stage] = row
            # 不凭首屏几个 COMPLETED 推断六阶段全领；继续滚动直到1..6均有
            # 已完成证据，或达到扫描预算停止留证。
            continue

        if not rows:
            if _record_header(items) and not _individual_claim_rows(items):
                out.update(verified=True, claimable=0, reason="record_page_empty_no_claimable")
                return out
            out["reason"] = "record_page_unverified"
            return out

        if set(out["rows"]) == set(range(1, 7)) and not pending:
            if not any(row.get("state") == "incomplete" for row in out["rows"].values()):
                out.update(verified=True, claimable=0, reason="all_six_records_checked")
                return out

        app.swipe(1000, 850, 1000, 450, 900)
        app.wait(2)
    out["reason"] = "record_scan_budget_exhausted"
    return out


def service(app, regions, completed_audit=None):
    """沿用V1任务扫描，只替换区域记录领取与验证。"""
    from sss_cycle_service_v1 import summarize

    out = deepcopy(completed_audit) if completed_audit else {"tasks": {}, "records": {}}
    out["home_verified"] = False
    if not app.goto_sss_page():
        out["reason"] = "sss_home_unverified"
        return out
    path = app.shot("sss_service_v2_home")
    items = app.ocr(path)
    buttons = [(x, y) for t, x, y in items if t == "周期任务" and x > 1300]
    if len(buttons) != 1:
        out["reason"] = "tasks_entry_unverified"
        return out
    if not out["tasks"].get("verified"):
        app.tap(*buttons[0])
        app.wait(3)
        out["tasks"] = scan_tasks(app)
        if out["tasks"]["verified"]:
            app.back()
            app.wait(2)
    if not out["tasks"].get("verified"):
        out["reason"] = out["tasks"].get("reason")
        return out

    for name in regions:
        if out["records"].get(name, {}).get("verified"):
            continue
        if not app.goto_sss_page() or not app.select_sss_region(name):
            out["reason"] = "region_entry_unverified:" + name
            return out
        path = app.shot("sss_service_v2_region")
        items = app.ocr(path)
        record_buttons = [(x, y) for t, x, y in items if t == "周期清理记录"]
        if len(record_buttons) != 1:
            out["reason"] = "record_entry_unverified:" + name
            return out
        app.tap(*record_buttons[0])
        app.wait(2)
        out["records"][name] = scan_records(app)
        if not out["records"][name]["verified"]:
            out["reason"] = out["records"][name].get("reason")
            return out
        app.back()
        app.wait(2)

    out["home_verified"] = app.goto_sss_page()
    if out["home_verified"]:
        path = app.shot("sss_service_v2_final_counts")
        out["counts"] = app.read_sss_reward_counts_from_image(path)
        out.update(summarize(out["counts"], out["tasks"], out["records"], regions))
        out.pop("reason", None)
    return out
