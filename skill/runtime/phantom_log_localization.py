"""傀影肉鸽监督日志的用户可见中文翻译。

原始监督日志仍保留稳定的机器可读英文，供脚本判断和排错；本模块只负责
日志悬浮窗的显示层，不参与任何业务决策。
"""

from __future__ import annotations

import re


_STAGE_NAMES = {
    "exp": "古堡笔记经验爬塔",
    "monthly": "月度小队",
    "deep": "深入调查",
}

_RESULT_NAMES = {
    "growth_cycle_complete": "本轮探索已结算",
    "task_chain_error": "MAA任务链发生技术错误",
    "queue_already_running": "检测到已有MAA队列",
    "unexpected_stop": "MAA队列意外停止",
    "planned_settlement_pause": "已在计划结算边界暂停",
    "planned_squad_switch": "已在结算边界切换分队",
    "deadline": "已到达计划截止时间",
    "completed": "本阶段已经完成",
    "probe_confirmed": "参数验证完成",
    "candidate_squad_locked": "候选分队尚未解锁",
    "start_failed": "MAA启动失败",
    "announcement_preflight_failed": "登录公告处理失败",
}

_REASON_NAMES = {
    "queue_already_running": "检测到重复MAA队列",
    "task_chain_error": "MAA任务链技术错误",
    "unexpected_stop": "MAA队列意外停止",
    "technical_restart_limit": "技术恢复次数达到上限",
    "deadline_reached": "到达计划截止时间",
    "planned_preparation_boundary": "到达计划领奖边界",
    "probe_confirmed": "参数验证完成",
}

_STATE_NAMES = {
    "main_menu": "主页",
    "announcement": "登录公告",
    "terminal": "终端",
    "unknown": "未知界面",
}

_CLASSIFICATION_NAMES = {
    "terminal_collapse_candidate": "终局崩盘候选",
    "unknown_no_stage_evidence": "缺少关卡证据，暂不归因",
    "game_pass": "完整通关",
}


def _yes_no(value: str) -> str:
    return "是" if value == "True" else "否"


def _display_time(prefix: str) -> str:
    match = re.match(r"\[(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}:\d{2})[^]]*\]", prefix)
    if not match:
        return prefix
    return f"[{match.group(2)}-{match.group(3)} {match.group(4)}]"


def localize_phantom_log_line(line: str) -> str:
    """将一行傀影监督日志转换成中文用户摘要。"""
    match = re.match(r"^(\[[^]]+\])\s*(.*)$", line.rstrip("\n"))
    if match:
        prefix = _display_time(match.group(1))
        message = match.group(2)
    else:
        prefix = ""
        message = line.rstrip("\n")

    translated = _translate_message(message)
    return f"{prefix} {translated}".strip()


