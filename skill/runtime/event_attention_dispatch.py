"""注意事件（event_page_attention）待投递归并与投递回执工具。

背景：``outputs/event_page_attention/*.json`` 是项目既有的“待注意事件”出口。
写入方（``event_page_guard_v1.publish_page_attention``、``maa_window_dock_v1``
的 ``write_attention_event``）只负责写 ``delivery_status=pending``；把事件真正送回
项目对话的动作，此前只存在于每日任务的临时步骤里，既没有固定工具，也说不清
哪一条已经送达。结果是 pending 一直堆积（2026-09-16 实测 18 条积压，
最早 09-10），而“文件 pending”又容易被误读成“已经被项目知道”。

本工具只做两件可机械复核的事：

1. ``--digest``：扫描 pending，按 ``reason`` 归并成一份简报；同时写出 markdown
   正文与 json 侧车，侧车里带本次要投递的精确 ``event_id`` 列表。
2. ``--mark-delivered --from-digest <json>``：把侧车里列出、且**当前仍是 pending**
   的事件标记为 delivered，写入 ``delivered_at`` / ``delivery_thread_id`` /
   ``delivered_event_id``。改写前先把原文件备份到 ``outputs/event_attention_dispatch/backup/``，
   可逐条恢复。

它不负责发送消息：发消息仍由原生任务的 ``send_message_to_thread`` 完成，投递成功
之后才调用 ``--mark-delivered``。不新增 Automation，不碰 pending 之外的状态，
不改写事件正文。

用法::

    python event_attention_dispatch.py --status
    python event_attention_dispatch.py --digest --write
    python event_attention_dispatch.py --mark-delivered --from-digest <json> \
        --thread-id <recipient-project-thread-id>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 测试可用环境变量把读写重定向到临时目录，避免污染真实事件目录。
ATTENTION_DIR = os.environ.get("ARK_ATTENTION_DIR") or os.path.join(
    BASE_DIR, "outputs", "event_page_attention"
)
DISPATCH_DIR = os.environ.get("ARK_ATTENTION_DISPATCH_DIR") or os.path.join(
    BASE_DIR, "outputs", "event_attention_dispatch"
)

DEFAULT_PROJECT_THREAD_ID = os.environ.get("ARKNIGHTS_PROJECT_THREAD_ID", "").strip()

PENDING = "pending"
DELIVERED = "delivered"

# reason -> 人类可读类别。未命中前缀表时按前缀兜底，保证新 reason 也能归并。
REASON_LABELS = {
    "unknown_page_no_verified_progress_30s": "导航未知页（30 秒无已验证进展）",
    "unexpected_active_page": "意外页面（非预期活动页）",
    "tarot_close_not_located": "塔罗覆盖层未定位到关闭点",
    "tarot_confirm_unchanged": "塔罗确认后画面未变化",
    "tarot_sequence_limit": "塔罗处理次数达到上限",
    "adb_swipe_rejected": "输入注入被拒绝（ADB swipe）",
    "formation_recovery_detail_unverified": "编队恢复详情未验证",
    "post_battle_detail_unverified": "战后详情未验证",
    "event_signin_today_card_not_located": "签到页今日卡片未定位",
    "infrast_product_mismatch": "MAA：产物与配置不相符",
    "copilot_job_error": "MAA：作业文件/作业选择出错",
    "file_read_failed": "MAA：读取文件失败",
    "operator_unavailable": "MAA：干员不可用",
    "formation_operator_missing": "MAA：干员组内干员均未拥有",
    "unsupported_level": "MAA：不支持的关卡",
    "task_error": "MAA：任务出错",
    "battle_error": "MAA：战斗出错",
    "taskchain_error": "MAA：任务链失败",
    "subtask_error": "MAA：子任务失败",
    "connection_error": "MAA：连接失败",
    "resource_update_error": "MAA：资源更新/加载失败",
    "resource_error": "MAA：资源校验失败",
    "autostart_error": "MAA：开机自启设置失败",
}

REASON_PREFIX_LABELS = (
    ("event_signin_", "签到页"),
    ("tarot_", "塔罗覆盖层"),
    ("sss_", "保全派驻"),
)


def label_for(reason: str) -> str:
    reason = str(reason or "")
    if reason in REASON_LABELS:
        return REASON_LABELS[reason]
    for prefix, label in REASON_PREFIX_LABELS:
        if reason.startswith(prefix):
            return f"{label}（{reason}）"
    return reason or "（reason 缺失）"


def read_events(folder: str) -> tuple[list[dict], list[str]]:
    """读取事件目录。返回 (可解析事件, 不可解析文件名)。"""
    events: list[dict] = []
    broken: list[str] = []
    if not os.path.isdir(folder):
        return events, broken
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            broken.append(name)
            continue
        if not isinstance(payload, dict):
            broken.append(name)
            continue
        payload.setdefault("event_id", name[: -len(".json")])
        events.append({"path": path, "name": name, "payload": payload})
    return events, broken


def event_sort_key(event: dict) -> str:
    payload = event["payload"]
    return str(payload.get("created_at") or payload.get("run_key") or event["name"])


def select_pending(events: list[dict]) -> list[dict]:
    """只挑仍是 pending 的事件；已投递/其他状态一律不重复投递。"""
    return [
        event
        for event in events
        if str(event["payload"].get("delivery_status") or "") == PENDING
    ]


def _first_observation(payload: dict) -> str:
    for observation in payload.get("observations") or []:
        if not isinstance(observation, dict):
            continue
        for field in ("text", "ocr", "code", "state"):
            value = observation.get(field)
            if value:
                text = " ".join(str(value).split())
                return text[:80]
    return ""


def group_events(events: list[dict]) -> list[dict]:
    """按 reason 归并，保持组内时间顺序，组间按最早时间排序。"""
    buckets: dict[str, dict] = {}
    for event in events:
        payload = event["payload"]
        reason = str(payload.get("reason") or "(missing_reason)")
        bucket = buckets.setdefault(
            reason, {"reason": reason, "label": label_for(reason), "items": []}
        )
        bucket["items"].append(event)
    groups = sorted(buckets.values(), key=lambda bucket: event_sort_key(bucket["items"][0]))
    for bucket in groups:
        bucket["items"].sort(key=event_sort_key)
    return groups


def build_digest(events: list[dict], thread_id: str, generated_at: str) -> dict:
    groups = group_events(events)
    event_ids = [event["payload"]["event_id"] for event in sorted(events, key=event_sort_key)]
    lines = [
        "# 注意事件待投递简报（自动生成）",
        "",
        f"- 生成时间：{generated_at}",
        f"- 待投递：{len(events)} 条（{len(groups)} 类）",
        f"- 拟投递到：`{thread_id}`",
        f"- 事件目录：`{ATTENTION_DIR}`",
        "- 说明：这些是历史上只写进 `outputs/event_page_attention/` 但从未回传项目的条目；"
        "投递成功后才由 `--mark-delivered` 标为 delivered。",
        "",
    ]
    for index, bucket in enumerate(groups, start=1):
        items = bucket["items"]
        first, last = items[0], items[-1]
        lines.append(f"## {index}. {bucket['label']} × {len(items)}")
        lines.append("")
        lines.append(
            f"- 时间范围：{first['payload'].get('created_at', '?')} → "
            f"{last['payload'].get('created_at', '?')}"
        )
        sources = sorted({str(item["payload"].get("source") or "?") for item in items})
        lines.append(f"- 来源：{', '.join(sources)}")
        ids = [item["payload"]["event_id"] for item in items]
        lines.append(f"- 事件 ID（{len(ids)}）：{', '.join(ids)}")
        for item in items[-3:]:
            note = _first_observation(item["payload"])
            stamp = str(item["payload"].get("created_at") or "?")[:19]
            status = str(item["payload"].get("status") or "?")
            suffix = f"｜观察：{note}" if note else ""
            lines.append(
                f"  - {stamp} `{item['payload']['event_id']}` status={status}{suffix}"
            )
        if len(items) > 3:
            lines.append(f"  - （另有 {len(items) - 3} 条较早同类记录，详见 JSON 侧车）")
        lines.append("")
    markdown = "\n".join(lines).rstrip() + "\n"
    payload = {
        "schema_version": 1,
        "generated_at": generated_at,
        "attention_dir": ATTENTION_DIR,
        "target_thread_id": thread_id,
        "pending_count": len(events),
        "group_count": len(groups),
        "event_ids": event_ids,
        "groups": [
            {
                "reason": bucket["reason"],
                "label": bucket["label"],
                "count": len(bucket["items"]),
                "event_ids": [item["payload"]["event_id"] for item in bucket["items"]],
                "files": [item["name"] for item in bucket["items"]],
            }
            for bucket in groups
        ],
    }
    return {"markdown": markdown, "payload": payload}


def write_digest(out_dir: str, digest: dict) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    md_path = os.path.join(out_dir, f"digest-{stamp}.md")
    json_path = os.path.join(out_dir, f"digest-{stamp}.json")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(digest["markdown"])
    payload = dict(digest["payload"])
    payload["markdown_path"] = md_path
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return {"markdown_path": md_path, "json_path": json_path}


def _backup_dir(out_dir: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(out_dir, "backup", stamp)


def mark_delivered(
    folder: str,
    event_ids: list[str],
    thread_id: str,
    out_dir: str,
    digest_path: str | None = None,
    dry_run: bool = False,
) -> dict:
    """把仍为 pending 的事件标记为 delivered。返回明细，便于逐条复核。"""
    wanted = {str(event_id) for event_id in event_ids}
    events, _ = read_events(folder)
    result = {
        "requested": len(wanted),
        "marked": [],
        "already_delivered": [],
        "not_pending": [],
        "missing": [],
        "backup_dir": None,
    }
    found: dict[str, dict] = {}
    for event in events:
        event_id = event["payload"]["event_id"]
        if event_id in wanted:
            found[event_id] = event
    result["missing"] = sorted(wanted - set(found))

    backup = None
    delivered_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for event_id in sorted(wanted & set(found)):
        event = found[event_id]
        payload = event["payload"]
        status = str(payload.get("delivery_status") or "")
        if status == DELIVERED:
            result["already_delivered"].append(event_id)
            continue
        if status != PENDING:
            result["not_pending"].append({"event_id": event_id, "delivery_status": status})
            continue
        payload["delivery_status"] = DELIVERED
        payload["delivered_at"] = delivered_at
        payload["delivery_thread_id"] = thread_id
        payload["delivered_event_id"] = event_id
        if digest_path:
            payload["delivered_digest"] = digest_path
        if dry_run:
            result["marked"].append(event_id)
            continue
        if backup is None:
            backup = _backup_dir(out_dir)
            os.makedirs(backup, exist_ok=True)
            result["backup_dir"] = backup
        shutil.copy2(event["path"], os.path.join(backup, event["name"]))
        tmp = event["path"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, event["path"])
        result["marked"].append(event_id)
    return result


def status(folder: str) -> dict:
    events, broken = read_events(folder)
    counts = {"pending": 0, DELIVERED: 0}
    other = []
    for event in events:
        value = str(event["payload"].get("delivery_status") or "")
        if value in counts:
            counts[value] += 1
        else:
            other.append({"event_id": event["payload"]["event_id"], "delivery_status": value})
    pending_ids = [
        event["payload"]["event_id"]
        for event in sorted(events, key=event_sort_key)
        if str(event["payload"].get("delivery_status") or "") == PENDING
    ]
    return {
        "attention_dir": folder,
        "total": len(events),
        "pending": counts[PENDING],
        "delivered": counts[DELIVERED],
        "other_status": other,
        "broken_files": broken,
        "pending_event_ids": pending_ids,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="注意事件待投递归并与投递回执")
    parser.add_argument("--attention-dir", default=ATTENTION_DIR, help="事件目录")
    parser.add_argument("--out-dir", default=DISPATCH_DIR, help="简报与备份目录")
    parser.add_argument("--status", action="store_true", help="只统计 pending/delivered")
    parser.add_argument("--digest", action="store_true", help="生成待投递简报")
    parser.add_argument("--write", action="store_true", help="把简报落盘（默认只打印）")
    parser.add_argument("--mark-delivered", action="store_true", help="标记投递完成")
    parser.add_argument("--from-digest", help="从简报 JSON 侧车读取 event_id 列表")
    parser.add_argument("--event-id", action="append", default=[], help="显式指定 event_id，可重复")
    parser.add_argument("--thread-id", default=DEFAULT_PROJECT_THREAD_ID, help="投递目标任务 ID")
    parser.add_argument("--dry-run", action="store_true", help="只报告将要做的改动")
    args = parser.parse_args(argv)
    if (args.digest or args.mark_delivered) and not args.thread_id:
        parser.error("set --thread-id or ARKNIGHTS_PROJECT_THREAD_ID to your own project chat")

    if args.status:
        print(json.dumps(status(args.attention_dir), ensure_ascii=False, indent=2))
        return 0

    if args.digest:
        events, broken = read_events(args.attention_dir)
        pending = select_pending(events)
        generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        digest = build_digest(pending, args.thread_id, generated_at)
        if broken:
            print(f"警告：{len(broken)} 个文件无法解析：{', '.join(broken)}", file=sys.stderr)
        if args.write:
            paths = write_digest(args.out_dir, digest)
            print(json.dumps(paths, ensure_ascii=False, indent=2))
        else:
            print(digest["markdown"])
        return 0

    if args.mark_delivered:
        event_ids = list(args.event_id)
        digest_path = args.from_digest
        if digest_path:
            with open(digest_path, "r", encoding="utf-8") as handle:
                event_ids.extend(json.load(handle).get("event_ids") or [])
        if not event_ids:
            print("没有要标记的事件：请给出 --from-digest 或 --event-id", file=sys.stderr)
            return 2
        result = mark_delivered(
            args.attention_dir, event_ids, args.thread_id, args.out_dir,
            digest_path=digest_path, dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result["missing"] else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