def _translate_message(message: str) -> str:
    match = re.fullmatch(
        r"(?:attached )?Core parameters confirmed: Phantom mode=(\d+) \(([^)]+)\), core=(.+)",
        message,
    )
    if match:
        stage = _STAGE_NAMES.get(match.group(2), match.group(2))
        attached = "接管现有队列并" if message.startswith("attached ") else ""
        return f"已{attached}确认MAA参数：傀影肉鸽 / {stage} / 核心干员={match.group(3)}"

    match = re.fullmatch(r"session finished: stage=([^,]+), result=(.+)", message)
    if match:
        stage = _STAGE_NAMES.get(match.group(1), match.group(1))
        result = _RESULT_NAMES.get(match.group(2), f"未分类结果（{match.group(2)}）")
        return f"本轮会话结束：{stage}；结果={result}"

    match = re.fullmatch(r"technical restart (\d+)/(\d+): (.+)", message)
    if match:
        reason = _REASON_NAMES.get(match.group(3), match.group(3))
        return f"执行技术恢复 {match.group(1)}/{match.group(2)}：{reason}"

    match = re.fullmatch(r"stop queue: reason=([^,]+), confirmed=(True|False)", message)
    if match:
        reason = _REASON_NAMES.get(match.group(1), match.group(1))
        return f"停止MAA队列：原因={reason}；停止确认={_yes_no(match.group(2))}"

    match = re.fullmatch(
        r"recorded Phantom settlement: game_pass=(True|False), terminal_stage=([^,]+), "
        r"combat_end=(True|False), classification=(.+)",
        message,
    )
    if match:
        stage = "未识别" if match.group(2) == "unknown" else match.group(2)
        classification = _CLASSIFICATION_NAMES.get(match.group(4), match.group(4))
        return (
            f"记录肉鸽结算：完整通关={_yes_no(match.group(1))}；"
            f"终局关卡={stage}；战斗结束证据={_yes_no(match.group(3))}；"
            f"分类={classification}"
        )

    match = re.fullmatch(r"high-risk Phantom stage entered; focused evidence tracking: (.+)", message)
    if match:
        return f"进入高风险关卡，开始重点采集部署与截图证据：{match.group(1)}"

    match = re.fullmatch(r"attached to existing Roguelike queue at line (\d+)", message)
    if match:
        return f"已接管正在运行的肉鸽队列（底层日志位置 {match.group(1)}）"

    match = re.fullmatch(r"Roguelike preflight closed login announcement; state=(.+)", message)
    if match:
        state = _STATE_NAMES.get(match.group(1), match.group(1))
        return f"肉鸽启动前已关闭登录公告；当前界面={state}"

    match = re.fullmatch(r"opening core (.+) unavailable; allow MAA fallback .*", message)
    if match:
        return f"本局未能招募开局核心 {match.group(1)}；按既定规则允许MAA自动替补继续，不占用技术恢复次数"

    match = re.fullmatch(
        r"Phantom reward service finished: ok=(True|False), claimed=(True|False), "
        r"preparation_skipped=(True|False)",
        message,
    )
    if match:
        return (
            f"傀影奖励检查结束：流程成功={_yes_no(match.group(1))}；"
            f"本次领取到奖励={_yes_no(match.group(2))}；"
            f"幕后筹备已满点并跳过={_yes_no(match.group(3))}"
        )

    match = re.fullmatch(r"safe settlement boundary reached; squad switch (.+) -> (.+)", message)
    if match:
        return f"已到安全结算边界：分队从“{match.group(1)}”切换为“{match.group(2)}”"

    exact = {
        "MAA Core log rotated; preserved Roguelike evidence and continued monitoring":
            "MAA底层日志已轮换；本轮证据已保留，继续监控",
        "reward evidence missing for exp; continue same stage for growth rewards":
            "本轮未发现新的古堡笔记领奖证据；继续同一路线积累经验和奖励",
        "reward evidence missing for monthly; continue same stage for growth rewards":
            "本轮未发现新的月度小队领奖证据；继续当前阶段",
        "reward evidence missing for deep; continue same stage for growth rewards":
            "本轮未发现新的深入调查领奖证据；继续当前阶段",
        "Castle Notes reward service finished at growth boundary; resume EXP farming":
            "结算边界的古堡笔记奖励检查已完成；继续经验爬塔",
        "Castle Notes reward service was not confirmed; preserve warning and resume EXP farming":
            "古堡笔记领奖尚未确认；保留警告并继续经验爬塔",
        "live MAA queue confirmed; skipped environment relaunch before attachment":
            "已确认MAA队列正在运行；直接接管监控，不重复启动环境",
        "safe settlement boundary reached; MAA stopped and game preserved for Castle Notes reward handling":
            "已到安全结算边界：MAA已停止，保留游戏用于领取古堡笔记奖励",
        "Roguelike preflight could not close the confirmed announcement":
            "肉鸽启动前无法关闭已确认的登录公告",
        "Roguelike preflight announcement remained after close action":
            "执行关闭操作后登录公告仍然存在",
        "Phantom floor-4 route guard rejected 永无尽头 and returned to scan an alternative route":
            "傀影第四层路线保护已避开“永无尽头”，正在扫描其他可达路线",
    }
    if message in exact:
        return exact[message]

    match = re.fullmatch(r"focus-stage screenshot failed without interrupting MAA: (.+)", message)
    if match:
        return "高风险关卡截图失败；未中断MAA，技术详情已保留在原始日志"

    match = re.fullmatch(r"(?:successful )?terminal cleanup failed: (.+)", message)
    if match:
        return "结束清理失败；技术详情已保留在原始日志"

    match = re.fullmatch(
        r"Castle Notes reward service failed with (.+); "
        r"preserve warning and resume EXP farming",
        message,
    )
    if match:
        return f"古堡笔记领奖发生技术异常（{match.group(1)}）；已保留警告并继续经验爬塔"

    match = re.fullmatch(
        r"technical recovery finished: reason=([^,]+), "
        r"queue_stop=(True|False), environment_ready=(True|False)",
        message,
    )
    if match:
        reason = _REASON_NAMES.get(match.group(1), match.group(1))
        return (
            f"技术恢复完成：原因={reason}；"
            f"旧队列停止确认={_yes_no(match.group(2))}；"
            f"模拟器与ADB恢复={_yes_no(match.group(3))}"
        )

    match = re.fullmatch(
        r"technical recovery limit reached; all controlled processes cleaned, "
        r"cooldown until (.+) before retrying same contract",
        message,
    )
    if match:
        return f"连续技术恢复仍失败；相关进程已清理，将在 {match.group(1)} 按原配置重试"

    if message == "technical cooldown finished; resume same Phantom contract":
        return "一小时技术冷却结束；正在按原傀影配置恢复运行"

    # 监督器未来新增英文事件时，显示层不把整段技术英文暴露给用户；
    # 原文仍完整保存在 phantom_until_deadline.log 中供诊断。
    if re.search(r"[A-Za-z]{4,}", message):
        return "其他技术事件（原始详情已保留，等待加入中文摘要）"
    return message
