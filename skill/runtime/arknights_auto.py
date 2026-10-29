"""
明日方舟全场景自动化引擎 v3.0 (Universal Edition)
==================================================
统一管理: 日常任务 / 主线推进 / 活动刷取 / 剿灭 / 肉鸽 / 资源关
任何场景都能自动处理, 无需修改代码。

场景模式:
  --mode daily       每日日常(StartUp+Infrast+Recruit+Mall+Award)
  --mode mainline    主线推进(从当前进度开始, 磨难优先)
  --mode annihilation 每周剿灭闭环(未到上限则优先)
  --mode resource    资源关刷取(AP-5/LS-6/SK-5/CE-6/PR-x)
  --mode event       活动刷取(自动检测当前活动)
  --mode roguelike   肉鸽(指定主题)
  --mode reclamation 生息演算-沙洲遗闻(按预算轮数无存档刷繁荣点)
  --mode full        完整流程: 每周剿灭→活动优先/主线→日常收尾

用法:
  python arknights_auto.py --mode daily
  python arknights_auto.py --mode mainline
  python arknights_auto.py --mode full
  python arknights_auto.py --mode resource --stage AP-5 --times 5
  python arknights_auto.py --mode event --stage act24side_01 --times 10

作者: WorkBuddy 自动化   日期: 2026-06-27
"""
from portable_paths import resolve_path as _portable_path

import argparse, subprocess, time, json, os, re, urllib.request, urllib.parse, sys, hashlib, random
import shutil, tempfile, zipfile
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from maacore_screenshot import MaaCoreScreenshotBridge

# ============================================================
# 环境配置
# ============================================================

ADB = _portable_path('mumu', 'shell/adb.exe')
MUMU_CLI = _portable_path('mumu', 'nx_main/mumu-cli.exe')
MUMU_PLAYER = _portable_path('mumu', 'nx_main/MuMuNxMain.exe')
MUMU_INSTALL_ROOT = os.path.dirname(os.path.dirname(MUMU_PLAYER))
DEVICE = os.environ.get("ARKNIGHTS_DEVICE", "127.0.0.1:0").strip() or "127.0.0.1:0"  # 默认端口, ensure_env会自动检测实际端口
PKG = os.environ.get("ARKNIGHTS_GAME_PACKAGE", "").strip()
MAA_PATH = _portable_path('maa', 'MAA.exe')
MAA_CONFIG = _portable_path('maa', 'config')
MAA_LOG = _portable_path('maa', 'debug/asst.log')
MAA_GUI_LOG = _portable_path('maa', 'debug/gui.log')
MAA_ROOT = os.path.dirname(MAA_PATH)
MAA_STAGE_ACTIVITY_CACHE = os.path.join(MAA_ROOT, "cache", "gui", "StageActivityV2.json")
MAA_DEPOT_CACHE = os.path.join(MAA_ROOT, "data", "DepotData.json")
MAA_ITEM_INDEX = os.path.join(MAA_ROOT, "resource", "item_index.json")
MUMU_VM_INDEX = os.environ.get("ARK_MUMU_VM_INDEX", "0").strip() or "0"
ENABLE_MAA_MUMU_SCREENSHOT_ENHANCEMENT = (
    os.environ.get("ARK_MAA_MUMU_SCREENSHOT_ENHANCEMENT", "1").strip() != "0"
)

def _resolve_script_dir():
    """Recover the real Unicode project path when a launcher mangles argv/cwd."""
    raw = os.path.dirname(os.path.abspath(__file__))
    explicit = os.environ.get("ARKNIGHTS_AUTO_PROJECT_ROOT", "").strip()
    if explicit and os.path.isfile(os.path.join(explicit, "arknights_auto.py")):
        return os.path.abspath(explicit)
    if "\ufffd" not in raw and os.path.isfile(os.path.join(raw, "arknights_auto.py")):
        return raw
    documents = os.path.join(os.path.expanduser("~"), "Documents")
    try:
        for entry in os.scandir(documents):
            if not entry.is_dir(follow_symlinks=False):
                continue
            candidate = os.path.join(entry.path, "arknights_auto_0712")
            if os.path.isfile(os.path.join(candidate, "arknights_auto.py")):
                return os.path.abspath(candidate)
    except OSError:
        pass
    return raw


SCRIPT_DIR = _resolve_script_dir()
DYNAMIC_333_CONFIG = os.path.join(SCRIPT_DIR, "config", "base_orundum_333_dynamic_v1.json")
LOCAL_RUNTIME_DEPS = os.path.join(SCRIPT_DIR, ".runtime_deps")
LOCAL_RUNTIME_PYTHON = (3, 12)
if (
    os.path.isdir(LOCAL_RUNTIME_DEPS)
    and sys.version_info[:2] == LOCAL_RUNTIME_PYTHON
    and LOCAL_RUNTIME_DEPS not in sys.path
):
    # Codex/WorkBuddy may launch the project with different Python interpreters.
    # This private runtime contains CPython 3.12 native wheels. Loading it from
    # WorkBuddy's Python 3.13 shadows that interpreter's valid NumPy/OpenCV with
    # incompatible binaries, so only prepend it for the matching interpreter.
    sys.path.insert(0, LOCAL_RUNTIME_DEPS)
PROJECT_CONTRACT_FILE = os.path.join(SCRIPT_DIR, "PROJECT_CONTRACT.json")
# The Codex project directory is the single runtime authority.  Tests and
# deliberately isolated runs may still override it explicitly, but the
# presence of an old WorkBuddy copy must never redirect a normal run.
BASE = os.environ.get("ARKNIGHTS_AUTO_BASE", SCRIPT_DIR)
OUTPUT_DIR = os.path.join(BASE, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)
# outputs 曾继承异常 ACL；小型运行态数据使用独立目录，避免提示/调度因
# 报告目录被旧查看器或历史权限占用而失效。
RUNTIME_STATE_DIR = os.path.join(BASE, "runtime_state")
os.makedirs(RUNTIME_STATE_DIR, exist_ok=True)
COPILOT_DIR = os.path.join(BASE, "outputs", "copilot_ops_full")
INDEXED_COPILOT_DIR = os.path.join(BASE, "outputs", "copilot_ops")
BUNDLED_COPILOT_DIR = os.path.join(SCRIPT_DIR, "copilot_jobs")
# 用户2026-08-17要求：作业作者写入的技能等级/模组是建议门槛，先交给
# 真实自动编队和战斗验证；只有缺少干员或实际战败才阻断。设为1可恢复
# MAA原生严格前置检查，便于随时回滚。
RELAX_COPILOT_SKILL_MODULE_REQUIREMENTS = (
    os.environ.get("ARK_COPILOT_STRICT_REQUIREMENTS", "0").strip() != "1"
)
PROGRESS_FILE = os.path.join(BASE, "outputs", "主线通关进度.json")
EVENT_PROGRESS_FILE = os.path.join(BASE, "outputs", "活动通关进度.json")
ANNIHILATION_PROGRESS_FILE = os.path.join(BASE, "outputs", "剿灭周进度.json")
# `outputs/nav_debug` is retained as historical evidence only.  Both it and
# its `outputs` parent have inherited stale sandbox/account ACL entries after
# an elevated 100-GiB cleanup.  Use a fresh root-level bounded cache so a live
# runner never blocks on the legacy evidence tree.
LEGACY_SCREEN_DIR = os.path.join(BASE, "outputs", "nav_debug")
SCREEN_DIR = os.path.join(BASE, "runtime_screenshots")
LOG_FILE = os.path.join(BASE, "outputs", "auto_run.log")
STATUS_FILE = os.path.join(BASE, "outputs", "status.txt")
FIGHT_HANDOFF_FILE = os.path.join(BASE, "outputs", "fight_handoff.json")
MAINLINE_HANDOFF_FILE = os.path.join(BASE, "outputs", "mainline_handoff.json")
RECLAMATION_OWNERSHIP_FILE = os.path.join(
    BASE, "outputs", "reclamation_owned_save.json"
)
LONG_TERM_HANDOFF_FILE = os.path.join(
    BASE, "outputs", "long_term_terminal_handoff.json"
)
os.makedirs(SCREEN_DIR, exist_ok=True)

# runtime_screenshots 只保存可复核的近期截图。旧实现曾在 nav_debug 中
# 永久累积每次 OCR/状态识别的
# 1920x1080 PNG，实测已增长到 60,025 张 / 106.49 GB；这会同时放大
# 磁盘写入、系统文件缓存、杀毒扫描与目录枚举压力，长跑时表现为整机卡死。
# 两道上限取更严格者，并允许测试/特殊审计临时通过环境变量调整。
NAV_DEBUG_MAX_FILES = max(100, int(os.environ.get("ARK_NAV_DEBUG_MAX_FILES", "800")))
NAV_DEBUG_MAX_BYTES = max(
    256 * 1024 * 1024,
    int(os.environ.get("ARK_NAV_DEBUG_MAX_BYTES", str(2 * 1024 * 1024 * 1024))),
)
NAV_DEBUG_PRUNE_EVERY = max(10, int(os.environ.get("ARK_NAV_DEBUG_PRUNE_EVERY", "50")))
_SHOT_COUNT = 0
SCRIPT_SCREENSHOT_BACKEND = os.environ.get(
    "ARK_SCRIPT_SCREENSHOT_BACKEND", "maacore"
).strip().lower()
_MAACORE_SCREENSHOT_BRIDGE = None
_MAACORE_SCREENSHOT_FALLBACK_WARNED = False


def _prune_nav_debug(force=False):
    """清理自动生成的旧截图；保留最新证据且不触碰目录外文件。"""
    try:
        entries = []
        for entry in os.scandir(SCREEN_DIR):
            if not entry.is_file(follow_symlinks=False) or not entry.name.lower().endswith(".png"):
                continue
            stat = entry.stat(follow_symlinks=False)
            entries.append((stat.st_mtime_ns, stat.st_size, entry.path))
        entries.sort(reverse=True)

        kept_count = 0
        kept_bytes = 0
        removed_count = 0
        removed_bytes = 0
        for _mtime, size, path in entries:
            if kept_count < NAV_DEBUG_MAX_FILES and kept_bytes + size <= NAV_DEBUG_MAX_BYTES:
                kept_count += 1
                kept_bytes += size
                continue
            try:
                os.remove(path)
                removed_count += 1
                removed_bytes += size
            except OSError:
                continue
        if removed_count and force:
            log(
                "  [截图缓存] 已清理旧图"
                f" {removed_count} 张/{removed_bytes / (1024 ** 3):.2f}GB，"
                f"保留 {kept_count} 张/{kept_bytes / (1024 ** 3):.2f}GB"
            )
        return {
            "removed_count": removed_count,
            "removed_bytes": removed_bytes,
            "kept_count": kept_count,
            "kept_bytes": kept_bytes,
        }
    except OSError as exc:
        if force:
            log(f"  [截图缓存] 清理失败但不阻断任务: {exc}", "WARN")
        return None

def write_status(step, detail=""):
    """写实时状态到status.txt, 用户可随时查看"""
    ts = datetime.now().strftime("%H:%M:%S")
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        f.write(f"[{ts}] {step}\n")
        if detail:
            f.write(f"  {detail}\n")

# 🔔 手机推送: PushPlus (微信推送, 免费 token 即可)
# 获取: https://www.pushplus.plus/ → 登录 → 一对一推送 → 复制token填下面
# 留空 = 不推送
PUSHPLUS_TOKEN = ""

# 🔴 2026-06-29 全局记录本次MAA run的日志起始行 (generate_daily_report只解析本次run)
_LAST_MAA_RUN_START_LINE = 0
# MAA启动时可能轮换/截断asst.log。只保存旧行号会让等待器看到完成、最终报告却读到空文本。
# 因此等待期间持续保存本轮日志快照，报告和截图核验统一优先使用这份直接证据。
_LAST_MAA_RUN_LOG = ""
# wait_maa_complete 当前正在观察的单个 asst.log 文件片段。MAA 会在长时间
# Infrast 中把 asst.log 轮转到 asst.bak.log；必须把轮转前后的片段拼接，
# 不能因新文件出现 AllTasksCompleted 就覆盖掉早先 StartUp/Infrast 证据。
_LAST_MAA_RUN_SEGMENT = ""
# 本进程证据窗从脚本启动即建立，而不是等到第一次点击MAA Start。这样即便
# 更新/环境检查在队列启动前失败，日报也不会把累计asst.log当成本次运行。
_CURRENT_RUN_STARTED_AT = None
_CURRENT_RUN_EVIDENCE_BOUNDARY_READY = False
# MAA单个Core日志可轮转到约64MiB。等待器只需要任务链终态、理智、掉落、
# 作业错误和长期模式结算等结构化证据，不应每30秒把整份日志复制成多份大字符串。
# 完整原文仍由MAA磁盘日志保留；内存快照保留最早边界、全部命中证据和最近尾部，
# 并受字符上限约束。环境变量仅用于离线压力测试或临时诊断。
MAA_LOG_MEMORY_MAX_CHARS = max(
    512 * 1024,
    int(os.environ.get("ARK_MAA_LOG_MEMORY_MAX_CHARS", str(4 * 1024 * 1024))),
)
MAA_LOG_EVIDENCE_TAIL_LINES = max(
    200,
    int(os.environ.get("ARK_MAA_LOG_EVIDENCE_TAIL_LINES", "800")),
)
MAA_LOG_ROTATION_FALLBACK_LINES = max(
    MAA_LOG_EVIDENCE_TAIL_LINES,
    int(os.environ.get("ARK_MAA_LOG_ROTATION_FALLBACK_LINES", "2000")),
)
_MAA_LOG_EVIDENCE_MARKERS = (
    "TaskChain", "AllTasksCompleted", "append_task", '"taskchain"',
    "Current Sanity", "FightTimes", "times_finished", "sanity_cost",
    "StageDrops", "addQuantity", "annihilation_weekly_process",
    "OperatorMissing", '"reason":"Missing"', "BattleFormation",
    "UnsupportedLevel", "Not support stage", "SubTaskError", "BattleStartPre",
    "Roguelike", "StageInfo", "game_pass", "GamePass",
    "Reclamation", "PNS-", "ProsperityNoSave", "RA@Store",
)
# 🔴 2026-06-29 全局记录本次run的截图验证结果
_LAST_VERIFICATION = {}
_LAST_STAGE_MARKER_VERIFICATION = {}
# 🔴 2026-07-05 保全派驻需要手动编队时设为True, 跳过cleanup不关游戏
_SSS_NEED_MANUAL = False
_MAINLINE_RUN_SNAPSHOT = None
_MAINLINE_STAGE_ATTEMPTS = {}
# 同一主线运行内已经由章节地图真实OCR见过的H节点。OCR逐帧会偶发漏字，
# 后续扫描只允许补充这份证据，不能用一次漏识别撤销本轮早先取得的解锁证据。
# 每次mode_mainline启动时清空，绝不跨运行把旧地图状态当作当前事实。
_MAINLINE_HARD_MAP_EVIDENCE = {}
_LAST_VERIFY_ENTERED_BATTLE = False
AGGRESSIVE_CLEANUP = os.environ.get("ARKNIGHTS_AGGRESSIVE_CLEANUP", "0") == "1"
# 保全派驻是独立、不耗理智的周期任务。默认纳入 full；如需隔离排障可显式设为0。
ENABLE_SSS_IN_FULL = os.environ.get("ARKNIGHTS_ENABLE_SSS", "1") != "0"
_RUN_MUTEX_HANDLE = None
_RUN_SUMMARY = {}
_ACTIVE_EXECUTION_PLAN = None
# 完整流程的最终日常只能复用“最后一次理智作战之后”的完成记录。
# 该边界由总控在进入最终日常前从 MAA GUI 日志中编译，避免恢复同日早先日常后漏领奖励。
_DAILY_COMPLETION_NOT_BEFORE = None
# 本进程内刚刚真实闭环的理智作战时间。MAA GUI日志在部分Windows区域设置
# 下会把中文消息写成乱码，不能只依赖“开始行动/-理智”中文行恢复边界。
_CURRENT_RUN_LAST_STAMINA_BATTLE_AT = None

# 自动周流程一次最多给MAA 5次机会；MAA应在本周合成玉达到上限时自行停止。
# 这只是安全上限，不代表固定执行5次，更不以“周一”作为完成依据。
ANNIHILATION_AUTO_MAX_RUNS = 5


# 2026-07 当前活动。活动关开放期内，完整流程先首通，再把剩余理智全部投向活动关。
ACTIVE_EVENTS = [
    {
        "name": "墟",
        "start": "2026-08-22T04:00:00",
        "end": "2026-09-01T03:59:59",
        "kind": "rerun",
        # MAA StageActivityV2 exposes SSReopen-AT / “代理1~8关”. The stable
        # title character only selects a candidate; an AT node on the real map
        # is still required before battle admission.
        "entry_keywords": ["墟"],
        "combat_keywords": ["不夜街区"],
        "section_keywords": {
            "normal": ["不夜街区"],
            "ex": ["锻冶旧迹", "旧迹"],
            "s": ["绝缘石阶"],
        },
        "task_keywords": ["御机便览"],
        "task_claim_enabled": True,
        "stage_prefix": "AT",
        # 仓库缓存只用于展示；未刷新时不得擅自把收益关改成AT-6/AT-7。
        "farm_stage": "AT-8",
        "farm_cost": 21,
        "sanity_costs": {
            "AT-1": 9, "AT-2": 9,
            "AT-3": 12, "AT-4": 12, "AT-5": 12,
            "AT-6": 21, "AT-7": 21, "AT-8": 21,
            "AT-EX-1": 10, "AT-EX-2": 10,
            "AT-EX-3": 15, "AT-EX-4": 15,
            "AT-EX-5": 15, "AT-EX-6": 15,
            "AT-EX-7": 20, "AT-EX-8": 20,
            "AT-S-1": 15, "AT-S-2": 15,
            "AT-S-3": 20, "AT-S-4": 20,
        },
        # 复刻任务会重置：有任务奖励的耗理智关各用历史代理完成一次；
        # 只有任务表精确点名的AT-EX-8额外重打突袭。
        "replay_stages": [
            *[f"AT-{i}" for i in range(1, 9)],
            *[f"AT-EX-{i}" for i in range(1, 9)],
            *[f"AT-S-{i}" for i in range(1, 5)],
        ],
        "required_challenge_replays": ["AT-EX-8"],
        "task_clear_targets": [15, 45, 85],
        "stages": [
            {
                "display": f"AT-{i}",
                "internal": f"act44side_{i:02d}",
                "modes": ["normal"],
            }
            for i in range(1, 9)
        ] + [
            {
                "display": f"AT-EX-{i}",
                "internal": f"act44side_ex{i:02d}",
                "challenge_internal": f"act44side_ex{i:02d}#f#",
                "modes": ["normal", "challenge"],
            }
            for i in range(1, 9)
        ] + [
            {
                "display": f"AT-S-{i}",
                "internal": f"act44side_s{i:02d}",
                "challenge_internal": f"act44side_s{i:02d}#f#",
                "modes": ["normal", "challenge"],
            }
            for i in range(1, 5)
        ],
    },
    {
        "name": "直到大地变成一颗酸橙",
        "start": "2026-08-01T12:00:00",
        # 当前开放的第一段作战持续到08月22日03:59；后续两段只是在同一
        # 活动内追加节点，不应因为首日尚未开放就回退主线。
        "end": "2026-08-22T03:59:00",
        "kind": "new",
        # 终端卡片使用美术字，RapidOCR实机常把前半句拆错；“酸橙”是该卡
        # 独有且稳定的尾部文字。仍需在点击后用本期TO节点闭环确认，不能仅凭
        # 这个短词把任意页面当成活动地图。
        "entry_keywords": ["直到大地变成一颗酸橙", "酸橙"],
        "combat_keywords": ["驶向大地尽头"],
        # 活动地图底部真实页签；普通与EX必须由本期配置决定，禁止沿用上期
        # 红丝绒“演出开始/为戏剧，为永恒”的硬编码。
        "section_keywords": {
            "normal": ["驶向大地尽头"],
            "ex": ["踏上归家长途"],
            "s": ["眺望待行之路"],
        },
        # 三个篇章页签在1920x1080活动地图底部。白底美术字在实机截图中
        # 可能完全漏OCR，所以仅在已确认本期TO节点时允许使用坐标回退；
        # 点击后仍必须看到目标关卡族节点，不能把坐标点击本身当成功。
        "section_positions": {
            "normal": [1290, 1000],
            "ex": [1515, 1000],
            "s": [1750, 1000],
        },
        # 用户2026-08-03实机确认：“安洁莉娜的旅行小记”是需要遥感操控
        # 的小游戏，当前自动化不能可靠完成。其入口及关联奖励本期均不自动
        # 点击，也不作为今日活动战斗闭环的完成条件。
        "task_keywords": [],
        "task_claim_enabled": False,
        "task_claim_skip_reason": "安洁莉娜的旅行小记需遥感操控；用户明确要求当前暂不领取",
        "stage_prefix": "TO",
        # 用户2026-08-03明确指定：后续EX关开放前，活动期剩余理智固定刷TO-8。
        # 这条资源用途覆盖首日曾使用的TO-9临时配置，不能由“最高已通关关卡”推断回去。
        "farm_stage": "TO-8",
        "farm_cost": 21,
        # SideStory 普通第一段没有逐关突袭入口；EX阶段按每关自己的模式配置，
        # 不能把“所有关卡都普通+突袭”机械套进普通主线。
        "first_clear_modes": ["normal"],
        # 中途剧情同样是后续战斗关的真实解锁前置。实机已确认 TO-6 后
        # 必须先完成 TO-ST-2，才能出现 TO-7；不能把它误报成地图定位失败。
        "story_stages": ["TO-ST-1", "TO-ST-2"],
        # TO-1结束后会依次出现剧情/教学前置。教学关需要用户手动完成；
        # 若TO-2尚未出现且地图明确看到TO-TR-1，应直接说明真实阻挡，
        # 不能继续横扫地图并笼统报告“关卡未找到”。
        "manual_prerequisites": [
            {"display": "TO-TR-1", "before": "TO-2", "kind": "tutorial"},
        ],
        # 本期地图的 y=700 横穿 TO-3/TO-5 标签与连线；而 x=1500 位于
        # 右侧蓝色云层装饰，二者都会让拖动不交给真实地图。实机截图确认
        # 左侧三角地图内 y=850、x=250~650 是无节点的可交互带。
        "navigation_swipe_y": 850,
        "navigation_reset_swipe": [250, 850, 650, 850, 700],
        "navigation_forward_swipe": [650, 850, 250, 850, 700],
        "sanity_costs": {
            **{f"TO-{i}": 9 if i <= 2 else (12 if i <= 5 else 21) for i in range(1, 10)},
            "TO-EX-1": 10, "TO-EX-2": 10,
            "TO-EX-3": 15, "TO-EX-4": 15, "TO-EX-5": 15, "TO-EX-6": 15,
            "TO-EX-7": 20, "TO-EX-8": 20,
            "TO-S-1": 10, "TO-S-2": 10,
            "TO-S-3": 15, "TO-S-4": 15,
            "TO-MO-1": 25,
        },
        # 普通活动主线 TO-1~TO-9 与已开放的 EX-1~EX-8 分开声明模式。
        # 普通关只核对普通三星；EX关依次完成普通和突袭，再进入TO-8刷取。
        "stages": [
            {
                "display": f"TO-{i}",
                "internal": f"act53side_{i:02d}",
                "modes": ["normal"],
            }
            for i in range(1, 10)
        ] + [
            {
                "display": f"TO-EX-{i}",
                "internal": f"act53side_ex{i:02d}",
                "challenge_internal": f"act53side_ex{i:02d}#f#",
                "modes": ["normal", "challenge"],
            }
            for i in range(1, 9)
        ] + [
            {
                "display": f"TO-S-{i}",
                "internal": f"act53side_s{i:02d}",
                "challenge_internal": f"act53side_s{i:02d}#f#",
                "modes": ["normal", "challenge"],
            }
            for i in range(1, 5)
        ] + [
            {
                "display": "TO-MO-1",
                "internal": "act53side_mo01",
                "modes": ["normal"],
            }
        ],
    },
    {
        "name": "红丝绒",
        "start": "2026-07-20T04:00:00",
        # 关卡在07月30日03:59关闭；商店延长至08月03日不授权继续战斗。
        "end": "2026-07-30T03:59:00",
        "kind": "rerun",
        "entry_keywords": ["红丝绒"],
        "combat_keywords": ["演出开始", "为戏剧，为永恒"],
        "task_keywords": ["外景地娱乐项目"],
        "stage_prefix": "AD",
        "farm_stage": "AD-6",
        "farm_cost": 21,
        "sanity_costs": {
            "AD-1": 9, "AD-2": 9,
            "AD-3": 12, "AD-4": 12, "AD-5": 12,
            "AD-6": 21, "AD-7": 21, "AD-8": 21,
            "AD-EX-1": 10, "AD-EX-2": 10,
            "AD-EX-3": 15, "AD-EX-4": 15, "AD-EX-5": 15, "AD-EX-6": 15,
            "AD-EX-7": 20, "AD-EX-8": 20,
        },
        # 复刻任务会重置；这些耗理智关必须重新完成一次。普通关优先使用
        # 已有代理指挥，EX同样先实机检查代理入口，不能套用旧首通断点。
        "replay_stages": [
            *[f"AD-{i}" for i in range(1, 9)],
            *[f"AD-EX-{i}" for i in range(1, 9)],
        ],
        "required_challenge_replays": ["AD-EX-8"],
        "task_clear_targets": [15, 45, 85],
        "stages": [
            {"display": f"AD-{i}", "internal": f"AD-{i}"}
            for i in range(1, 9)
        ] + [
            {"display": f"AD-EX-{i}", "internal": f"AD-EX-{i}"}
            for i in range(1, 9)
        ],
    },
    {
        "name": "丛林症结",
        "start": "2026-07-10T12:00:00",
        "end": "2026-07-17T03:59:00",
        # 实机OCR会在“丛”与“从”之间波动，两者都只用于终端活动卡片定位。
        "entry_keywords": ["丛林症结", "从林症结"],
        "combat_keywords": ["生长痛"],
        "farm_stage": "BD-8",
        "farm_cost": 21,
        "stages": [
            {"display": f"BD-{i}", "internal": f"act21mini_{i:02d}"}
            for i in range(1, 9)
        ],
    }
]

# 终端左下也会展示网页/非理智活动。它们只提供情报，不能抢占周一剿灭
# 核对，也不能把真正的理智活动和主线全部冻结。别名包含实机OCR波动。
NON_STAMINA_TERMINAL_ACTIVITIES = [
    {
        "name": "异相寻展",
        "aliases": ["异相寻展", "异相巡展", "奇象寻展", "奇象巡展"],
    },
]

# 2026-07-13从PRTS作业站逐关核对的高热度精确作业。随包内置，明天不依赖临时搜索结果。
VERIFIED_EVENT_COPILOT_IDS = {
    "BD-1": 97197,
    "BD-2": 97200,
    "BD-3": 97201,
    "BD-4": 97205,
    "BD-5": 97216,
    "BD-6": 97218,
    "BD-7": 97219,
    "BD-8": 97224,
}


def get_active_event(now=None):
    """返回当前开放活动；所有日期判断集中在这里，避免散落硬编码。"""
    now = now or datetime.now()
    for event in ACTIVE_EVENTS:
        start = datetime.fromisoformat(event["start"])
        end = datetime.fromisoformat(event["end"])
        if start <= now < end:
            return event
    return None


# MAA StageManager.AddPermanentStages 的国服固定关卡表。脚本在这里复制
# “今日关卡小提示”的数据逻辑，而不是打开 MAA 窗口读取 UI。Python weekday:
# Monday=0 ... Sunday=6。库存 ID 与 MAA StageManager.cs 的 DropGroups 一致。
MAA_PERMANENT_STAGE_TIPS = (
    {"stage": "CE-6", "tip": "龙门币", "days": (1, 3, 5, 6)},
    {"stage": "AP-5", "tip": "采购凭证", "days": (0, 3, 5, 6)},
    {
        "stage": "CA-5", "tip": "技能", "days": (1, 2, 4, 6),
        "drop_groups": (("3301", "3302", "3303"),),
    },
    {"stage": "LS-6", "tip": "经验", "days": tuple(range(7))},
    {"stage": "SK-5", "tip": "碳", "days": (0, 2, 4, 5)},
    {
        "stage": "PR-A-1/2", "tip": "奶&盾芯片", "days": (0, 3, 4, 6),
        "drop_groups": (("3261", "3231"), ("3262", "3232")),
    },
    {
        "stage": "PR-B-1/2", "tip": "术&狙芯片", "days": (0, 1, 4, 5),
        "drop_groups": (("3251", "3241"), ("3252", "3242")),
    },
    {
        "stage": "PR-C-1/2", "tip": "先锋&辅助芯片", "days": (2, 3, 5, 6),
        "drop_groups": (("3211", "3271"), ("3212", "3272")),
    },
    {
        "stage": "PR-D-1/2", "tip": "近卫&特种芯片", "days": (1, 2, 5, 6),
        "drop_groups": (("3221", "3281"), ("3222", "3282")),
    },
)


def _maa_api_time_to_utc(value, time_zone_hours=8):
    """复制 MAA StageManager.ParseDateTime：配置时刻减 TimeZone 得 UTC。"""
    parsed = datetime.strptime(str(value), "%Y/%m/%d %H:%M:%S")
    return (parsed - timedelta(hours=float(time_zone_hours or 0))).replace(
        tzinfo=timezone.utc
    )


def _as_utc(now=None):
    """项目按国服 UTC+8 解释无时区时间；测试可传入 aware datetime。"""
    value = now or datetime.now(timezone(timedelta(hours=8)))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone(timedelta(hours=8)))
    return value.astimezone(timezone.utc)


def _parse_iso_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    # .NET 的 round-trip 格式可带 7 位小数；Python 只需要微秒精度。
    text = re.sub(r"(\.\d{6})\d+(?=[+-]\d\d:\d\d$|Z$)", r"\1", text)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed


def _read_json_file(path, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, ValueError, TypeError):
        return default


def build_maa_daily_stage_tip(
    now=None,
    activity_path=None,
    depot_path=None,
    item_index_path=None,
    client="Official",
    depot_fresh_hours=24,
):
    """在本脚本内复刻 MAA 的“今日关卡小提示”。

    活动开放期来自 StageActivityV2；库存来自 DepotData。二者分开标注时效，
    旧库存只展示，绝不直接授权资源消耗。
    """
    activity_path = activity_path or MAA_STAGE_ACTIVITY_CACHE
    depot_path = depot_path or MAA_DEPOT_CACHE
    item_index_path = item_index_path or MAA_ITEM_INDEX
    now_utc = _as_utc(now)
    local_now = now_utc.astimezone(timezone(timedelta(hours=8)))
    activity_data = _read_json_file(activity_path, {}) or {}
    depot_record = _read_json_file(depot_path, {}) or {}
    item_index = _read_json_file(item_index_path, {}) or {}

    raw_depot = depot_record.get("data") or {}
    if isinstance(raw_depot, str):
        try:
            raw_depot = json.loads(raw_depot)
        except ValueError:
            raw_depot = {}
    depot = {
        str(item_id): int(count)
        for item_id, count in (raw_depot.items() if isinstance(raw_depot, dict) else [])
        if isinstance(count, (int, float)) and not isinstance(count, bool)
    }
    sync_time = _parse_iso_datetime(depot_record.get("syncTime"))
    depot_age_hours = None
    if sync_time is not None:
        depot_age_hours = max(
            0.0,
            (now_utc - sync_time.astimezone(timezone.utc)).total_seconds() / 3600,
        )
    depot_fresh = bool(
        depot_record.get("done") is True
        and depot
        and depot_age_hours is not None
        and depot_age_hours <= float(depot_fresh_hours)
    )

    lines = []
    active_side_stories = []
    client_data = activity_data.get(client) or {}
    for activity_key, entry in (client_data.get("sideStoryStage") or {}).items():
        activity = (entry or {}).get("Activity") or {}
        try:
            start_utc = _maa_api_time_to_utc(
                activity.get("UtcStartTime"), activity.get("TimeZone", 8)
            )
            expire_utc = _maa_api_time_to_utc(
                activity.get("UtcExpireTime"), activity.get("TimeZone", 8)
            )
        except (TypeError, ValueError):
            continue
        if not (start_utc <= now_utc < expire_utc):
            continue
        seconds_left = max(0, (expire_utc - now_utc).total_seconds())
        days_left = int(seconds_left // 86400)
        days_text = str(days_left) if days_left > 0 else "不到1"
        name = activity.get("StageName") or activity_key
        story = {
            "key": activity_key,
            "name": name,
            "start_utc": start_utc.isoformat(),
            "expire_utc": expire_utc.isoformat(),
            "remaining_seconds": int(seconds_left),
            "remaining_days_text": days_text,
            "stages": [],
        }
        active_side_stories.append(story)
        lines.append(f"「{name}」剩余天数: {days_text}天")
        for stage in (entry or {}).get("Stages") or []:
            value = str((stage or {}).get("Value") or (stage or {}).get("Display") or "")
            drop = str((stage or {}).get("Drop") or "")
            if not value or not drop:
                continue
            item = item_index.get(drop) if isinstance(item_index, dict) else None
            drop_name = (item or {}).get("name") if isinstance(item, dict) else None
            drop_name = drop_name or drop
            count = depot.get(drop)
            text = f"{value}: {drop_name}"
            if count is not None:
                text += f" (库存 {count})"
            lines.append(text)
            story["stages"].append({
                "stage": value,
                "drop_id": drop if drop in depot or drop_name != drop else None,
                "drop": drop_name,
                "inventory": count,
            })

    resource_lines = []
    for entry in MAA_PERMANENT_STAGE_TIPS:
        if local_now.weekday() not in entry["days"]:
            continue
        text = f"{entry['stage']}: {entry['tip']}"
        groups = []
        for group in entry.get("drop_groups") or ():
            groups.append(" & ".join(str(depot.get(item_id, "--")) for item_id in group))
        if groups:
            text += f" (库存 {' / '.join(groups)})"
        lines.append(text)
        resource_lines.append({
            "stage": entry["stage"],
            "tip": entry["tip"],
            "inventory_groups": groups,
        })

    if sync_time is None:
        inventory_note = "仓库缓存无同步时间；库存只展示，不参与自动决策"
    elif depot_fresh:
        inventory_note = f"仓库缓存已刷新（{sync_time.astimezone(timezone(timedelta(hours=8))).isoformat()}）"
    else:
        inventory_note = (
            "仓库缓存已过期"
            f"（{sync_time.astimezone(timezone(timedelta(hours=8))).isoformat()}，"
            f"约{depot_age_hours:.1f}小时前）；库存只展示，不参与自动决策"
        )
    return {
        "status": "ok" if activity_data else "activity_cache_missing",
        "generated_at": local_now.isoformat(),
        "source": {
            "activity": os.path.abspath(activity_path),
            "depot": os.path.abspath(depot_path),
            "items": os.path.abspath(item_index_path),
        },
        "active_side_stories": active_side_stories,
        "resource_stages": resource_lines,
        "depot": {
            "sync_time": sync_time.isoformat() if sync_time else None,
            "counts": depot,
            "age_hours": round(depot_age_hours, 2) if depot_age_hours is not None else None,
            "fresh": depot_fresh,
            "fresh_limit_hours": depot_fresh_hours,
            "note": inventory_note,
        },
        "lines": lines,
        "text": "今日关卡小提示:\n" + "\n".join(lines) + "\n" + inventory_note,
    }


def save_maa_daily_stage_tip(now=None):
    """生成脚本自用提示快照；不启动 MAA，不控制鼠标。"""
    tip = build_maa_daily_stage_tip(now=now)
    json_path = os.path.join(RUNTIME_STATE_DIR, "今日关卡小提示.json")
    md_path = os.path.join(RUNTIME_STATE_DIR, "今日关卡小提示.md")
    _atomic_write_json(json_path, tip)
    with open(md_path, "w", encoding="utf-8") as stream:
        stream.write("# 今日关卡小提示\n\n")
        stream.write("\n".join(f"- {line}" for line in tip["lines"]))
        stream.write(f"\n\n> {tip['depot']['note']}\n")
    tip["output_json"] = json_path
    tip["output_md"] = md_path
    return tip


def choose_dynamic_333_plan(tip):
    """按已刷新仓库选择0/1/2/3条搓玉线；返回可审计决定。"""
    depot = (tip or {}).get("depot") or {}
    counts = depot.get("counts") or {}
    result = {
        "status": "inventory_unverified",
        "plan_index": None,
        "orundum_lines": None,
        "rock": counts.get("30012"),
        "lmd": counts.get("4001"),
        "sync_time": depot.get("sync_time"),
        "policy": "rock<20 or lmd<100k:0; rock<120 or lmd<500k:1; rock<360 or lmd<1.5m:2; else:3",
    }
    if depot.get("fresh") is not True:
        result["reason"] = depot.get("note") or "depot_cache_not_fresh"
        return result
    rock = counts.get("30012")
    lmd = counts.get("4001")
    if not isinstance(rock, int) or not isinstance(lmd, int):
        result["reason"] = "required_inventory_missing"
        return result
    if rock < 20 or lmd < 100_000:
        lines = 0
    elif rock < 120 or lmd < 500_000:
        lines = 1
    elif rock < 360 or lmd < 1_500_000:
        lines = 2
    else:
        lines = 3
    result.update({
        "status": "selected",
        "plan_index": lines,
        "orundum_lines": lines,
        "lmd_lines": 3 - lines,
        "reason": f"实时仓库固源岩{rock}、龙门币{lmd}",
    })
    return result


def _configure_user_data_update(cfg):
    queue = _task_queue(cfg)
    task = next((item for item in queue if item.get("TaskType") == "UserDataUpdate"), None)
    if task is None:
        task = {
            "$type": "UserDataUpdateTask", "Name": "", "IsEnable": False,
            "TaskType": "UserDataUpdate",
        }
        queue.append(task)
    _set_enabled_tasks(cfg, {"UserDataUpdate"})
    task.update({
        "UpdateOperBox": False,
        "UpdateDepot": True,
        "TriggerInterval": "EveryTime",
        "IsTriggered": True,
    })
    return task


def _refresh_depot_for_dynamic_333():
    """独立刷新仓库；只有本次同步完成且缓存新鲜才允许改产品。"""
    summary = _RUN_SUMMARY.setdefault("base_333", {})
    summary["inventory_refresh"] = "running"
    started = datetime.now(timezone(timedelta(hours=8)))
    if not goto_main_menu():
        summary.update({"inventory_refresh": "failed", "reason": "main_menu_not_confirmed"})
        return None
    reload_maa_after_config_switch("动态333决策前刷新仓库")
    try:
        with temporary_maa_config(_configure_user_data_update, "仅UserDataUpdate刷新仓库"):
            if not run_maa_daily_tasks(enabled_tasks={"UserDataUpdate"}):
                raise RuntimeError("UserDataUpdate启动失败")
            result = wait_maa_complete(
                timeout=600, continue_after_chain_error=False, prestarted_boundary=True
            )
            if result is not True:
                raise RuntimeError(f"UserDataUpdate未确认完成: {result}")
    except Exception as exc:
        summary.update({"inventory_refresh": "failed", "reason": str(exc)})
        log(f"⚠️ 动态333仓库刷新失败，不改变基建产品: {exc}", "WARN")
        return None
    tip = build_maa_daily_stage_tip(
        now=datetime.now(timezone(timedelta(hours=8))), depot_fresh_hours=1
    )
    synced = _parse_iso_datetime((tip.get("depot") or {}).get("sync_time"))
    if not (tip.get("depot") or {}).get("fresh") or synced is None:
        summary.update({"inventory_refresh": "failed", "reason": "fresh_depot_cache_missing"})
        return None
    # 允许MAA写盘与本地时钟存在少量偏差，但拒绝昨日缓存。
    if synced.astimezone(timezone.utc) < (started - timedelta(minutes=5)).astimezone(timezone.utc):
        summary.update({"inventory_refresh": "failed", "reason": "depot_sync_not_from_current_refresh"})
        return None
    summary.update({
        "inventory_refresh": "verified",
        "inventory_sync_time": (tip.get("depot") or {}).get("sync_time"),
    })
    return tip


def _apply_dynamic_333_infrast_config(decision):
    """持久切换最终日常Infrast到选定MAA原生333产品方案。"""
    summary = _RUN_SUMMARY.setdefault("base_333", {})
    plan_index = (decision or {}).get("plan_index")
    if not isinstance(plan_index, int) or not 0 <= plan_index <= 3:
        summary.update({"status": "unchanged", "reason": "inventory_decision_unverified"})
        return False
    config_data = _read_json_file(DYNAMIC_333_CONFIG, {}) or {}
    plans = config_data.get("plans") or []
    if len(plans) != 4:
        summary.update({"status": "failed", "reason": "dynamic_333_config_invalid"})
        return False
    config_path = os.path.join(MAA_CONFIG, "gui.new.json")
    cfg = _read_json_file(config_path, {}) or {}
    try:
        infrast = next(item for item in _task_queue(cfg) if item.get("TaskType") == "Infrast")
    except (StopIteration, TypeError):
        summary.update({"status": "failed", "reason": "maa_infrast_task_missing"})
        return False
    backup_dir = os.path.join(OUTPUT_DIR, "maa_config_backups")
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(
        backup_dir, f"gui.new.before_dynamic333_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    _atomic_write_json(backup_path, cfg)
    infrast.update({
        "Mode": "Custom",
        "UsesOfDrones": "SyntheticJade" if plan_index else "Money",
        "OriginiumShardAutoReplenishment": True,
        "CustomFileType": "user_defined",
        "Filename": os.path.abspath(DYNAMIC_333_CONFIG),
        "PlanSelect": plan_index,
    })
    _atomic_write_json(config_path, cfg)
    summary.update({
        "status": "configured",
        "layout": "333",
        "decision": deepcopy(decision),
        "config": os.path.abspath(DYNAMIC_333_CONFIG),
        "plan_index": plan_index,
        "backup": backup_path,
    })
    log(
        f"✅ 动态333已选择{plan_index}条搓玉线、{3-plan_index}条龙门币线 "
        f"({decision.get('reason')})"
    )
    return True


def prepare_dynamic_333_base():
    tip = _refresh_depot_for_dynamic_333()
    if tip is None:
        return False
    decision = choose_dynamic_333_plan(tip)
    summary = _RUN_SUMMARY.setdefault("base_333", {})
    summary["decision"] = deepcopy(decision)
    if decision.get("status") != "selected":
        log("⚠️ 动态333库存未核验，不改变当前产品配置", "WARN")
        return False
    if not _apply_dynamic_333_infrast_config(decision):
        return False
    if not goto_main_menu():
        summary["home_return"] = "failed"
        summary["reason"] = "动态333仓库刷新后未能返回主界面"
        log("⏸ 动态333仓库刷新后未确认主页；拒绝盲启最终日常", "ERROR")
        return False
    summary["home_return"] = "verified"
    return True


def _configured_event_from_maa_tip(tip):
    """把 MAA 活动日历命中已批准活动；未知活动必须返回 None。"""
    for story in (tip or {}).get("active_side_stories") or []:
        configured = _configured_event_from_name(story.get("name"))
        if configured:
            return configured, story
    return None, None


def _configured_event_from_name(name):
    """把终端OCR活动名映射到配置；终端图形证据高于日期推断。"""
    normalized = re.sub(r"[<>《》〈〉「」『』\s]", "", str(name or ""))
    for event in ACTIVE_EVENTS:
        candidates = [event.get("name", ""), *(event.get("entry_keywords") or [])]
        for candidate in candidates:
            token = re.sub(r"[<>《》〈〉「」『』\s]", "", str(candidate or ""))
            if token and (token in normalized or normalized in token):
                return event
    return None


def _non_stamina_activity_from_name(name):
    """识别终端卡片中的非理智活动；仅忽略明确列入白名单的项目。"""
    normalized = re.sub(r"[<>《》〈〉「」『』\s]", "", str(name or ""))
    for activity in NON_STAMINA_TERMINAL_ACTIVITIES:
        for candidate in [activity.get("name", ""), *(activity.get("aliases") or [])]:
            token = re.sub(r"[<>《》〈〉「」『』\s]", "", str(candidate or ""))
            if token and (token in normalized or normalized in token):
                return activity
    return None


def detect_terminal_limited_event():
    """在终端左下活动卡片读取活动名、开放状态和倒计时。

    返回status=open|none|uncertain。只有确认进入终端且左下没有“活动已开放”
    才能返回none；OCR或导航失败不得被解释成“无活动”。
    """
    result = {
        "status": "uncertain",
        "name": None,
        "remaining_days": None,
        "evidence": "",
    }
    if not goto_terminal_main():
        result["evidence"] = "无法进入终端"
        log("⛔ 活动检测无法进入终端；禁止据此选择主线", "ERROR")
        return result

    p = shot("terminal_limited_event")
    items = ocr(p)
    # 1920x1080实机：限时活动卡固定在左下。只读取此ROI，避免把右侧
    # 剿灭/集成战略倒计时或中间章节文字当成活动证据。
    roi_items = [
        (str(text), x, y) for text, x, y in items
        if 0 <= x <= 800 and 650 <= y <= 1035
    ]
    roi_text = " ".join(text for text, _x, _y in roi_items)
    page_text = " ".join(str(text) for text, _x, _y in items)
    terminal_confirmed = (
        get_state() == "terminal_list"
        or "ATTENTION" in page_text.upper()
        or "TO-DO LIST" in page_text.upper()
        or "前往上一次作战" in page_text
    )
    if not terminal_confirmed:
        result["evidence"] = f"终端页面语义未确认: {page_text[:160]}"
        log(f"⛔ 活动检测未确认终端页面: {page_text[:120]}", "ERROR")
        return result

    if "活动已开放" not in roi_text:
        result.update({"status": "none", "evidence": f"左下活动ROI无开放标记: {roi_text[:120]}"})
        log("✅ 终端左下活动卡片未显示‘活动已开放’")
        return result

    remaining = None
    day_matches = re.findall(r"(?<!\d)(\d{1,2})\s*天", roi_text)
    if day_matches:
        remaining = min(int(value) for value in day_matches)

    # 常见OCR结果为“<红丝绒>活动已开放”或“红丝绒 活动已开放”。
    activity_name = None
    name_match = re.search(
        r"[<《〈「『]?\s*([^<>《》〈〉「」『』]{2,20}?)\s*[>》〉」』]?\s*活动已开放",
        roi_text,
    )
    if name_match:
        activity_name = name_match.group(1).strip(" <>《》〈〉「」『』")
        # OCR偶尔把倒计时拼到活动名前面。
        activity_name = re.sub(r"\d{1,2}\s*天", "", activity_name).strip()

    if not activity_name:
        result["evidence"] = f"发现活动已开放但活动名未识别: {roi_text[:160]}"
        log(f"⛔ 已发现开放活动，但活动名识别失败: {roi_text[:120]}", "ERROR")
        return result

    result.update({
        "status": "open",
        "name": activity_name,
        "remaining_days": remaining,
        "evidence": roi_text[:240],
    })
    log(
        f"✅ 终端活动检测: {activity_name} 已开放"
        f"，剩余{remaining if remaining is not None else '未识别'}天"
    )
    return result


def _game_day_key(now=None):
    """方舟每日刷新以04:00为界；跨零点仍属于同一个游戏日。"""
    now = now or datetime.now()
    return (now - timedelta(hours=4)).date().isoformat()


def acquire_single_instance():
    """Windows命名互斥锁：禁止两个自动化流程同时操作同一游戏界面。"""
    global _RUN_MUTEX_HANDLE
    if _RUN_MUTEX_HANDLE:
        return True
    if os.name != "nt":
        return True
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\ArknightsAutoCodex")
    if not handle:
        log("❌ 无法创建自动化单实例锁", "ERROR")
        return False
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        log("❌ 已有明日方舟自动化流程正在运行，本次拒绝启动", "ERROR")
        return False
    _RUN_MUTEX_HANDLE = handle
    log("  🔒 已取得自动化单实例锁")
    return True


def release_single_instance():
    """Release the process-wide automation mutex when a supervisor exits.

    Windows also closes the handle when the process terminates, but an explicit
    release keeps long-running supervisors and in-process recovery/tests from
    reporting a cleanup exception after all game processes were already closed.
    """
    global _RUN_MUTEX_HANDLE
    handle = _RUN_MUTEX_HANDLE
    if not handle:
        return True
    _RUN_MUTEX_HANDLE = None
    if os.name != "nt":
        return True
    try:
        import ctypes

        closed = bool(ctypes.windll.kernel32.CloseHandle(handle))
    except Exception as exc:
        log(f"⚠️ 释放自动化单实例锁异常: {exc}", "WARN")
        return False
    if not closed:
        log("⚠️ 释放自动化单实例锁失败", "WARN")
        return False
    log("  🔓 已释放自动化单实例锁")
    return True


_LONG_TERM_TERMINAL_STATUSES = {
    "reward_completion_unconfirmed",
    "technical_pause",
    "deadline_stopped",
    "phantom_objectives_completed",
    "prosperity_cap_reached",
}


def record_long_term_handoff(
    kind,
    status,
    *,
    detail="",
    residue_state=None,
    cleanup_finished=False,
):
    """Persist whether a finished long-term run left UI for daily takeover.

    A battle screen alone never grants permission to restart the game.  The
    long-term owner must first publish a terminal handoff after its MAA queue
    has stopped; cleanup completion revokes that permission.
    """
    payload = {
        "schema_version": 1,
        "kind": str(kind or "unknown"),
        "status": str(status or "unknown"),
        "detail": str(detail or ""),
        "residue_state": residue_state,
        "game_day": _game_day_key(),
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "cleanup_finished": bool(cleanup_finished),
        "daily_takeover_authorized": bool(
            status in _LONG_TERM_TERMINAL_STATUSES
            and not cleanup_finished
            and residue_state == "battle"
        ),
    }
    _atomic_write_json(LONG_TERM_HANDOFF_FILE, payload)
    log(
        "  [长期任务交接] "
        f"{payload['kind']}/{payload['status']}, "
        f"残留={payload['residue_state']}, "
        f"每日接管={'允许' if payload['daily_takeover_authorized'] else '不允许'}"
    )
    return payload


def _load_daily_long_term_handoff(now=None):
    """Return a same-game-day terminal handoff that still owns a battle UI."""
    now = now or datetime.now()
    try:
        with open(LONG_TERM_HANDOFF_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if payload.get("game_day") != _game_day_key(now):
        return None
    if payload.get("status") not in _LONG_TERM_TERMINAL_STATUSES:
        return None
    if payload.get("cleanup_finished"):
        return None
    if payload.get("residue_state") != "battle":
        return None
    if payload.get("daily_takeover_authorized") is not True:
        return None
    return payload


def _recover_terminal_long_term_battle_for_daily():
    """Cold-restart only a battle explicitly handed off by a finished owner."""
    plan = _ACTIVE_EXECUTION_PLAN or _RUN_SUMMARY.get("execution_plan") or {}
    if not _RUN_MUTEX_HANDLE:
        log("⛔ 战斗残留恢复被拒绝: 当前流程未持有单实例锁", "ERROR")
        return False
    if plan.get("mode") not in {"daily", "full"} or "daily" not in set(
        plan.get("allowed_actions") or []
    ):
        log("⛔ 战斗残留恢复被拒绝: 当前执行契约未授权每日接管", "ERROR")
        return False
    if _maa_task_queue_running():
        log("⛔ 战斗残留恢复被拒绝: MAA任务队列仍在运行", "ERROR")
        return False
    handoff = _load_daily_long_term_handoff()
    if not handoff:
        log("⛔ 战斗残留恢复被拒绝: 没有同游戏日长期任务终态交接证据", "ERROR")
        return False

    before = shot("daily_orphaned_battle_before_restart")
    log(
        "→ 长期任务已终止且MAA队列空闲；每日流程接管旧战斗并冷启动游戏 "
        f"({handoff.get('kind')}/{handoff.get('status')})"
    )
    stopped = subprocess.run(
        [ADB, "-s", DEVICE, "shell", "am", "force-stop", PKG],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if stopped.returncode != 0:
        log(f"❌ 旧战斗冷启动停止失败: {(stopped.stderr or '').strip()}", "ERROR")
        return False
    wait(2)
    launched = subprocess.run(
        [ADB, "-s", DEVICE, "shell", "monkey", "-p", PKG, "-c",
         "android.intent.category.LAUNCHER", "1"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if launched.returncode != 0 or "error" in (launched.stderr or "").lower():
        log(f"❌ 旧战斗冷启动拉起失败: {(launched.stderr or '').strip()}", "ERROR")
        return False
    _RUN_SUMMARY["daily_battle_recovery"] = {
        "status": "cold_restart_started",
        "kind": handoff.get("kind"),
        "terminal_status": handoff.get("status"),
        "before_screenshot": before,
        "recovered_at": datetime.now().isoformat(timespec="seconds"),
    }
    record_long_term_handoff(
        handoff.get("kind"),
        handoff.get("status"),
        detail="每日流程已接管旧战斗并启动包级冷启动",
        residue_state="restarting",
        cleanup_finished=False,
    )
    return True


def _recover_current_run_battle_for_final_daily():
    """Cold-restart a battle residue created by this same full run.

    Long-term handoff evidence is required when a new process takes over an
    older battle.  It is intentionally not required here: the active full run
    has direct ownership evidence in ``_CURRENT_RUN_LAST_STAMINA_BATTLE_AT``
    and has already observed the Copilot terminal state.  Without this narrow
    path a failed event job can leave the game paused in battle and make the
    final daily queue fail before it starts.
    """
    if get_state() != "battle":
        return True
    if _CURRENT_RUN_LAST_STAMINA_BATTLE_AT is None:
        log("⛔ 检测到战斗残留，但本轮没有理智战斗所有权证据；拒绝接管", "ERROR")
        return False
    if _maa_task_queue_running():
        log("⛔ 本轮战斗残留恢复被拒绝：MAA任务队列仍在运行", "ERROR")
        return False

    before = shot("current_run_battle_before_final_daily_restart")
    log("→ 本轮理智战斗已终止但画面仍在战斗；冷启动游戏后再执行最终日常")
    stopped = subprocess.run(
        [ADB, "-s", DEVICE, "shell", "am", "force-stop", PKG],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if stopped.returncode != 0:
        log(f"❌ 本轮战斗残留停止失败: {(stopped.stderr or '').strip()}", "ERROR")
        return False
    wait(2)
    launched = subprocess.run(
        [ADB, "-s", DEVICE, "shell", "monkey", "-p", PKG, "-c",
         "android.intent.category.LAUNCHER", "1"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if launched.returncode != 0 or "error" in (launched.stderr or "").lower():
        log(f"❌ 本轮战斗残留冷启动失败: {(launched.stderr or '').strip()}", "ERROR")
        return False
    _RUN_SUMMARY["daily_battle_recovery"] = {
        "status": "current_run_cold_restart_started",
        "before_screenshot": before,
        "battle_owned_at": _CURRENT_RUN_LAST_STAMINA_BATTLE_AT.isoformat(
            timespec="seconds"
        ),
        "recovered_at": datetime.now().isoformat(timespec="seconds"),
    }
    return True

# ============================================================
# 防御检查系统 (2026-06-30 self-improvement归纳后植入)
# 基于15个高频错误，每次执行前/中/后自动验证
# ============================================================

# 已知错误模式清单 (来源: .learnings/ERRORS.md)
GUARD_RULES = [
    # (id, severity, description, source_pattern)
    # severity: FATAL=阻断, WARN=警告但继续
    ("G01", "FATAL", "ensure_env不得用MuMuNxMain.exe启动VM", "MuMuNxMain.exe"),
    ("G02", "FATAL", "mode_full:daily后必须ensure_env重启环境", None),  # 运行时检查
    ("G03", "FATAL", "goto_chapter:快捷入口到formation必须back", None),  # 运行时检查
    ("G04", "FATAL", "wait_maa_complete不得用主界面判完成", "主界面.*时间.*完成"),
    ("G05", "WARN",  "notify_completion不得含os.startfile", "os.startfile"),
    ("G06", "FATAL", "generate_daily_report必须用_LAST_MAA_RUN_START_LINE", None),
    ("G07", "FATAL", "main:cleanup必须在verify_mainline_completion之后", None),
    ("G08", "FATAL", "登录点击必须用黄色菱形坐标(961,1028)", None),
    ("G09", "FATAL", "StagePlan剿灭必须是Annihilation不是空串", "\"StagePlan\".*\"\""),
    ("G10", "WARN",  "mode_annihilation必须执行日常任务", None),
    ("G11", "WARN",  "MAA更新后TaskQueue会重置需检查", None),
    ("G12", "FATAL", "Import按钮完全不点", None),
    ("G13", "FATAL", "难度选择器是下拉框不是toggle", None),
    ("G14", "FATAL", "get_state必须检测所有弹窗状态", None),
    ("G15", "FATAL", "游戏启动需捕获stderr防device offline", None),
]

_guard_failures = []  # 本轮检查累计失败

def _guard_check(check_id, context=None, **kwargs):
    """运行时防御检查: 在已知错误点主动验证前置条件
    
    Args:
        check_id: GUARD_RULES中的G编号 或 自定义描述
        context: 额外上下文信息
        **kwargs: 条件断言, 如 condition=True, expected="xxx", actual="yyy"
    
    用法:
        _guard_check("G02", daily_ok=True)           # 断言条件
        _guard_check("G03", state="formation")       # 带上下文
        _guard_check("G07", cleanup_after_verify=True) # 自定义
    """
    global _guard_failures
    condition = kwargs.get("condition", True)
    expected = kwargs.get("expected")
    actual = kwargs.get("actual")
    
    if not condition:
        msg = f"⚠️ [GUARD:{check_id}] 防御检查失败!"
        if context:
            msg += f" 上下文: {context}"
        if expected and actual:
            msg += f"  期望: {expected} | 实际: {actual}"
        
        # 查找严重级别
        severity = "WARN"
        for rule in GUARD_RULES:
            if rule[0] == check_id:
                severity = rule[1]
                msg = f"⚠️ [GUARD:{check_id}] {rule[2]}"
                if context:
                    msg += f" ({context})"
                break
        
        _guard_failures.append((check_id, severity, msg))
        if severity == "FATAL":
            log(msg, "ERROR")
        else:
            log(msg, "WARN")
        return False
    else:
        # 通过时静默 (太多日志干扰)
        return True


def _guard_static_scan():
    """静态扫描自身源码, 检查已知错误模式是否残留 (启动时执行一次)"""
    import re
    try:
        with open(__file__, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
    except:
        log("  [Guard静态] 无法读取自身源码, 跳过", "WARN")
        return
    
    # 按稳定的章节标记排除Guard/Preflight自身，不能依赖会随编辑漂移的固定行号。
    business_start = next(
        (i for i, line in enumerate(all_lines) if line.strip() == "# 章节与难度配置"),
        len(all_lines),
    )
    source = "".join(all_lines[business_start:])
    
    checks = {
        # G01: 检查 mumu-cli launch 是否作为主要启动方式存在 (好模式存在, 而非坏模式不存在)
        # fallback里允许subprocess.Popen([MUMU_PLAYER])作为回退
        "G01_mumu_cli_launch": (r'mumu-cli.*control.*launch', 
                               "ensure_env中缺少mumu-cli launch主启动方式"),
        # G05: 检查 os.startfile( 不在注释中 (注释掉的代码不算)
        "G05_os_startfile": (r'^[^#\n]*os\.startfile\(', 
                            "notify_completion中残留os.startfile()调用(已注释的不算)"),
        # G04: 检查 wait_maa_complete 是否还用主界面+时间判完成
        "G04_main_menu_complete": (r'task_started\s+and\s+state\s*==\s*"main_menu"\s+and\s+el\s*>\s*60', 
                                  "wait_maa_complete残留主界面+时间判据"),
        # G09: StagePlan=[""] 空串配置
        "G09_StagePlan_empty": (r'"StagePlan"\s*:\s*\[\s*""\s*\]', 
                               "StagePlan残留空串配置(应为Annihilation)"),
    }
    
    found = 0
    for check_id, (pattern, desc) in checks.items():
        # G01是"好模式必须存在", 其他是"坏模式必须不存在"
        if check_id == "G01_mumu_cli_launch":
            if not re.search(pattern, source):
                _guard_failures.append((check_id, "FATAL", f"静态扫描发现: {desc}"))
                log(f"  ❌ [Guard静态] {desc}", "ERROR")
                found += 1
        else:
            if re.search(pattern, source, re.MULTILINE):
                _guard_failures.append((check_id, "FATAL", f"静态扫描发现: {desc}"))
                log(f"  ❌ [Guard静态] {desc}", "ERROR")
                found += 1
    
    if found == 0:
        log("  ✅ [Guard静态] 4项源码检查全部通过")
    else:
        log(f"  ⚠️ [Guard静态] {found}项未通过! 可能导致已知bug复现", "ERROR")
    return found == 0

def _guard_report():
    """打印本轮所有防御检查结果"""
    global _guard_failures
    if not _guard_failures:
        log("✅ 所有防御检查通过")
        return True
    
    fatals = [f for f in _guard_failures if f[1] == "FATAL"]
    warns = [f for f in _guard_failures if f[1] == "WARN"]
    
    log(f"\n{'='*50}")
    log(f"🛡️ 防御检查报告: {len(_guard_failures)}项未通过")
    if fatals:
        log(f"  ❌ 致命({len(fatals)}项):")
        for f in fatals:
            log(f"     [{f[0]}] {f[2]}")
    if warns:
        log(f"  ⚠️ 警告({len(warns)}项):")
        for f in warns:
            log(f"     [{f[0]}] {f[2]}")
    log(f"{'='*50}")
    
    _guard_failures = []  # 清空, 准备下一轮
    return len(fatals) == 0


# ============================================================
# Pre-Flight Checklist (2026-06-30 跨对话业务规则强制检查)
# 读取 BUSINESS_RULES.json, 验证代码和AI行为是否符合所有用户反馈
# ============================================================

BUSINESS_RULES_FILE = os.path.join(SCRIPT_DIR, "BUSINESS_RULES.json")


def load_project_contract():
    """Load the user-authorized project goals that outrank technical rules."""
    try:
        with open(PROJECT_CONTRACT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log(f"  [项目契约] 读取失败: {exc}", "ERROR")
        return None


def validate_project_contract(contract=None):
    """Validate structure and the non-negotiable authorization invariants."""
    contract = contract or load_project_contract()
    errors = []
    if not isinstance(contract, dict):
        return False, ["项目契约不存在或不是JSON对象"]
    if contract.get("schema_version") != 1:
        errors.append("schema_version必须为1")
    goals = contract.get("active_goals") or []
    goal_ids = [goal.get("id") for goal in goals if isinstance(goal, dict)]
    if not goal_ids or len(goal_ids) != len(set(goal_ids)) or any(not item for item in goal_ids):
        errors.append("active_goals必须具有唯一且非空的id")
    governance = contract.get("governance") or {}
    if governance.get("assistant_inference_may_change_goal") is not False:
        errors.append("助手推断不得改变项目目标")
    if governance.get("goal_change_requires_user_approval") is not True:
        errors.append("目标变化必须要求用户确认")
    if governance.get("unknown_transition") != "pause_and_report":
        errors.append("未知转移必须暂停并报告")
    constraints = contract.get("hard_constraints") or {}
    if constraints.get("unapproved_resource_fallback") is not False:
        errors.append("不得授权未配置的资源关兜底")
    if constraints.get("difficulty_downgrade") is not False:
        errors.append("不得自动降低难度")
    if int(constraints.get("max_mainline_attempts", 0) or 0) != 5:
        errors.append("主线单关上限必须为5套有效不同作业")
    if int(constraints.get("max_event_attempts", 0) or 0) != 5:
        errors.append("活动单关上限必须为5套有效不同作业")
    if constraints.get("unknown_cli_argument") != "fatal":
        errors.append("未知命令行参数必须阻止执行")
    goal_memory = contract.get("goal_memory") or {}
    time_classes = goal_memory.get("time_classes") or []
    classified_goal_ids = {
        goal_id
        for item in time_classes if isinstance(item, dict)
        for goal_id in (item.get("goal_ids") or [])
    }
    active_goal_ids = {
        goal.get("id") for goal in goals
        if isinstance(goal, dict) and goal.get("status") != "superseded"
    }
    if classified_goal_ids != active_goal_ids:
        missing = sorted(active_goal_ids - classified_goal_ids)
        extra = sorted(classified_goal_ids - active_goal_ids)
        errors.append(f"目标记忆必须分类全部活动目标; missing={missing}, extra={extra}")
    daily_clock = goal_memory.get("daily_clock") or {}
    if daily_clock.get("long_term_cleanup_deadline") != "11:30":
        errors.append("长期任务统一清理时间必须为11:30")
    if daily_clock.get("daily_automation_start") != "12:00":
        errors.append("每日自动化启动时间必须为12:00")
    if daily_clock.get("single_control_owner") is not True:
        errors.append("同一时间只能有一个游戏控制者")
    guards = goal_memory.get("transition_guards") or {}
    if guards.get("new_goal_insertion") != "current_explicit_user_instruction_then_recompile":
        errors.append("新增目标必须来自用户当前明确指令并重新编译契约")
    if guards.get("insert_between_final_daily_and_cleanup") != "forbidden":
        errors.append("最终五链与清理之间不得插入其他目标")
    flow = goal_memory.get("ordered_daily_flow") or []
    orders = [item.get("order") for item in flow if isinstance(item, dict)]
    if not flow or orders != sorted(orders) or len(orders) != len(set(orders)):
        errors.append("每日目标顺序必须存在、递增且无重复")
    return not errors, errors


def _record_decision_request(action, reason, goal_ids=None, proposed_change=None):
    """Record an improvement idea without executing a goal-changing action."""
    request = {
        "action": action,
        "reason": reason,
        "goal_ids": list(goal_ids or []),
        "proposed_change": proposed_change,
        "status": "awaiting_user_approval",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _RUN_SUMMARY.setdefault("decision_requests", []).append(request)
    log(f"⏸ 建议待确认，未执行: {action} — {reason}", "WARN")
    return request


def compile_execution_plan(
    mode,
    *,
    stage=None,
    max_attempts=5,
    theme=None,
    reclamation_cycles=None,
    reclamation_stop_at=None,
    unknown_args=None,
):
    """Compile CLI intent into an immutable, user-authorized run plan."""
    global _ACTIVE_EXECUTION_PLAN
    contract = load_project_contract()
    valid, contract_errors = validate_project_contract(contract)
    if not valid:
        for error in contract_errors:
            _record_decision_request("修复项目契约", error, ["G-AUTH-001"])
        return None

    violations = []
    constraints = contract["hard_constraints"]
    mode_actions = contract.get("mode_actions") or {}
    if mode not in mode_actions:
        violations.append(f"未知运行模式: {mode}")
    if unknown_args:
        violations.append(f"未知命令行参数: {' '.join(unknown_args)}")
    if int(max_attempts) > int(constraints["max_mainline_attempts"]):
        violations.append(
            f"请求重试{max_attempts}次，超过用户授权上限{constraints['max_mainline_attempts']}次"
        )
    if mode == "resource" and not stage:
        violations.append("资源关模式必须明确指定--stage，不能由脚本选择")
    if mode == "event_verify" and not stage:
        violations.append("活动手动完成复核必须明确指定--stage，不能由脚本猜测")
    if mode == "chapter17_sandbox" and not stage:
        violations.append("第17章沙盘恢复模式必须明确指定--stage")
    if mode == "reclamation" and reclamation_cycles is None:
        violations.append("生息演算必须明确指定--reclamation-cycles，不能继承历史预算")

    if violations:
        for violation in violations:
            _record_decision_request("拒绝编译越权计划", violation, ["G-AUTH-001"])
        return None

    goal_ids_by_mode = {
        "full": ["G-AUTH-001", "G-WEEKLY-001", "G-EVENT-001", "G-MAINLINE-001", "G-DAILY-001", "G-REPORT-001"],
        "event_today": ["G-AUTH-001", "G-EVENT-001", "G-DAILY-001", "G-REPORT-001"],
        "event_first_clear": ["G-AUTH-001", "G-EVENT-001", "G-REPORT-001"],
        "mainline": ["G-AUTH-001", "G-MAINLINE-001", "G-REPORT-001"],
        "chapter17_sandbox": ["G-AUTH-001", "G-MAINLINE-001", "G-REPORT-001"],
        "daily": ["G-AUTH-001", "G-DAILY-001", "G-REPORT-001"],
        "annihilation": ["G-AUTH-001", "G-WEEKLY-001", "G-REPORT-001"],
        "resource": ["G-AUTH-001", "G-REPORT-001"],
        "event": ["G-AUTH-001", "G-EVENT-001", "G-REPORT-001"],
        "event_verify": ["G-AUTH-001", "G-EVENT-001", "G-REPORT-001"],
        "roguelike": ["G-AUTH-001", "G-LONG-001", "G-REPORT-001"],
        "reclamation": ["G-AUTH-001", "G-LONG-001", "G-REPORT-001"],
        "security": ["G-AUTH-001", "G-SSS-001", "G-REPORT-001"],
    }
    plan = {
        "mode": mode,
        "goal_ids": goal_ids_by_mode.get(mode, ["G-AUTH-001"]),
        "allowed_actions": list(mode_actions.get(mode, [])),
        "requested_stage": stage,
        "max_attempts": min(int(max_attempts), int(constraints["max_mainline_attempts"])),
        "theme": theme,
        "reclamation_cycles": reclamation_cycles,
        "reclamation_stop_at": reclamation_stop_at,
        "unknown_transition": contract["governance"]["unknown_transition"],
        "goal_memory_revision": contract["goal_memory"]["revision"],
        "transition_guards": deepcopy(contract["goal_memory"]["transition_guards"]),
        "compiled_at": datetime.now().isoformat(timespec="seconds"),
        "status": "authorized",
    }
    _ACTIVE_EXECUTION_PLAN = deepcopy(plan)
    _RUN_SUMMARY["execution_plan"] = deepcopy(plan)
    return plan


def _ensure_execution_plan(mode, **kwargs):
    if _ACTIVE_EXECUTION_PLAN and _ACTIVE_EXECUTION_PLAN.get("mode") == mode:
        return _ACTIVE_EXECUTION_PLAN
    return compile_execution_plan(mode, **kwargs)


def _plan_allows(action):
    plan = _ACTIVE_EXECUTION_PLAN or _RUN_SUMMARY.get("execution_plan") or {}
    allowed = action in set(plan.get("allowed_actions") or [])
    if not allowed:
        _record_decision_request(
            action,
            f"本轮{plan.get('mode', 'unknown')}执行契约未授权该动作",
            plan.get("goal_ids") or ["G-AUTH-001"],
        )
    return allowed

def preflight_check():
    """启动前强制检查所有业务规则 (跨对话错误防护的核心机制)
    
    读取 BUSINESS_RULES.json, 对每条规则:
    - code_pattern: 扫描自身源码验证 required_pattern/required_patterns/forbidden_pattern
    - ai_behavior: 仅记录, 由AI在对话中遵守 (无法自动检查)
    
    任何 fatal 规则失败 → 打印错误但继续执行 (不阻塞, 但记录)
    """
    import json as _json
    import re as _re

    contract = load_project_contract()
    contract_ok, contract_errors = validate_project_contract(contract)
    if not contract_ok:
        log(f"  [Preflight] 项目契约失败: {'; '.join(contract_errors)}", "ERROR")
        return False
    active_goal_ids = {
        goal.get("id") for goal in (contract.get("active_goals") or [])
        if isinstance(goal, dict) and goal.get("status") != "superseded"
    }
    
    if not os.path.exists(BUSINESS_RULES_FILE):
        log("  [Preflight] BUSINESS_RULES.json 不存在，阻止执行", "ERROR")
        return False
    
    try:
        with open(BUSINESS_RULES_FILE, 'r', encoding='utf-8') as f:
            rules_data = _json.load(f)
    except Exception as e:
        log(f"  [Preflight] 读取BUSINESS_RULES.json失败，阻止执行: {e}", "ERROR")
        return False
    
    # 读取自身源码 (排除定义区域)
    try:
        with open(__file__, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        business_start = next(
            (i for i, line in enumerate(all_lines) if line.strip() == "# 章节与难度配置"),
            len(all_lines),
        )
        source = "".join(all_lines[business_start:])
    except:
        log("  [Preflight] 无法读取自身源码", "WARN")
        return True
    
    business_rules = rules_data.get("business_rules", [])
    ai_rules = rules_data.get("ai_behavior_rules", [])
    
    fatal_failures = []
    warn_failures = []
    code_checked = 0
    ai_noted = 0
    
    for rule in business_rules:
        rule_id = rule.get("id", "?")
        desc = rule.get("rule", "")
        severity = rule.get("severity", "warn")
        check_type = rule.get("check_type", "")

        if rule.get("changes_execution_flow"):
            goal_refs = set(rule.get("goal_refs") or [])
            if not goal_refs or not goal_refs.issubset(active_goal_ids):
                fatal_failures.append((
                    rule_id,
                    desc,
                    f"[{rule_id}] 流程规则缺少有效goal_refs: {sorted(goal_refs)}",
                ))
                continue
        
        if check_type == "code_pattern":
            code_checked += 1
            passed = True
            
            # 检查 forbidden_pattern (坏模式必须不存在)
            forbidden = rule.get("forbidden_pattern")
            if forbidden and _re.search(forbidden, source, _re.MULTILINE):
                passed = False
                msg = f"[{rule_id}] 发现禁止模式: {forbidden}"
            
            # 单个长正则会把函数内部语句顺序误当成业务语义。行为由多个
            # 独立特征共同保证时使用 required_patterns，各特征无序校验；
            # required_pattern 仅保留给确实要求结构顺序的旧规则。
            required = rule.get("required_pattern")
            if required and not _re.search(required, source, _re.MULTILINE):
                passed = False
                msg = f"[{rule_id}] 缺少必需模式: {required}"
            required_patterns = rule.get("required_patterns") or []
            missing_patterns = [
                pattern for pattern in required_patterns
                if not _re.search(pattern, source, _re.MULTILINE)
            ]
            if missing_patterns:
                passed = False
                msg = f"[{rule_id}] 缺少必需特征: {missing_patterns}"
            
            if not passed:
                if severity == "fatal":
                    fatal_failures.append((rule_id, desc, msg))
                else:
                    warn_failures.append((rule_id, desc, msg))
        
        elif check_type == "ai_behavior":
            ai_noted += 1
            # AI行为规则无法自动检查, 仅记录
    
    # 输出结果 (精简版: 只显示摘要和失败项)
    total = len(business_rules)
    if fatal_failures:
        log(f"\n🛡️ Pre-Flight: {total}条规则, ❌{len(fatal_failures)}条失败 — {fatal_failures[0][2]}")
    elif warn_failures:
        log(f"\n🛡️ Pre-Flight: {total}条规则, ⚠️{len(warn_failures)}条警告 — {', '.join(f[0] for f in warn_failures)}")
    else:
        log(f"\n🛡️ Pre-Flight: {total}条规则, ✅全部通过")
    
    # 写入验证结果到文件 (供AI对话时读取)
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_rules": total,
        "code_checked": code_checked,
        "ai_noted": ai_noted,
        "fatal_failures": [{"id": f[0], "desc": f[1], "msg": f[2]} for f in fatal_failures],
        "warn_failures": [{"id": f[0], "desc": f[1], "msg": f[2]} for f in warn_failures],
        "all_passed": len(fatal_failures) == 0 and len(warn_failures) == 0,
        "project_contract": {
            "path": PROJECT_CONTRACT_FILE,
            "schema_version": contract.get("schema_version"),
            "active_goal_ids": sorted(active_goal_ids),
            "valid": contract_ok,
        },
    }
    try:
        result_path = os.path.join(BASE, "outputs", "preflight_result.json")
        with open(result_path, 'w', encoding='utf-8') as f:
            _json.dump(result, f, ensure_ascii=False, indent=2)
    except:
        pass
    
    return len(fatal_failures) == 0


# ============================================================
# 章节与难度配置
# ============================================================

CHAPTER_NAMES = {
    10: "破碎日冕", 11: "淬火尘霾", 12: "惊霆无声",
    13: "恶兆湍流", 14: "慈悲灯塔", 15: "离解复合",
    16: "反常光谱", 17: "相变临界",
}

# 难度系统: 每章最难难度 + 选择器坐标
DIFFICULTY = {
    # 10~14章磨难环境一次实际扣除42理智；旧日志按普通关21记账会少报一半。
    10: {"hardest": "磨难", "selector": (264, 966), "option": (849, 1041), "sanity_cost": 42},
    11: {"hardest": "磨难", "selector": (264, 966), "option": (849, 1041), "sanity_cost": 42},
    12: {"hardest": "磨难", "selector": (264, 966), "option": (849, 1041), "sanity_cost": 42},
    13: {"hardest": "磨难", "selector": (264, 966), "option": (849, 1041), "sanity_cost": 42},
    14: {"hardest": "磨难", "selector": (264, 966), "option": (849, 1041), "sanity_cost": 42},
    # 07/30 实机：第15章章节地图只有单一主线环境；左下角区域是“推演计分”说明，
    # 不是难度下拉框。继续沿用旧坐标会打开说明弹窗并把真实章节地图误判为难度失败。
    15: {"hardest": "单一主线环境", "selector": None, "option": None,
         "single_environment": True},
    # 07/30 实机：第16章与15章相同，左下角同样是推演计分说明而非难度下拉。
    16: {"hardest": "单一主线环境", "selector": None, "option": None,
         "single_environment": True},
    # 第17章没有章节级难度下拉，但有逐关的“常规作战→险地作战→沙盘推演”
    # 三阶段。章节地图这里只确认章节，不得据此把关卡视为单一环境或已闭环。
    17: {"hardest": "险地作战+沙盘推演", "selector": None, "option": None,
         "per_stage_difficulty": True},
}

# 第17章只有这些战斗节点具有沙盘推演。17-14、17-16、17-18是特殊节点，
# 作业说明也没有沙盘选项，继续沿用后期章节详情三徽记作为终态证据。
CHAPTER17_SANDBOX_STAGES = frozenset(
    [f"17-{index}" for index in range(2, 14)] + ["17-15", "17-17"]
)
CHAPTER17_SPECIAL_STAGES = frozenset(("17-14", "17-16", "17-18"))

# 全权委托代理指挥卡也用于周一剿灭。自动流程单周上限为5次，因此保全
# 不能再沿用旧的“留1张”思路；只有到期分桶证明扣除后仍有5张可跨到
# 下一个周一时，才允许消耗2张做一次保全全权委托。
ANNIHILATION_DELEGATE_RESERVE = 5
SSS_FULL_DELEGATE_COST = 2

# 资源关代码
RESOURCE_STAGES = {
    "1-7": {"name": "盘前奏曲", "cost": 6, "drop": "固源岩"},
    "AP-5": {"name": "固若金汤", "cost": 30, "drop": "采购凭证"},
    "AP-6": {"name": "固若金汤", "cost": 48, "drop": "采购凭证"},
    "LS-6": {"name": "战术演习", "cost": 36, "drop": "经验卡"},
    "LS-7": {"name": "战术演习", "cost": 48, "drop": "经验卡"},
    "SK-5": {"name": "技能研究", "cost": 36, "drop": "技能书"},
    "CE-6": {"name": "货物运送", "cost": 36, "drop": "龙门币"},
    "CA-5": {"name": "空中威胁", "cost": 36, "drop": "技巧概要"},
    "PR-A-1": {"name": "钛源", "cost": 18, "drop": "芯片"},
    "PR-A-2": {"name": "钛源", "cost": 36, "drop": "芯片"},
    "PR-B-1": {"name": "铜源", "cost": 18, "drop": "芯片"},
    "PR-B-2": {"name": "铜源", "cost": 36, "drop": "芯片"},
    "PR-C-1": {"name": "锌源", "cost": 18, "drop": "芯片"},
    "PR-C-2": {"name": "锌源", "cost": 36, "drop": "芯片"},
    "PR-D-1": {"name": "锰源", "cost": 18, "drop": "芯片"},
    "PR-D-2": {"name": "锰源", "cost": 36, "drop": "芯片"},
}

# MAA v6.16 的“库存保持”官方预设：低级芯片和高级芯片组各职业保持
# 20；全部满足或当日关卡未开放后，AP-5 作为无活动、主线全闭环后的
# 常驻理智出口。采购凭证目标故意设为极高值，使它只因理智不足停止，
# 而不是在已有5000红票时错误留下满理智。
DEPOT_CHIP_FLOOR = 20
DEPOT_RESOURCE_FALLBACK_PLANS = (
    ("PR-A-1", "3231", "重装芯片", DEPOT_CHIP_FLOOR),
    ("PR-A-1", "3261", "医疗芯片", DEPOT_CHIP_FLOOR),
    ("PR-B-1", "3241", "狙击芯片", DEPOT_CHIP_FLOOR),
    ("PR-B-1", "3251", "术师芯片", DEPOT_CHIP_FLOOR),
    ("PR-C-1", "3211", "先锋芯片", DEPOT_CHIP_FLOOR),
    ("PR-C-1", "3271", "辅助芯片", DEPOT_CHIP_FLOOR),
    ("PR-D-1", "3221", "近卫芯片", DEPOT_CHIP_FLOOR),
    ("PR-D-1", "3281", "特种芯片", DEPOT_CHIP_FLOOR),
    ("PR-A-2", "3232", "重装芯片组", DEPOT_CHIP_FLOOR),
    ("PR-A-2", "3262", "医疗芯片组", DEPOT_CHIP_FLOOR),
    ("PR-B-2", "3242", "狙击芯片组", DEPOT_CHIP_FLOOR),
    ("PR-B-2", "3252", "术师芯片组", DEPOT_CHIP_FLOOR),
    ("PR-C-2", "3212", "先锋芯片组", DEPOT_CHIP_FLOOR),
    ("PR-C-2", "3272", "辅助芯片组", DEPOT_CHIP_FLOOR),
    ("PR-D-2", "3222", "近卫芯片组", DEPOT_CHIP_FLOOR),
    ("PR-D-2", "3282", "特种芯片组", DEPOT_CHIP_FLOOR),
    ("AP-5", "4006", "采购凭证", 999999),
)

# 剿灭关卡
ANNIHILATION_STAGES = {
    "1-7": "切尔诺伯格",
    "龙门外环": "龙门外环",
    "龙门市区": "龙门市区",
    "废弃矿区": "废弃矿区",
    "北原冰原": "北原冰原",
}

# MAA Core 使用的肉鸽主题 ID。旧值“杰作花园/战略围棋/迷雾歧路”既不是
# 游戏主题名也不是 Core ID，会使 GUI 回退到上一次主题，造成看似启动成功、
# 实际跑错主题。保留 garden 作为 JieGarden 的兼容别名。
ROGUELIKE_THEMES = {
    "phantom": "Phantom",
    "mizuki": "Mizuki",
    "sami": "Sami",
    "sarkaz": "Sarkaz",
    "jiegarden": "JieGarden",
    "garden": "JieGarden",
}

ROGUELIKE_THEME_NAMES = {
    "Phantom": "傀影与猩红孤钻",
    "Mizuki": "水月与深蓝之树",
    "Sami": "探索者的银凇止境",
    "Sarkaz": "萨卡兹的无终奇语",
    "JieGarden": "岁的界园志异",
}

# MAA WPF 持久化使用的肉鸽策略枚举名。Core 日志中的数值分别为
# Exp=0、Squad=6、Deep=7。这里显式收口，避免只打开“自动轮换”开关却
# 仍继承 Exp，造成看似在补月度、实际继续刷级。
ROGUELIKE_MODES = {
    "exp": "Exp",
    "monthly": "Squad",
    # MAA WPF's RoguelikeMode enum calls Core mode=7 "Exploration".
    # Writing the intuitive but invalid value "Deep" makes the tolerant
    # deserializer discard the field and silently fall back to Exp (mode=0).
    "deep": "Exploration",
}

ROGUELIKE_CORE_MODE_IDS = {
    "Exp": 0,
    "Squad": 6,
    "Exploration": 7,
}

# ============================================================
# 关键坐标 (1920x1080 横屏) — 2026-06-27 23:17 正统流程验证
# ============================================================

# 主界面右上角 "终端" 入口
# 🔴 2026-07-01 修正: OCR实测"终端"@(1450,240), 点击后进入终端列表(正确)
# 之前误改为(890,175)是错的, 那个位置在角色立绘区域
POS_TERMINAL = (1450, 241)
# 1920x1080 终端底栏“常态事务”。终端首页的剿灭周任务卡在达到
# 1800/1800 后会消失；玩家会进入常态事务，在左侧待办栏查看合成玉
# 进度。最右侧雪花是周期挑战/危机合约，不能误当剿灭入口。
POS_TERMINAL_ROUTINE = (1118, 1000)

# Act II 章节选择页 → 破碎日冕概览 → "前往章节" 按钮 (图4验证)
POS_GO_CHAPTER = (1680, 930)  # 章节概览页右下角“前往章节”(1920x1080, 07/12截图确认)

# 编队界面 "开始行动" 按钮 (已验证)
POS_START_BATTLE = (1768, 988)
POS_SKIP = (1774, 81)
# 2026-08-11 TO-ST-1 实机复核：剧情跳过确认框右侧圆形勾选。
# 1920x1080 下按钮中心约为 (1197, 693)。旧坐标 (1200, 540) 位于正文区，
# 会形成“点右上跳过→点空白→仍在剧情”的重复技术失败。
POS_SKIP_CONFIRM = (1197, 693)
# 2026-08-08 水月首次结局跳过剧情后会进入“数据回溯”中间页；
# 该按钮位于模拟器 1920x1080 坐标系右下角。MAA 不识别此页，必须
# 先闭环它再重启同一肉鸽队列，否则会被误计为连续技术崩溃。
POS_MIZUKI_DATA_REVIEW_START = (1773, 975)
POS_MIZUKI_REVIEW_NEXT = (1815, 575)
POS_MIZUKI_REVIEW_DONE = (960, 980)
POS_DISMISS = (960, 960)
POS_BACK = (60, 70)
POS_LOGIN_START = (961, 1028)
# 游戏内顶部导航条的房屋图标。左侧(60,70)是返回箭头，房屋实际在约(400,55)。
POS_TOP_HOME = (400, 55)
# 主界面任务按钮(左侧栏, 日常/周常任务入口)
POS_TASK_BTN = (245, 200)
# 任务页"全部领取"按钮(右上角)
POS_CLAIM_ALL = (1780, 140)

# MAA GUI 控件位置
MAA_EDIT_POS = (92, 282)
MAA_IMPORT_POS = (670, 282)
MAA_START_RECT = (351, 362, 591, 462)

# ============================================================
# 基础工具函数
# ============================================================

def _atomic_write_json(path, data):
    """原子写入JSON，避免进程中断留下半截配置文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _task_queue(cfg):
    try:
        return cfg["Configurations"]["Default"]["TaskQueue"]
    except (KeyError, TypeError):
        raise ValueError("MAA配置缺少 Configurations.Default.TaskQueue")


def _set_enabled_tasks(cfg, enabled_tasks):
    """只启用指定MAA任务，返回是否至少找到一个目标任务。"""
    enabled_tasks = set(enabled_tasks)
    found = set()
    for task in _task_queue(cfg):
        task_type = task.get("TaskType", "")
        task["IsEnable"] = task_type in enabled_tasks
        if task_type in enabled_tasks:
            found.add(task_type)
    missing = enabled_tasks - found
    if missing:
        raise ValueError(f"MAA配置缺少任务: {sorted(missing)}")
    return True


def _configure_maa_mumu_screenshot_enhancement(cfg, emulator_path=None):
    """配置MAA官方MuMu 12截图增强；不启用网络桥接或增强触控。"""
    emulator_path = os.path.abspath(emulator_path or MUMU_INSTALL_ROOT)
    try:
        settings = cfg["Configurations"]["Default"]["Gui"]["ConnectSettings"]
    except (KeyError, TypeError):
        raise ValueError("MAA配置缺少 Configurations.Default.Gui.ConnectSettings")
    if settings.get("Config") != "MuMuEmulator12":
        raise ValueError(f"MAA连接配置不是MuMuEmulator12: {settings.get('Config')}")
    extras = settings.setdefault("Extras", {}).setdefault("MuMuEmulator12", {})
    extras.update({
        "EmulatorPath": emulator_path,
        "EnableBridgeConnection": False,
        "EnableTouch": False,
        "InstanceIndex": int(MUMU_VM_INDEX),
        "IsEnabled": True,
    })
    return extras


def _maa_mumu_core_extras(emulator_path=None):
    """返回MaaCore key=6所需的最小MuMu增强截图参数。"""
    return json.dumps({
        "path": os.path.abspath(emulator_path or MUMU_INSTALL_ROOT),
    }, ensure_ascii=False, separators=(",", ":"))


def _maa_screencap_log_mode(log_text):
    """由MaaCore连接日志区分增强截图、通用ADB截图和连接失败。"""
    text = str(log_text or "")
    if re.search(r"MuMuEmulator12\s*\{[^}]*[\"']?path[\"']?\s*:", text, re.S):
        return "mumu_enhanced"
    if "adb_cfg.extras is empty" in text or "FastestWayToScreencap" in text:
        return "generic_adb"
    if any(marker in text for marker in (
        "ConnectFailed", "ConnectionError", "Failed to connect", "connect failed",
    )):
        return "connection_failed"
    return "unknown"


def prepare_maa_mumu_screenshot_enhancement(config_path=None, emulator_path=None):
    """在MAA启动前事务化启用MuMu截图增强，并保留首份原配置备份。"""
    if not ENABLE_MAA_MUMU_SCREENSHOT_ENHANCEMENT:
        return {"status": "disabled_by_env"}
    config_path = config_path or os.path.join(MAA_CONFIG, "gui.new.json")
    emulator_path = os.path.abspath(emulator_path or MUMU_INSTALL_ROOT)
    if not os.path.isfile(os.path.join(emulator_path, "nx_main", "MuMuNxMain.exe")):
        return {"status": "unsupported", "reason": "mumu_install_missing"}
    try:
        with open(config_path, "r", encoding="utf-8") as stream:
            original = json.load(stream)
        modified = deepcopy(original)
        extras = _configure_maa_mumu_screenshot_enhancement(modified, emulator_path)
        if modified == original:
            return {"status": "already_enabled", "extras": deepcopy(extras)}

        # MAA运行时会自行回写gui.new.json；只在空闲启动边界改配置，避免竞态。
        if config_path == os.path.join(MAA_CONFIG, "gui.new.json") and _maa_process_ids():
            return {"status": "deferred", "reason": "maa_running"}

        original_bytes = json.dumps(
            original, ensure_ascii=False, indent=2
        ).encode("utf-8")
        digest = hashlib.sha256(original_bytes).hexdigest()[:16]
        backup_dir = os.path.join(BASE, "outputs", "config_backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(
            backup_dir, f"maa_gui_new_before_mumu_screencap_{digest}.json"
        )
        if not os.path.exists(backup_path):
            _atomic_write_json(backup_path, original)
        _atomic_write_json(config_path, modified)
        return {
            "status": "enabled",
            "backup": backup_path,
            "extras": deepcopy(extras),
        }
    except Exception as exc:
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}


@contextmanager
def temporary_maa_config(mutator, description):
    """临时修改MAA配置；无论任务成功、失败或抛异常都恢复原配置。"""
    config_path = os.path.join(MAA_CONFIG, "gui.new.json")
    with open(config_path, "r", encoding="utf-8") as f:
        original = json.load(f)
    modified = deepcopy(original)
    mutator(modified)
    _atomic_write_json(config_path, modified)
    log(f"→ MAA临时配置已应用: {description}")
    try:
        yield config_path
    finally:
        try:
            _atomic_write_json(config_path, original)
            log("→ MAA临时配置已恢复")
        except Exception as e:
            log(f"❌ 恢复MAA配置失败: {e}", "ERROR")


def reload_maa_after_config_switch(reason):
    """任务边界关闭空闲MAA，使下一次启动重新读取已落盘配置。"""
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "MAA.exe"],
            capture_output=True, encoding="gbk", errors="replace", timeout=8,
        )
        if result.returncode == 0:
            log(f"  [MAA配置边界] 已关闭空闲MAA，下一任务重载配置: {reason}")
            wait(2)
            _refresh_windows_taskbar("MAA配置切换")
        return True
    except Exception as e:
        log(f"  ⚠️ MAA配置重载准备失败: {e}", "WARN")
        return False


def _configure_fight(cfg, stage_code, times, current_stage=False):
    """配置一次受次数限制的Fight任务，并启用游戏内最大连续代理倍率。

    新活动刚开放时，MAA 的活动关列表可能尚未收录关卡代号。此时由脚本先用
    图形导航停在已通关普通关详情页，再让 Fight 接管“当前关卡”，避免 MAA
    把未知关卡重置为空后错误跳到上一次的突袭页面。
    """
    if not isinstance(times, int) or times < 1:
        raise ValueError("刷取次数必须是大于0的整数")
    _set_enabled_tasks(cfg, {"Fight"})
    fight = next(t for t in _task_queue(cfg) if t.get("TaskType") == "Fight")
    fight["StagePlan"] = [] if current_stage else [stage_code]
    fight["EnableTimesLimit"] = True
    fight["TimesLimit"] = times
    # MAA v6 的 Series=0 表示自动选择当前可用的最大连续代理次数（最高6次），
    # 同时会在理智不足6次时自动降到可执行次数。显式写入，避免继承旧GUI配置。
    fight["Series"] = 0
    fight["HideSeries"] = False
    fight["UseMedicine"] = False
    fight["UseStone"] = False


def _configure_depot_resource_fallback(cfg):
    """配置MAA库存保持：芯片/芯片组不足20优先，其后AP-5耗尽理智。"""
    queue = _task_queue(cfg)
    task = next(
        (item for item in queue if item.get("TaskType") == "DepotMaintain"),
        None,
    )
    if task is None:
        task = {
            "$type": "DepotMaintainTask",
            "Name": "主线全清后的芯片与采购凭证兜底",
            "IsEnable": False,
            "TaskType": "DepotMaintain",
        }
        queue.append(task)
    _set_enabled_tasks(cfg, {"DepotMaintain"})
    task.update({
        "UpdateDepot": True,
        "IsStageManually": False,
        "SkipDuringActivity": True,
        "SkipDuringResourceCollection": False,
        "UseAutoSeries": True,
        "UseMedicine": False,
        "UseStone": False,
        "UseExpiringMedicine": False,
        "PlanList": [
            {
                "Stage": stage,
                "DropId": drop_id,
                "DropCount": target,
                "UseMedicine": False,
                "MedicineCount": 0,
                "UseStone": False,
                "StoneCount": 0,
                "TaskId": 0,
            }
            for stage, drop_id, _drop_name, target
            in DEPOT_RESOURCE_FALLBACK_PLANS
        ],
    })
    return task


def _configure_reclamation_tales(cfg, clear_store=True):
    """配置沙洲遗闻无存档刷点；只有图形确认“开始演算”后才能调用。"""
    _set_enabled_tasks(cfg, {"Reclamation"})
    task = next(t for t in _task_queue(cfg) if t.get("TaskType") == "Reclamation")
    task["Theme"] = "Tales"
    # MAA GUI枚举名；对应核心协议 mode=0（无存档，进出关卡刷生息点数）。
    task["Mode"] = "ProsperityNoSave"
    task["ToolToCraft"] = ""
    task["IncrementMode"] = 0
    task["MaxCraftCountPerRound"] = 16
    # GUI文字为“任务完成后购买商店”，用户目标是领取尚未取得的奖励。
    task["ClearStore"] = bool(clear_store)
    return task


def _normalise_stage_label(value):
    """用于作业精确匹配；只保留字母数字，统一大小写。"""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _copilot_matches_stage(content, stage_name, display_name):
    """拒绝PRTS模糊检索混入的其他关卡作业。"""
    if not isinstance(content, dict):
        return False
    target_internal = _normalise_stage_label(stage_name)
    target_display = _normalise_stage_label(display_name)
    actual_internal = _normalise_stage_label(content.get("stage_name"))
    title = str((content.get("doc") or {}).get("title", ""))
    title_head = re.split(r"\s+-\s+|\s+", title.strip(), maxsplit=1)[0]
    actual_display = _normalise_stage_label(title_head)
    # MAA 作业站对 H 关使用 hard_CC-NN 内部名，例如 H12-4 = hard_12-04。
    # 不能只拿显示名 H12-4 与 stage_name 做字符串相等，否则标题以“第十二章”
    # 开头的有效作业会被误删。仍然要求完整关卡编号相等，避免模糊串关。
    hard_alias = ""
    h_match = re.fullmatch(r"H(\d{1,2})-(\d{1,2})", str(display_name or "").strip(), re.I)
    if h_match:
        hard_alias = _normalise_stage_label(
            f"hard_{int(h_match.group(1)):02d}-{int(h_match.group(2)):02d}"
        )
    # 活动关显示名会被不同活动重复使用（例如 TO-1）。只要调用方已经
    # 提供了本期内部关卡名，且作业也声明了内部关卡名，就必须严格相等；
    # 不能再因为标题里的显示名相同而误收旧活动作业。
    if target_internal and actual_internal:
        # 新旧MAA作业并存：作业站通常保存 hard_CC-NN，较新的本地作业
        # 可能直接保存 HCC-N。二者都必须与同一个完整H关编号严格等价；
        # 只放宽这组可逆别名，不允许普通关或活动关靠标题模糊串关。
        if hard_alias:
            return actual_internal in {
                target_internal,
                target_display,
                hard_alias,
            }
        return actual_internal == target_internal
    title_has_exact_display = bool(
        target_display
        and re.search(
            rf"(?<![A-Z0-9]){re.escape(str(display_name).strip())}(?![0-9])",
            title,
            re.I,
        )
    )
    return bool(
        (target_internal and actual_internal == target_internal)
        or (target_display and actual_display == target_display)
        or (hard_alias and actual_internal == hard_alias)
        or title_has_exact_display
    )


def _resolve_roguelike_theme(theme):
    value = str(theme or "garden").strip()
    canonical = ROGUELIKE_THEMES.get(value.lower(), value)
    if canonical not in ROGUELIKE_THEME_NAMES:
        raise ValueError(f"不支持的肉鸽主题: {theme}")
    return canonical


def _configure_roguelike(
    cfg,
    theme,
    difficulty=2147483647,
    starts_count=1,
    core_char="维什戴尔",
    squad="远程战术分队",
    roles="稳扎稳打",
    mode="Exp",
):
    """配置肉鸽任务；默认刷级，也支持月度小队和深入调查。"""
    difficulty = int(difficulty)
    starts_count = int(starts_count)
    if difficulty < 0:
        raise ValueError("肉鸽难度不能小于0")
    if starts_count < 1:
        raise ValueError("肉鸽运行次数必须大于0")
    mode_value = ROGUELIKE_MODES.get(str(mode or "Exp").strip().lower())
    if not mode_value:
        raise ValueError(f"不支持的肉鸽模式: {mode}")
    is_exp = mode_value == "Exp"
    is_monthly = mode_value == "Squad"
    is_deep = mode_value == "Exploration"
    _set_enabled_tasks(cfg, {"Roguelike"})
    task = next(t for t in _task_queue(cfg) if t.get("TaskType") == "Roguelike")
    task.update({
        "Theme": _resolve_roguelike_theme(theme),
        "Difficulty": difficulty,
        "Mode": mode_value,
        # 深入调查由具体调查条目提供预设分队。强塞普通探索分队会让
        # MAA 在只有预设分队可选时无限横向扫描，永远无法开局。
        "Squad": "" if is_deep else str(squad or "远程战术分队"),
        "SquadCollectible": "" if is_deep else str(squad or "远程战术分队"),
        "Roles": str(roles or "稳扎稳打"),
        "StartCount": starts_count,
        "CoreChar": str(core_char or ""),
        # 用户已确认前瞻性投资及古堡笔记等级均已完成。后续肉鸽的
        # 目标是尚未领取的实际奖励，不再在商店消耗源石锭定投。
        "Investment": False,
        "InvestWithMoreScore": False,
        "MonthlySquadAutoIterate": is_monthly,
        "MonthlySquadCheckComms": is_monthly,
        "DeepExplorationAutoIterate": is_deep,
        # This is irrelevant outside FindPlaytime mode, but the WPF property is
        # a non-null enum.  An empty string is treated as invalid and triggers
        # fault-tolerant configuration recovery during MAA startup.
        "FindPlaytimeTarget": "Ling",
        "UseSupport": False,
        "UseSupportNonFriend": False,
        "RefreshTraderWithDice": False,
        "StopWhenDepositFull": False,
        "StopAtFinalBoss": False,
        # “刷等级/经验”不等于“等级一满就结束队列”。长期肉鸽仍需继续
        # 普通探索来解锁结局、调查和主题能力；若这里为 True，MAA 会在
        # StartExplore 前直接禁用任务，监督器只能收到空的队列完成事件。
        "StopWhenLevelMax": False,
        "StartWithSeed": False,
        "Seed": "",
    })
    return task


def _roguelike_core_params(
    theme,
    difficulty=2147483647,
    starts_count=1,
    core_char="维什戴尔",
    squad="远程战术分队",
    roles="稳扎稳打",
    mode="Exp",
    use_foldartal=None,
):
    """Build the official MaaCore Roguelike payload.

    ``use_foldartal`` is a Core-only option in MAA 6.16.8: the WPF task
    serializer does not forward it. Keep the direct-Core path explicit so a
    value written only to gui.new.json can never masquerade as effective.
    """
    canonical = _resolve_roguelike_theme(theme)
    mode_value = ROGUELIKE_MODES.get(str(mode or "Exp").strip().lower())
    if mode_value not in ROGUELIKE_CORE_MODE_IDS:
        raise ValueError(f"不支持的肉鸽模式: {mode}")
    difficulty = int(difficulty)
    starts_count = int(starts_count)
    if difficulty < 0:
        raise ValueError("肉鸽难度不能小于0")
    if starts_count < 1:
        raise ValueError("肉鸽运行次数必须大于0")
    if use_foldartal is not None and canonical != "Sami":
        raise ValueError("use_foldartal仅适用于Sami主题")

    is_deep = mode_value == "Exploration"
    params = {
        "theme": canonical,
        "mode": ROGUELIKE_CORE_MODE_IDS[mode_value],
        "difficulty": difficulty,
        "starts_count": starts_count,
        "squad": "" if is_deep else str(squad or "远程战术分队"),
        "roles": str(roles or "稳扎稳打"),
        "core_char": str(core_char or ""),
        "investment_enabled": False,
        "investment_with_more_score": False,
        "stop_when_investment_full": False,
        "stop_at_final_boss": False,
        "stop_at_max_level": False,
        "use_support": False,
        "use_nonfriend_support": False,
        "refresh_trader_with_dice": False,
        "monthly_squad_auto_iterate": mode_value == "Squad",
        "monthly_squad_check_comms": mode_value == "Squad",
        "deep_exploration_auto_iterate": is_deep,
    }
    if use_foldartal is not None:
        params["use_foldartal"] = bool(use_foldartal)
    return params


def _run_mumu(*args, timeout=30):
    """统一执行MuMu CLI；其JSON/中文输出按UTF-8解码，避免系统GBK误解码。"""
    return subprocess.run(
        [MUMU_CLI, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def resolve_mumu_instance():
    """以mumu-cli登记信息为准，统一CLI、ADB和MAA实例号。

    MuMu升级后桌面编号0可能对应内部实例1。不能把桌面编号、内部编号
    和MAA实例号各自硬编码；这里唯一解析一次，后续全流程复用结果。
    """
    global MUMU_VM_INDEX
    try:
        r = _run_mumu("info", "-v", "all", timeout=10)
        if r.returncode != 0 or not (r.stdout or "").strip():
            return None
        entries = json.loads(r.stdout)
        if not isinstance(entries, dict) or not entries:
            return None

        display_index = os.environ.get("ARK_MUMU_DISPLAY_INDEX", "0").strip() or "0"
        candidates = [str(item) for item in entries.keys()]
        selected = None
        for key, item in entries.items():
            if isinstance(item, dict) and str(item.get("name", "")).endswith(
                f"-{display_index}"
            ):
                selected = str(key)
                break
        if selected is None and len(candidates) == 1:
            selected = candidates[0]
        if selected is None:
            for key, item in entries.items():
                if isinstance(item, dict) and item.get("is_main") is True:
                    selected = str(key)
                    break
        if selected is None:
            selected = sorted(candidates, key=lambda x: int(x) if x.isdigit() else 9999)[0]

        changed = selected != MUMU_VM_INDEX
        MUMU_VM_INDEX = selected
        if changed:
            log(
                f"  [MuMu] 实例号统一: 桌面编号{display_index} → "
                f"内部实例{selected}"
            )
        return selected
    except Exception as exc:
        log(f"  [MuMu] 解析内部实例失败: {exc}", "WARN")
        return None


def start_log_viewer(log_file=None, status_file=None, title=None, status_text=None):
    """非阻塞启动实时日志悬浮窗；窗口自身使用命名互斥锁保证单实例。"""
    viewer = os.path.join(SCRIPT_DIR, "log_viewer.py")
    if not os.path.exists(viewer):
        log("  ⚠️ log_viewer.py不存在，跳过日志窗", "WARN")
        return False
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    env = os.environ.copy()
    env["ARKNIGHTS_AUTO_BASE"] = BASE
    if log_file:
        env["ARKNIGHTS_LOG_FILE"] = os.path.abspath(str(log_file))
    if status_file:
        env["ARKNIGHTS_STATUS_FILE"] = os.path.abspath(str(status_file))
    if title:
        env["ARKNIGHTS_LOG_TITLE"] = str(title)
    if status_text:
        env["ARKNIGHTS_STATUS_TEXT"] = str(status_text)
    try:
        stop_file = os.path.join(BASE, "outputs", "log_viewer.stop")
        if os.path.exists(stop_file):
            os.remove(stop_file)
        subprocess.Popen(
            [pythonw, viewer],
            cwd=SCRIPT_DIR,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log("  🪟 已请求启动实时日志悬浮窗")
        return True
    except Exception as e:
        log(f"  ⚠️ 启动日志悬浮窗失败: {e}", "WARN")
        return False


def stop_log_viewer():
    """通知独立日志窗自行退出，不粗暴结束其他Python进程。"""
    try:
        path = os.path.join(BASE, "outputs", "log_viewer.stop")
        pid_path = os.path.join(BASE, "outputs", "log_viewer.pid")
        with open(path, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())
        for _ in range(20):
            if not os.path.exists(pid_path):
                log("  ✅ 实时日志窗已关闭")
                return True
            # 日志窗可能随父终端异常退出，来不及在 finally 中删除 PID
            # 文件。旧 PID 不是残留窗口证据；先确认该 PID 是否真实存活，
            # 已退出就清理陈旧记录，避免收尾阶段持续误报。
            try:
                with open(pid_path, "r", encoding="ascii") as pid_file:
                    raw_pid = pid_file.read().strip()
                viewer_pid = int(raw_pid)
            except (OSError, ValueError):
                viewer_pid = 0
            if viewer_pid <= 0 or not _local_process_pid_exists(viewer_pid):
                try:
                    os.remove(pid_path)
                except FileNotFoundError:
                    pass
                log("  ✅ 实时日志窗已退出，陈旧PID记录已清理")
                return True
            time.sleep(0.25)
        log("  ⚠️ 实时日志窗收到关闭通知后仍未退出", "WARN")
        return False
    except Exception as e:
        log(f"  ⚠️ 无法关闭实时日志窗: {e}", "WARN")
        return False


def _local_process_pid_exists(pid):
    """只读确认本机 PID 是否仍存在；用于识别日志窗的陈旧 PID 文件。"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except (AttributeError, OSError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False

def log(msg, level="INFO"):
    """统一日志输出"""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}][{level}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "gbk"
        print(line.encode(encoding, errors="replace").decode(encoding), flush=True)
    # 同时写入日志文件
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass


def _close_maacore_screenshot_bridge():
    """释放无界面截图控制器，给MAA GUI或其他MaaCore任务让出连接。"""
    global _MAACORE_SCREENSHOT_BRIDGE
    bridge = _MAACORE_SCREENSHOT_BRIDGE
    _MAACORE_SCREENSHOT_BRIDGE = None
    if bridge is not None:
        try:
            bridge.close()
        except Exception:
            pass


def _capture_with_maacore(path):
    """用MaaCore官方MuMu增强截图保存一帧；失败时由调用方回退ADB。"""
    global _MAACORE_SCREENSHOT_BRIDGE, _MAACORE_SCREENSHOT_FALLBACK_WARNED
    if SCRIPT_SCREENSHOT_BACKEND != "maacore" or os.name != "nt":
        return False
    # MAA GUI/任务链拥有控制器时不创建第二个MaaCore连接；战斗期仍使用原
    # ADB低频截图。脚本导航阶段无需打开MAA.exe，即可使用增强截图。
    if _maa_process_ids():
        _close_maacore_screenshot_bridge()
        return False
    try:
        if (
            _MAACORE_SCREENSHOT_BRIDGE is None
            or _MAACORE_SCREENSHOT_BRIDGE.address != DEVICE
        ):
            _close_maacore_screenshot_bridge()
            enhanced_adb = os.path.join(MUMU_INSTALL_ROOT, "nx_main", "adb.exe")
            if not os.path.isfile(enhanced_adb):
                enhanced_adb = ADB
            _MAACORE_SCREENSHOT_BRIDGE = MaaCoreScreenshotBridge(
                install_root=os.path.dirname(MAA_PATH),
                adb_path=enhanced_adb,
                address=DEVICE,
                emulator_path=MUMU_INSTALL_ROOT,
                # MaaCore user dir is transient runtime state, not project
                # evidence. Keep it under an ASCII-safe temp path because the
                # WorkBuddy Python launcher can garble non-ASCII cwd strings.
                user_dir=os.path.join(tempfile.gettempdir(), "arknights_auto_maacore"),
            )
        _MAACORE_SCREENSHOT_BRIDGE.capture_png(path)
        _RUN_SUMMARY["script_screencap"] = {
            "backend": "maacore_mumu_enhanced",
            "status": "captured",
            "address": DEVICE,
        }
        return True
    except Exception as exc:
        _close_maacore_screenshot_bridge()
        if not _MAACORE_SCREENSHOT_FALLBACK_WARNED:
            log(f"  ⚠️ MaaCore增强截图不可用，回退ADB: {exc}", "WARN")
            _MAACORE_SCREENSHOT_FALLBACK_WARNED = True
        _RUN_SUMMARY["script_screencap"] = {
            "backend": "adb_fallback",
            "status": "fallback",
            "reason": str(exc),
        }
        return False

def shot(name="s"):
    """优先MaaCore无界面增强截图；MAA占用或失败时回退ADB。"""
    global _SHOT_COUNT
    _SHOT_COUNT += 1
    # 纳秒后缀避免同一秒内同名截图互相覆盖；定期做有界清理，避免长跑膨胀。
    path = os.path.join(SCREEN_DIR, f"{name}_{time.time_ns()}.png")
    for attempt in range(3):
        if not _capture_with_maacore(path):
            with open(path, "wb") as f:
                subprocess.run(
                    [ADB, "-s", DEVICE, "exec-out", "screencap", "-p"],
                    stdout=f,
                    timeout=10,
                )
        # 验证图片完整性
        try:
            from PIL import Image
            with Image.open(path) as img:
                img.verify()  # 验证文件是否完整并立即释放文件句柄
            if _SHOT_COUNT % NAV_DEBUG_PRUNE_EVERY == 0:
                _prune_nav_debug()
            return path
        except Exception as e:
            if attempt < 2:
                wait(1)
                continue
            # 最后一次失败: 返回一个空白色图片路径而不是crash
            log(f"  ⚠️ 截图失败({name}): {e}", "WARN")
            # 创建1x1白色占位图
            try:
                from PIL import Image as _Img
                _Img.new('RGB', (1,1), (255,255,255)).save(path)
            except: pass
            return path
    return path

_ocr_engine = None
def ocr(path):
    """OCR识别, 返回 [(text, cx, cy), ...]"""
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    result, _ = _ocr_engine(path)
    items = []
    if result:
        for r in result:
            if len(r) >= 3:
                text = str(r[1]).strip()
                box = r[0]
                cx = int((box[0][0] + box[2][0]) / 2)
                cy = int((box[0][1] + box[2][1]) / 2)
                items.append((text, cx, cy))
    return items

def ocr_text(path):
    """OCR纯文本"""
    return " ".join(t for t, _, _ in ocr(path))

def find_text(items, keyword, exact=False):
    """在OCR结果中找文字, 返回(cx, cy)或None"""
    for text, cx, cy in items:
        if exact:
            if text == keyword:
                return (cx, cy)
        else:
            if keyword in text:
                return (cx, cy)
    return None


def _find_stage_node_text(items, stage_name):
    """只返回章节地图的真实关卡标签，排除“通关X后解锁”等说明文字。"""
    target = re.sub(r"\([^)]*\)", "", str(stage_name or "")).strip().upper()
    if not target:
        return None
    pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(target)}(?!\d)", re.I)
    candidates = []
    for item in items or []:
        if not isinstance(item, tuple) or len(item) < 3:
            continue
        text, x, y = str(item[0]).strip(), item[1], item[2]
        if not pattern.search(text.upper()):
            continue
        # 第17章左上角长期显示“通关17-4后解锁”。旧包含匹配会反复点击
        # 这条说明，既进不了详情也找不到真正节点。
        if any(marker in text for marker in ("通关", "解锁", "开放")):
            continue
        compact = re.sub(r"\s+", "", text.upper())
        score = 0 if compact == target else 1
        candidates.append((score, -int(y), (x, y)))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def _find_episode_position(items, chapter, chapter_name="", min_y=320, max_y=920):
    """在主题曲卡片或概览底栏中容错定位 EP。

    实机中 ``EP`` 与数字经常被拆成两个 OCR 项，章节中文名也常有一个字
    误识别。这里仅在章节卡片的纵向区域内做有限模糊匹配，避免把正文数字
    当成章节入口。
    """
    chapter = int(chapter)
    candidates = []
    ep_tokens = []
    for item in items or []:
        if not isinstance(item, tuple) or len(item) < 3:
            continue
        text, x, y = str(item[0]).strip(), int(item[1]), int(item[2])
        if not (min_y <= y <= max_y):
            continue
        compact = re.sub(r"[^A-Z0-9\u4e00-\u9fff]", "", text.upper())
        if re.search(rf"EP0*{chapter}(?!\d)", compact):
            return (x, y)
        if re.fullmatch(rf"0*{chapter}", compact):
            candidates.append((x, y))
        if compact == "EP":
            ep_tokens.append((x, y))
        if chapter_name:
            chinese = re.sub(r"[^\u4e00-\u9fff]", "", text)
            if chapter_name in chinese:
                return (x, y)
            if len(chinese) >= 3 and SequenceMatcher(None, chinese, chapter_name).ratio() >= 0.60:
                return (x, y)
    for x, y in candidates:
        if any(abs(x - ex) <= 100 and abs(y - ey) <= 100 for ex, ey in ep_tokens):
            return (x, y)
    return None

def tap(x, y):
    """ADB点击"""
    subprocess.run([ADB, "-s", DEVICE, "shell", "input", "tap", str(x), str(y)], timeout=5)

def swipe(x1, y1, x2, y2, dur=500):
    """ADB滑动；把 Android 输入拒绝作为可观测失败返回。"""
    try:
        result = subprocess.run(
            [ADB, "-s", DEVICE, "shell", "input", "swipe",
             str(x1), str(y1), str(x2), str(y2), str(dur)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        log(f"  ⚠️ ADB滑动执行异常: {exc}", "WARN")
        return False
    output = " ".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode != 0 or "INJECT_EVENTS" in output or "SecurityException" in output:
        detail = re.sub(r"\s+", " ", output)[:240] or f"exit={result.returncode}"
        log(f"  ⚠️ ADB滑动被拒绝: {detail}", "WARN")
        return False
    return True

def back():
    """返回键"""
    subprocess.run([ADB, "-s", DEVICE, "shell", "input", "keyevent", "4"], timeout=5)

def wait(t):
    """等待"""
    time.sleep(t)

# ============================================================
# 状态检测
# ============================================================

def confirm_by_screenshot(tag="confirm", expected_keywords=None, retries=3, interval=2):
    """不确定时用截图确认 (用户2026-06-29要求: 不确定时截图确认, 检查核对用图像识别)

    多次截图+OCR, 用expected_keywords验证当前画面是否符合预期。
    每次截图保存到nav_debug目录供事后核查, 避免盲目操作。

    Args:
        tag: 截图标签(用于文件名)
        expected_keywords: 预期出现的关键词列表, None则只截图不验证
        retries: 重试次数
        interval: 每次间隔秒数
    Returns:
        (matched, text) — 是否匹配预期, 最后一次OCR文本
    """
    last_text = ""
    for i in range(retries):
        p = shot(f"{tag}_{i}")
        last_text = ocr_text(p)
        if expected_keywords:
            if any(k in last_text for k in expected_keywords):
                log(f"  [截图确认] ✅ 匹配预期 ({tag})")
                return True, last_text
            else:
                log(f"  [截图确认] 第{i+1}/{retries}次未匹配预期, OCR: {last_text[:60]}...")
        wait(interval)
    if expected_keywords:
        log(f"  [截图确认] ⚠️ {retries}次均未匹配预期 ({tag})")
    return False, last_text


def get_state():
    """检测当前游戏状态, 返回状态名"""
    p = shot("state")
    t = ocr_text(p)

    # 战斗已经结束、MAA也已完成时，神经网络同步失败对话框会完全遮住结算页。
    # 它既不是战斗失败，也不是未知页面；必须先于所有背景语义单独识别，
    # 否则监督器会在这里无意义等待五分钟。
    if (
        "战斗记录" in t
        and ("未能成功同步" in t or "是否重试" in t)
        and ("错误号" in t or "重试" in t)
    ):
        return "battle_record_sync_error"

    # 理智恢复窗覆盖在章节地图/关卡详情之上，背景仍包含OPERATION；必须
    # 先识别遮罩，否则恢复逻辑会把被弹窗拦截的点击当成地图操作成功。
    if "使用药剂恢复" in t and "使用至纯源石恢复" in t:
        return "sanity_restore"

    # 登录公告覆盖层会透出章节地图的OPERATION/关卡编号；若晚于chapter_map
    # 判断，就会在公告上反复执行章节导航。只用三个稳定页签中至少两个确认。
    announcement_markers = sum(k in t for k in ("活动公告", "系统公告", "资讯速报"))
    if announcement_markers >= 2:
        return "announcement"

    # 月度签到是独立全屏覆盖层，背景会透出主页或章节文字；它既不是
    # 通用reward，也不会自行消失。必须在通用页面分类之前单独识别，
    # 否则主线恢复会把它当unknown空等15轮后才偶然由goto_main兜底。
    if "签到" in t and any(k in t for k in ("常规配给", "已签到", "加急许可")):
        return "monthly_sign_in"

    if "沙洲遗闻" in t and any(k in t for k in ["开始演算", "继续演算", "繁荣馈赠", "见闻陈列"]):
        return "reclamation_tales_main"
    if "生息演算" in t and "集成战略" in t and "长期探索" in t:
        return "longterm_exploration"
    if "RECLAMATION" in t.upper() and "沙洲遗闻" in t and "进入主题" in t:
        return "reclamation_theme_list"

    # 保全派驻从设置页到阶段详情页都属于一个未结束的独立任务。阶段详情
    # 会显示“结束委托”而不是“离开任务”，且背景也包含 OPERATION；若不先
    # 分类，会被后面的章节地图规则吞掉，回主页时在错误位置反复点击。
    if (
        any(marker in t for marker in ("离开任务", "结束委托"))
        and any(
            marker in t
            for marker in (
                "首批作战小队选任", "选择定向导能元件", "战术装备",
                "快捷编队", "开始部署", "暂停任务", "当前进度",
            )
        )
    ):
        return "sss_intermediate"

    # 基建内部页面不要求先退回主页；MAA Infrast正是从这里继续接管。
    # 必须早于通用页面判断，避免把仍可操作的基建现场当成unknown等待240秒。
    if "控制中枢" in t and "进驻总览" in t:
        return "base"

    # UserDataUpdate 会把游戏停在仓库总览。该页不是游戏未启动，更不能
    # 重新 monkey 后原地空等；最终日常应先从这里真实返回主页再交给 MAA。
    if (
        sum(marker in t for marker in ("基础物品", "消耗物品", "养成材料")) >= 2
        and any(marker in t for marker in ("仓库", "全部", "物品"))
    ):
        return "depot"

    # 基建房间详情不会显示“控制中枢/进驻总览”，但仍是 MAA Infrast
    # 可以直接接管的基建内部页面。搓玉配方切换后脚本会停在贸易站或制造站
    # 详情；若把它归为 unknown，定向 Infrast 会先空等 240 秒。
    if (
        re.search(r"(?:贸易站|制造站)[A-Z]\d{3}", t)
        and any(marker in t for marker in (
            "设施信息", "进驻信息", "设施列表", "生产份数", "获取订单中",
        ))
    ):
        return "base"

    # 顶部房屋按钮展开的快捷导航会透出终端背景及 ATTENTION 文本；遮罩
    # 自身的“首页+终端+基建+公开招募...”语义必须拥有最高优先级。
    quick_nav_kw = ["首页", "终端", "基建", "公开招募", "采购中心", "档案"]
    if "首页" in t and "终端" in t and sum(k in t for k in quick_nav_kw) >= 4:
        return "quick_nav_overlay"

    # 第17章实机章节地图的左侧标题固定为“共享终端 / 用物清单”，这不是
    # 普通终端列表。必须在通用终端规则之前识别，否则17-4结算后明明已经
    # 回到17章地图，脚本仍会退出重进并把已通关关卡当作导航失败。
    if (
        "共享终端" in t
        and "用物清单" in t
        and "OPERATION" in t.upper()
        and re.search(r"\b17-\d{1,2}\b", t, re.I)
    ):
        return "chapter_map"

    # 终端右侧的每周剿灭卡固定显示“合成玉/0/1800”，必须先用终端
    # 的 ATTENTION / TO-DO LIST 语义分类，避免把终端首页当剿灭地图。
    if any(k in t for k in ["ATTENTION", "SUDESTORY", "TO-DO LIST"]) or \
       ("终端" in t and ("进度" in t or "EP" in t)):
        return "terminal_list"

    # 剿灭作战进度奖励清单会透出背景中的“剿灭委托/每周报酬/合成玉”，
    # 必须先于普通剿灭页分类。新剿灭首通后实机中文界面没有 COMPLETE，
    # 稳定语义是“多个已完成待收集的任务+一键领取”或多条“单次作战达到”。
    if (
        ("当前有多个已完成待收集的任务" in t and "一键领取" in t)
        or (t.count("单次作战达到") >= 2 and "领取" in t)
    ):
        return "annihilation_reward_overlay"

    # 终端“常态事务”同时展示剿灭合成玉与保全派驻。因为含“合成玉”，若
    # 不先单独分类会被通用 reward 规则吞掉，回主页逻辑只会反复点空白。
    if (
        "AFFAIR RECORD" in t.upper()
        or ("请确认当前待办事务" in t and "剿灭作战" in t and "保全派驻" in t)
    ):
        return "routine_tasks"

    # 剿灭结算页本身包含“合成玉”，必须先于通用reward判定。
    # 0714实机证据：若把该页误判为reward，脚本会反复点击页面下方，永远无法离开剿灭。
    if (
        ("剿灭委托" in t and ("每周报酬" in t or "作战进度" in t))
        or ("每周报酬" in t and "合成玉" in t and re.search(r"\d+\s*/\s*1800", t))
        or ("委托剩余" in t and "情报汇总" in t)
    ):
        return "annihilation_page"
    if "COMPLETE" in t and any(k in t for k in ["单次作战达到", "歼灭数", "领取"]):
        return "annihilation_reward_overlay"

    # H关失败结算同样显示“行动结束/MISSION RESULTS”，但会明确返还理智。
    # 必须先判失败，避免把失败页写成首次通关并反复补打。
    if "理智返还" in t:
        return "defeat"
    # 🔴 战斗结算/失败 优先于编队 (结算页可能有"可以使用代理指挥了"提示)
    if any(k in t for k in ["行动结束", "MISSION RESULTS", "首次掉落", "已同步"]):
        return "victory"
    if any(k in t for k in ["MISSION FAILED", "任务失败"]):
        return "defeat"
    # 🔴 2026-07-01 修复: reward判断收紧, "物资"单独出现不算(关卡详情页也有掉落预览)
    # 必须有"至纯源石"或"合成玉"(结算页特有), 或"获得"+"物资"同时出现
    if (
        "至纯源石" in t
        or "合成玉" in t
        or ("获得" in t and "物资" in t)
        # 活动任务首次领取角色时先播放角色/信物展示，再显示“获得物资”
        # 汇总页。前一页没有通用的“获得物资”，但“重复获得+信物/凭证”
        # 是稳定且足够窄的奖励语义；必须先归类为 reward 才能逐页关闭。
        or ("重复获得" in t and any(k in t for k in ("信物", "高级凭证", "资质凭证")))
    ):
        return "reward"

    # 编队界面 (快捷编队/助战干员/代理指挥)
    if any(k in t for k in ["快捷编队", "助战干员", "SUPPORT", "SUPPORTUNIT"]):
        return "formation"
    # 关卡详情也同时有“代理指挥+开始行动”，不能据此冒充编队页。
    if "代理指挥" in t and any(k in t for k in ["快捷编队", "助战干员", "部署", "COST"]):
        return "formation"
    # 🔴 2026-07-02 修复: 干员培养页面检测 (OCR: "等级 稀有度 信赖值 ALL 轻触右侧干员以查看详情")
    # 之前"干员"在main_menu特征词中, 导致干员培养页被误判为main_menu
    if any(k in t for k in ["干员培养", "轻触右侧干员", "信赖值"]) or \
       ("等级" in t and "稀有度" in t and "信赖值" in t):
        return "operator_page"
    # 肉鸽/特殊作战结算页必须点左上角退出按钮，Android back 在此页无效。
    if ("目标生命值" in t and "本次作战" in t) or "成功通过" in t:
        return "roguelike_result"
    # 任务奖励页可能叠着主页的径向菜单；必须先于main_menu判定，否则理智
    # OCR会把遮罩后的画面当作已经回到主页。
    if any(k in t for k in ["日常任务", "主线任务", "周常任务", "特勤任务", "reward set", "点击领取"]):
        return "task_page"
    # 章节地图顶部房屋按钮先展开径向快捷导航，并不会立即回到真正主页。
    # 该遮罩同时包含终端/基建/招募等主界面关键词，必须先于main_menu识别。
    # 快捷导航已在终端/奖励规则之前识别；这里不再重复判定。
    # 🔴 2026-07-02 修复: main_menu特征词去掉"干员"(太宽泛), 改用更精确的特征
    # 主界面必须同时有"终端"和至少2个其他主界面特征词
    main_menu_kw = ["终端", "基建", "采购中心", "公开招募", "仓库", "寻访"]
    main_menu_matched = sum(1 for k in main_menu_kw if k in t)
    if "终端" in t and main_menu_matched >= 2:
        return "main_menu"
    # 兼容: 如果没有"终端"但有3个以上其他主界面特征词, 也判定为main_menu
    if main_menu_matched >= 3:
        return "main_menu"
    # 关卡详情抽屉仍会透出底层地图的OPERATION和多个节点编号。必须先用
    # 详情页独有控件分类，否则第17章险地/沙盘会被吞成chapter_map，随后
    # 在已经打开的详情页上反复点击节点文字，最终误报“地图无法定位”。
    if _is_stage_detail_text(t):
        return "stage_detail"
    if any(k in t for k in ["OPERATION", "通关", "观看序曲", "当前进度", "本章节回想"]):
        return "chapter_map"
    if any(k in t for k in ["ENEMY", "COST", "剩余可放置"]):
        return "battle"
    if any(k in t for k in ["行动结束", "MISSION RESULTS", "首次掉落", "已同步"]):
        return "victory"
    if any(k in t for k in ["MISSION FAILED", "任务失败"]):
        return "defeat"
    # 活动大厅英文 HOLOGRAPHIC 含有子串 LOG；只接受独立单词LOG。
    if any(k in t for k in ["自动OFF", "跳过", "SKIP", "幕间"]) or \
       re.search(r'(?<![A-Z])LOG(?![A-Z])', t.upper()):
        return "story"
    # 🔴 2026-07-01 修复: 这里也不再用宽泛的"获得"/"物资"判断reward
    if "至纯源石" in t or "合成玉" in t:
        return "reward"
    # 基建退出确认文字包含“设置”，必须先于通用settings判定。
    if "确认离开罗德岛基建" in t or "是否确认离开罗德岛基建" in t:
        return "base_exit_dialog"
    if any(k in t for k in ["设置", "重置设置", "账户"]):
        return "settings"
    # Act II 章节选择页 ("Main Story/主题曲/为了明日" + 大卡片列表)
    if any(k in t for k in ["Main Story", "主题曲", "乐章收录"]) or \
       ("为了明日" in t and ("STORMWATCH" in t or "SHATTERPOINT" in t)):
        return "act2_select"
    # 终端列表页已在通用reward规则之前识别；这里不再重复判定。
    # 章节概览页 (有剧情描述 + "前往章节" 按钮)
    if "前往章节" in t or (any(k in t for k in ["小丘郡的混战", "罗德岛", "遗去的人"]) and "EP" in t):
        return "chapter_overview"
    # 🔴 Android桌面/启动器检测 (2026-06-28: 游戏未启动时在桌面循环)
    # 桌面特征: 搜索栏/每日新发现/游戏中心/应用图标等
    if any(k in t for k in ["每日新发现", "搜索", "游戏中心", "森空岛", "设置", \
                               "浏览器", "微信", "热门应用", "推荐应用"]):
        return "home_screen"
    if any(k in t for k in ["登录", "START", "账号"]) and \
       not any(k in t for k in ["终端", "基建", "采购中心", "编队", "公开招募", "仓库", "寻访", "任务"]):
        return "login"
    # 弹窗/对话框检测 (退出确认/公告/提示框等)
    # 🔴 关键: 之前漏检导致"是否确认退出游戏"弹窗一直返回unknown
    if any(k in t for k in ["是否确认退出", "确认退出游戏", "退出游戏?"]):
        return "exit_dialog"
    if any(k in t for k in ["公告", "活动公告", "更新日志"]):
        return "announcement"
    if any(k in t for k in ["网络连接断开", "神经网络连接丢失", "重新连接", "网络异常"]):
        return "network_error"
    return "unknown"

def _recognize_terminal_stamina_digits(roi_path):
    """绕过文字检测框，直接识别主页理智卡片的大号数字行。"""
    global _ocr_engine
    try:
        import numpy as np
        from PIL import Image

        if _ocr_engine is None:
            ocr(roi_path)
        with Image.open(roi_path) as source:
            rgb = source.convert("RGB")
            width, height = rgb.size
            digit_line = rgb.crop((
                int(width * 0.29), int(height * 0.09),
                int(width * 0.855), int(height * 0.56),
            ))
        bgr = np.asarray(digit_line)[:, :, ::-1].copy()
        recognized, _ = _ocr_engine.text_recognizer(bgr)
        for raw_text, score in recognized or []:
            digits = "".join(re.findall(r"\d", str(raw_text)))
            confidence = float(score)
            if digits and confidence >= 0.45:
                value = int(digits)
                if 0 <= value <= 300:
                    return {
                        "value": value,
                        "text": str(raw_text),
                        "score": confidence,
                    }
    except Exception as exc:
        log(f"  [理智] 大号数字行直读失败: {exc}", "WARN")
    return None


def get_stamina():
    """获取当前理智值
    
    🔴 2026-07-10 根源修复: 只截右上角理智区域OCR, 不截全屏
    之前OCR全屏→日期/时间/其他数字被正则误匹配→理智值错误
    
    理智显示位置: 主界面右上角, 格式"XXX/210"
    """
    from PIL import Image
    for retry in range(3):
        p = shot(f"sta_{retry}")
        t_full = ocr_text(p)
        # 关卡详情/地图同样会显示明确的“x/210”。先读取这一强格式，
        # 不要为了追求主页上下文而把已经识别出的最终理智丢掉。
        ratio_match = re.search(r'(?<!\d)(\d{1,3})\s*/\s*210(?!\d)', t_full)
        if ratio_match:
            val = int(ratio_match.group(1))
            if 0 <= val <= 300:
                checked = _validate_stamina_ocr_against_event_checkpoint(val)
                if checked is not None:
                    log(f"  [理智] 从明确比例读取: {checked}/210")
                    return checked

        # 新主页皮肤会把大号理智数值与小号“理智/210”拆成两个OCR文本块，
        # 全屏文本因此可能是“196 … 理智/210”而不是“196/210”。只在终端卡片
        # 的固定ROI内读取，避免把上方日期、合成玉或源石数量误当理智。
        try:
            with Image.open(p) as source:
                width, height = source.size
                stamina_roi = source.crop((
                    int(width * 0.54), int(height * 0.16),
                    int(width * 0.72), int(height * 0.41),
                ))
                roi_path = os.path.join(BASE, "runtime_screenshots", f"sta_roi_{retry}.png")
                stamina_roi.save(roi_path)
            roi_text = ocr_text(roi_path)
            roi_ratio = re.search(r'(?<!\d)(\d{1,3})\s*(?:\+\s*)?(?:理智\s*)?/\s*210(?!\d)', roi_text)
            if roi_ratio:
                val = int(roi_ratio.group(1))
                if 0 <= val <= 300:
                    checked = _validate_stamina_ocr_against_event_checkpoint(val)
                    if checked is not None:
                        log(f"  [理智] 从主页终端卡片读取: {checked}/210")
                        return checked
            # 新皮肤的大号个位数可能没有检测框，但下方“理智/210”仍清晰。
            # 只有固定ROI已经证明它是理智卡片时才直读数字行，避免误取日期。
            normalized_roi_text = re.sub(r"\s+", "", roi_text)
            if "/210" in normalized_roi_text or (
                "理智" in normalized_roi_text and "210" in normalized_roi_text
            ):
                direct = _recognize_terminal_stamina_digits(roi_path)
                if direct is not None:
                    checked = _validate_stamina_ocr_against_event_checkpoint(direct["value"])
                    if checked is not None:
                        log(
                            "  [理智] 从主页卡片数字行直读: "
                            f"{checked}/210 (raw={direct['text']}, confidence={direct['score']:.2f})"
                        )
                        return checked
        except Exception as exc:
            log(f"  [理智] 主页终端卡片ROI读取失败: {exc}", "WARN")
        # 验证在主界面
        if "终端" not in t_full and retry < 2:
            log(f"  [理智] 截图无'终端'关键字, 不在主界面, 尝试回主界面(第{retry+1}次): {t_full[:40]}")
            goto_main_menu()
            wait(2)
            continue
        
        # 🔴 2026-07-10: 用上下文匹配 "终端 数字 当前"
        # 理智大数字是图形渲染, 裁剪OCR读不到, 但全屏OCR能读到
        # 模式: "终端 210 当前" → 提取210
        # "终端 数字 当前" 或 "终端 数字" (当前可能不显示)
        m = re.search(r'终端\s*(\d+)', t_full)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 300:
                checked = _validate_stamina_ocr_against_event_checkpoint(val)
                if checked is not None:
                    return checked
            else:
                log(f"  [理智] OCR值{val}超出范围(0-300), 忽略: {t_full[:60]}")

        # fallback: "数字 当前 ... 理智"
        m2 = re.search(r'(\d+)\s*当前.*?理智', t_full)
        if m2:
            val = int(m2.group(1))
            if 0 <= val <= 300:
                return val
        
        if retry < 2:
            log(f"  [理智] OCR未识别(第{retry+1}次): {t_full[:60]}")
            state = get_state()
            if state != "main_menu":
                goto_main_menu()
            wait(2)
    log(f"  [理智] 3次OCR均失败, 返回None", "WARN")
    return None

def _capture_stamina_observation(phase, navigate=True):
    """读取游戏实时理智并写入本轮证据账本；失败时保持unknown。"""
    observations = _RUN_SUMMARY.setdefault("stamina_observations", {})
    record = {
        "phase": str(phase),
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "source": "game_screen_ocr",
        "value": None,
        "verified": False,
    }
    try:
        if navigate and not goto_main_menu():
            record["reason"] = "main_menu_not_confirmed"
        else:
            value = get_stamina()
            if isinstance(value, int):
                record.update({"value": value, "max": 210, "verified": True})
                log(f"  [日报理智实证] {phase}: {value}/210")
            else:
                record["reason"] = "stamina_ocr_failed"
                log(f"  [日报理智实证] {phase}: OCR未确认", "WARN")
    except Exception as exc:
        record["reason"] = f"{type(exc).__name__}: {exc}"
        log(f"  [日报理智实证] {phase}: {record['reason']}", "WARN")
    observations[str(phase)] = record
    return record


# ============================================================
# 导航函数
# ============================================================

def _chapter_numbers_from_text(text):
    """从章节地图OCR提取关卡前缀；同时支持11-14与H11-4。"""
    numbers = []
    for match in re.finditer(r'(?<![A-Z0-9])H?(\d{1,2})\s*[-—]\s*\d{1,2}(?!\d)', text or "", re.I):
        value = int(match.group(1))
        if 0 <= value <= 99:
            numbers.append(value)
    return numbers


def _is_stage_detail_text(text):
    return any(marker in (text or "") for marker in (
        "开始行动", "开始作战", "敌方情报", "推荐平均等级", "演习", "报酬",
    ))


def _normalize_full_chapter_map(tag="normalize_map"):
    """确保离开关卡详情抽屉，处于能看到多个节点和EPISODE切换器的完整地图。"""
    for attempt in range(3):
        p = shot(f"{tag}_{attempt}")
        text = ocr_text(p)
        numbers = _chapter_numbers_from_text(text)
        # 右侧详情抽屉展开时，底层章节地图仍可见且可直接操作其它节点。
        # 同章至少两个节点是地图上下文的直接证据，不应为了关抽屉退回主页重走导航。
        if numbers and max(numbers.count(n) for n in set(numbers)) >= 2:
            return True
        if _is_stage_detail_text(text):
            log("  [章节地图] 仅检测到单关详情，按back恢复地图节点")
            back()
            wait(3)
            continue
        if numbers:
            return True
        wait(2)
    return False


def _verify_target_chapter_map(ch, tag="chapter_verify", retries=2):
    """严格确认当前是目标章节地图，不以页面类型或章节名片段代替。"""
    for attempt in range(retries):
        if get_state() != "chapter_map":
            return False
        p = shot(f"{tag}_{attempt}")
        text = ocr_text(p)
        numbers = _chapter_numbers_from_text(text)
        if ch in numbers and numbers.count(ch) >= 2:
            log(f"  [章节确认] 目标第{ch}章，地图节点前缀={numbers}（允许右侧详情抽屉）")
            return True
        if _is_stage_detail_text(text):
            log("  [章节确认] 当前是关卡详情页，不视为完整章节地图", "WARN")
            return False
        if ch in numbers:
            log(f"  [章节确认] 目标第{ch}章，识别关卡前缀={numbers}")
            return True
        log(f"  [章节确认] 目标第{ch}章但识别前缀={numbers}; OCR={text[:80]}", "WARN")
        if attempt + 1 < retries:
            wait(2)
    return False


def _detect_current_chapter(tag="chapter_detect"):
    """从当前章节地图的关卡编号判断章节；返回None表示无法确认。"""
    if get_state() != "chapter_map":
        return None
    if not _normalize_full_chapter_map(f"{tag}_normalize"):
        return None
    text = ocr_text(shot(tag))
    numbers = _chapter_numbers_from_text(text)
    if not numbers:
        return None
    # 地图可能同时出现多个同章关卡，取出现次数最多的章节号。
    return max(set(numbers), key=lambda value: (numbers.count(value), value))


def _read_episode_nav(tag="episode_nav"):
    """只扫描右下角章节导航ROI，返回{章节号: 全屏点击坐标}。"""
    from PIL import Image
    full_path = shot(tag)
    left, top, right, bottom = 1400, 880, 1880, 1080
    crop_path = os.path.join(SCREEN_DIR, f"{tag}_roi.png")
    with Image.open(full_path) as image:
        crop = image.crop((left, top, right, bottom))
        try:
            crop.save(crop_path)
        finally:
            crop.close()

    positions = {}
    items = ocr(crop_path)
    for item in items:
        if not isinstance(item, tuple) or len(item) < 3:
            continue
        text, x, y = str(item[0]).strip(), item[1], item[2]
        match = re.fullmatch(r'(\d{1,2})', text)
        if match:
            chapter = int(match.group(1))
            positions[chapter] = (left + x, top + y)
    log(f"  [右下角章节导航] 识别={positions}")
    return positions


def _enter_chapter_from_overview(ch, tag="overview_resume"):
    """若当前是目标章节概览，点击右下角“前往章节”；否则返回None。"""
    name = CHAPTER_NAMES.get(ch, "")
    p = shot(tag)
    items = ocr(p)
    text = ocr_text(p)
    compact = re.sub(r'\s+', '', text)
    identity_ok = (name and name in text) or f"EP{ch}" in compact
    if not identity_ok:
        return None
    go_pos = find_text(items, "前往章节", exact=False) or find_text(items, "前往", exact=False)
    if not go_pos:
        go_pos = POS_GO_CHAPTER
    log(f"  [章节概览] 已确认{name}/EP{ch}，点击前往章节 @{go_pos}")
    tap(*go_pos)
    wait(5)
    return _verify_target_chapter_map(ch, f"{tag}_final", retries=3)


def _navigate_to_older_chapter(target_ch, max_steps=10):
    """利用地图右下角“上一EPISODE”逐章回退，并逐步验证结果。"""
    if not _normalize_full_chapter_map("episode_chain_normalize"):
        log("  [章节链] 无法进入完整章节地图", "ERROR")
        return False
    current = _detect_current_chapter("episode_chain_start")
    if current is None or current <= target_ch:
        return current == target_ch

    for step in range(max_steps):
        if current == target_ch:
            return True
        if current < target_ch:
            return False

        nav = _read_episode_nav(f"episode_chain_{current}")
        previous = current - 1
        if previous not in nav:
            log(f"  [章节链] 严格顺序要求{current}→{previous}，但右下角未识别到{previous}: {nav}", "WARN")
            return False

        switched = False
        for click_attempt in range(3):
            tap(*nav[previous])
            wait(5)
            after_nav = _read_episode_nav(f"episode_chain_after_{previous}_{click_attempt}")
            # 切换成功后，中间“当前进度”数字应变成previous。
            if previous in after_nav:
                # 用完整地图编号再做一次最终确认，避免只看导航条误判。
                new_current = _detect_current_chapter(f"episode_chain_map_after_{previous}")
                if new_current == previous:
                    switched = True
                    break
            log(f"  [章节链] 点击{click_attempt+1}次后尚未切到{previous}章，原地重试", "WARN")
            nav = after_nav or nav
        if not switched:
            log(f"  [章节链] 期望进入{previous}章，3次点击均未确认，停止", "ERROR")
            return False
        log(f"  [章节链] {current}章 → {new_current}章 ✅")
        current = new_current

    return current == target_ch

def _dismiss_announcement_overlay():
    """Close the full-screen login announcement only after semantic confirmation.

    Android back does not close this overlay.  The 1920x1080 live layout has a
    circular X in the top-right corner; requiring two stable tab labels keeps
    the coordinate fallback from being used on unrelated pages.
    """
    p = shot("announcement_overlay")
    text = ocr_text(p)
    markers = sum(k in text for k in ("活动公告", "系统公告", "资讯速报"))
    if markers < 2:
        log("  [回主界面] 公告页语义未确认，拒绝点击右上角关闭", "WARN")
        return False
    tap(1807, 105)
    log("  [回主界面] 已关闭登录公告覆盖层")
    wait(3)
    return True


def _dismiss_reward_overlay_for_main_menu():
    """按奖励页真实控件退出，而不是把所有 reward 都当成点空白可关闭。"""
    p = shot("reward_overlay_for_main")
    text = ocr_text(p)
    if "签到" in text and any(k in text for k in ("常规配给", "已签到", "加急许可")):
        # 月度签到日历的唯一关闭控件是右上角圆形 X。
        tap(1820, 105)
        log("  [回主界面] 已关闭月度签到奖励页")
        wait(3)
        return True
    tap(*POS_DISMISS)
    wait(2)
    return True


def goto_main_menu():
    """返回主界面 (从编队/详情页用back键, 不用home键避免触发退出确认框)
    
    🔴 2026-07-02 修复: 增加operator_page(干员培养页)检测和回退逻辑
    之前干员培养页被get_state误判为main_menu, 导致goto_main_menu直接返回
    """
    annihilation_reward_opened = False
    annihilation_claim_all_attempted = False
    for _ in range(15):
        state = get_state()
        if state == "main_menu":
            # 🔴 2026-07-02 二次验证: 确保真的在主界面(有终端入口)
            p = shot("verify_main")
            t = ocr_text(p)
            if "终端" in t:
                log("✅ 主界面")
                return True
            else:
                # get_state误判, 实际不在主界面, 用back键退出
                log(f"  [回主界面] get_state=main_menu但OCR无'终端', 实际可能在其他页面")
                back()
                wait(2)
                continue
        if state == "base_exit_dialog":
            p = shot("base_exit_confirm")
            text = ocr_text(p)
            if "离开罗德岛基建" not in text:
                log("  [回主界面] 基建离开弹窗语义未确认，拒绝点击", "ERROR")
                return False
            # 1920x1080实机：确认是弹窗下半区右侧红底白色勾；只有精确文字成立才点。
            tap(1265, 742)
            log("  [回主界面] 已确认离开罗德岛基建")
            wait(4)
        elif state == "announcement":
            if not _dismiss_announcement_overlay():
                back()
                wait(2)
        elif state == "monthly_sign_in":
            _dismiss_reward_overlay_for_main_menu()
        elif state == "annihilation_reward_overlay":
            # 首通会一次解锁多档作战进度奖励。清单中的每行“领取”不能被当成
            # 页面底部入口重复点击；优先只执行一次“一键领取”，处理完奖励展示
            # 后再用返回键收起清单。
            p = shot("annihilation_reward_overlay")
            items = ocr(p)
            claim_all = find_text(items, "一键领取", exact=False)
            if claim_all and not annihilation_claim_all_attempted:
                annihilation_claim_all_attempted = True
                log(f"  [回主界面] 一键领取剿灭作战进度奖励 @{claim_all}")
                tap(*claim_all)
                wait(4)
            else:
                log("  [回主界面] 收起剿灭作战进度奖励清单")
                back()
                wait(3)
        elif state == "annihilation_page":
            p = shot("annihilation_leave")
            items = ocr(p)
            claim = find_text(items, "领取", exact=True)
            if claim and not annihilation_reward_opened:
                annihilation_reward_opened = True
                log(f"  [回主界面] 打开剿灭作战进度奖励清单 @{claim}")
                tap(*claim)
                wait(3)
            else:
                log("  [回主界面] 从剿灭页面点击顶部房屋图标")
                tap(*POS_TOP_HOME)
                wait(3)
        elif state in (
            "terminal_list", "act2_select", "chapter_overview", "chapter_map",
            "stage_detail", "task_page", "routine_tasks",
        ):
            # 这些页面都有经过实机确认的顶部房屋图标，直接回主页比多层back稳定。
            tap(*POS_TOP_HOME)
            wait(3)
        elif state == "quick_nav_overlay":
            p = shot("quick_nav_home")
            items = ocr(p)
            home_pos = find_text(items, "首页", exact=True) or find_text(items, "首页")
            if not home_pos:
                log("  [回主界面] 快捷导航已确认但未定位首页，拒绝盲点", "ERROR")
                return False
            tap(*home_pos)
            log(f"  [回主界面] 快捷导航 → 首页 @{home_pos}")
            wait(4)
        elif state in ("victory", "reward"):
            _dismiss_reward_overlay_for_main_menu()
        elif state == "roguelike_result":
            # 0717实机“成功通过/目标生命值/本次作战”页只有左上角退出有效。
            tap(65, 55)
            wait(3)
        elif state == "sss_intermediate":
            p = shot("main_leave_sss")
            if not _leave_sss_intermediate(p, "main_leave_sss"):
                log("  [回主界面] 无法结束当前保全委托，停止盲目返回", "ERROR")
                return False
        elif state == "formation":
            # 编队界面用back键退出到关卡详情, 再back到章节地图
            back()
            wait(2)
        elif state == "operator_page":
            # 🔴 2026-07-02 新增: 干员培养页面用back键退出
            log("  [回主界面] 当前在干员培养页, 按back退出")
            back()
            wait(2)
        else:
            # 其他页面用back键 (不用POS_HOME_BTN, 那个会触发退出确认框)
            back()
            wait(2)
            # 检查是否弹出"退出游戏"确认框
            t = ocr_text(shot("check_exit"))
            if "退出" in t and "确认" in t:
                # 用back键取消退出确认框
                back()
                wait(2)
    # 最后兜底再试一次
    state = get_state()
    if state == "main_menu":
        p = shot("verify_main_final")
        t = ocr_text(p)
        if "终端" in t:
            log("✅ 主界面")
            return True
    log("❌ 无法回主界面", "ERROR")
    return False

def goto_chapter(ch):
    """导航到指定章节地图。

    已在完整章节地图时，可优先使用右下角严格连续的EPISODE链。
    根本路径固定为：主页→终端→左下角曲谱→主题曲→章节概览→前往章节。
    终端中间卡片只是“上次主题曲位置”快捷入口，禁止用于指定章节导航。
    """
    name = CHAPTER_NAMES.get(ch, "")
    log(f"→ 第{ch}章 {name} (正统4步+快捷入口)")

    # 支持从已经打开的目标章节概览继续，不退回主页重走流程。
    overview_result = _enter_chapter_from_overview(ch, "goto_chapter_overview_resume")
    if overview_result is not None:
        return overview_result

    # 已在章节地图且是正确章节就不用动
    if get_state() == "chapter_map":
        if _verify_target_chapter_map(ch, "cur_ch"):
            log(f"✅ 已在第{ch}章地图")
            return True
        current_ch = _detect_current_chapter("cur_ch_detect")
        if current_ch and current_ch > ch:
            ok = _navigate_to_older_chapter(ch)
            if ok:
                log(f"✅ 已通过EPISODE章节链切换到第{ch}章")
                return True
            log(f"  [章节导航] 右下角严格章节链在{current_ch}→{current_ch-1}处中断，改走终端曲谱根本路径", "WARN")
        else:
            log(f"  [章节导航] 当前章节={current_ch}，改走终端曲谱根本路径", "WARN")

    # 🔴 2026-07-02 修复: 如果在其他章节地图, 必须先回主界面再重新导航
    # 之前只检查chapter_map状态, 没检查是否是正确章节, 导致在第10章地图找11-2

    # Step 0: 回主界面
    if not goto_main_menu():
        return False

    # ===== Step 1: 主界面 → 点右上角 "终端" =====
    # 用OCR动态定位"终端"文字位置 (比硬编码坐标更可靠)
    log("  [Step1] 主界面 → 终端入口")
    p1 = shot("step1_find_terminal")
    items1 = ocr(p1)
    terminal_pos = find_text(items1, "终端")
    if terminal_pos:
        tap(*terminal_pos)
        log(f"  [Step1] OCR定位终端 @{terminal_pos}")
    else:
        # 兜底: 用固定坐标
        tap(*POS_TERMINAL)
        log(f"  [Step1] 固定坐标 {POS_TERMINAL}")
    wait(3)

    # ===== 检测当前页面状态 =====
    p = shot("after_terminal")
    items = ocr(p)
    txt = ocr_text(p)

    # ===== 快捷路径A: 已删除 (2026-07-01) =====
    # 快捷入口"前往上一次作战"进入的是上一次打的关卡地图(如10-11),
    # 不是目标关卡地图(如10-12), back退回后还是在错误关卡地图上找关卡,
    # 必然失败。彻底删除, 永远走标准4步流程。

    # ===== Step 2: 终端首页 → 点击左下角“曲谱” =====
    log("  [Step2] 终端首页 → 点击左下角曲谱")
    p_term = shot("terminal_home")
    items_term = ocr(p_term)
    score_pos = find_text(items_term, "曲谱", exact=False)
    if not score_pos or score_pos[1] < 850:
        score_pos = (470, 1000)  # 图1红框中心
    tap(*score_pos)
    wait(4)
    log(f"  ✅ 已点击曲谱 @{score_pos}")

    # ===== Step 3: 主题曲卡片页 → 选择目标中文名；找不到可先点任意章节 =====
    log(f"  [Step3] 主题曲界面 → 找 [{name}] / EP{ch}")
    pos3 = None
    fallback_card = None
    selected_target_directly = False
    p = None
    txt = ""
    # 最多四步向新章节方向搜索，再用四步回到初始视口。0717旧实现横滑24次，
    # 最后却点击第一次截图保存的陈旧坐标，EP13实际变成了EP00。
    act2_swipes = [(1500, 540, 350, 540, 800)] * 4 + [(350, 540, 1500, 540, 800)] * 4
    for attempt in range(len(act2_swipes) + 1):
        p = shot(f"act2_search_{attempt}")
        items = ocr(p)
        txt = ocr_text(p)
        pos3 = _find_episode_position(items, ch, name, min_y=320, max_y=920)
        # 坐标只属于当前截图；每次横滑后必须覆盖，绝不复用旧视口坐标。
        fallback_card = None
        for fallback_ch, chapter_name in CHAPTER_NAMES.items():
            candidate = _find_episode_position(items, fallback_ch, chapter_name, min_y=320, max_y=920)
            if candidate:
                fallback_card = candidate
                break
        if pos3:
            tap(*pos3)
            wait(4)
            selected_target_directly = True
            log(f"  ✅ 主题曲搜索{attempt}次后选择 [{name}] @{pos3}")
            break
        if attempt < len(act2_swipes):
            swipe(*act2_swipes[attempt])
            wait(2)
    if not pos3:
        if not fallback_card:
            log(f"  ❌ 主题曲界面未找到任何章节卡片", "ERROR")
            return False
        tap(*fallback_card)
        wait(4)
        log(f"  ⚠️ 未直接找到{name}，先进入任意章节概览 @{fallback_card}")

    # ===== Step 3B: 章节概览底部EP数组 → 校准到目标章节 =====
    overview_ok = False
    # 概览页不在主体区域滑动；只能点击底部可见的EP章节标签进行切换。
    overview_swipes = [] if selected_target_directly else []
    for attempt in range(len(overview_swipes) + 1):
        p_overview = shot(f"overview_select_{attempt}")
        items_overview = ocr(p_overview)
        text_overview = ocr_text(p_overview)
        compact_overview = re.sub(r'\s+', '', text_overview)
        overview_go = (find_text(items_overview, "前往章节", exact=False)
                       or find_text(items_overview, "前往", exact=False))
        overview_target_pos = _find_episode_position(
            items_overview, ch, name, min_y=780, max_y=1075,
        )
        identity_ok = (
            name in text_overview
            or re.search(rf"EP\s*0*{ch}(?!\d)", text_overview, re.I) is not None
            or _find_episode_position(items_overview, ch, name, min_y=80, max_y=760) is not None
        )
        # 已从主题曲页直接点击目标中文名时，概览身份识别到中文名或EP任一即可；
        # 最终仍由进入地图后的关卡前缀做强校验。
        if identity_ok and (overview_go or selected_target_directly):
            overview_ok = True
            break
        target_pos = overview_target_pos
        if target_pos and target_pos[1] >= 780:
            tap(*target_pos)
            wait(3)
            continue
        # 目标未直接选中时，只允许点击当前可见的底部EP标签，不做主体横滑。
    if not overview_ok:
        log(f"  ❌ 章节概览底部未能校准到{name}/EP{ch}", "ERROR")
        return False

    # ===== Step 4: 章节概览页 → 点 "前往章节" =====
    # 概览页特征: 左侧有剧情描述文字 + EP编号 + 章节名, 右下角有"前往章节"按钮
    log("  [Step4] 概览页 → 前往章节")
    p = shot("overview")
    items = ocr(p)
    txt = ocr_text(p)

    go_btn = find_text(items, "前往章节", exact=False) or find_text(items, "前往", exact=False)
    if go_btn:
        tap(*go_btn)
        wait(3)
        log(f"  ✅ 前往章节 @{go_btn}")
    else:
        # 只有概览页仍明确包含目标章节时才允许使用已验证坐标。
        target_mentioned = name in txt or f"EP{ch}" in txt.replace(" ", "")
        if not target_mentioned:
            log(f"  ❌ 概览页无法确认第{ch}章，拒绝固定坐标点击", "ERROR")
            return False
        tap(*POS_GO_CHAPTER)
        wait(3)
        log(f"  ⚠️ OCR未找到'前往', 使用固定坐标 {POS_GO_CHAPTER}")

    # 最终确认
    if _verify_target_chapter_map(ch, "final_map", retries=3):
        log(f"✅ 第{ch}章 {name} 地图到达并确认")
        return True

    final_state = get_state()
    txt_final = ocr_text(shot("final_map_failed"))
    log(f"⚠️ 最终章节确认失败: state={final_state}, OCR={txt_final[:80]}", "WARN")
    return False

def goto_terminal_main():
    """导航到终端主界面(资源关/剿灭入口)"""
    if get_state() != "main_menu":
        if not goto_main_menu():
            return False
    tap(*POS_TERMINAL)
    wait(3)
    p = shot("terminal_main")
    text = ocr_text(p)
    # 0714实机终端首页的稳定标题是英文ATTENTION / TO-DO LIST / MAIN THEME，
    # 中文“主线/剿灭/物资筹备”可能完全不出现。页面状态和这些版面词任一成立即可。
    terminal_markers = ["ATTENTION", "TO-DO LIST", "MAIN THEME", "SUDESTORY"]
    if get_state() == "terminal_list" or any(k in text for k in terminal_markers) or \
       any(k in text for k in ["物资筹备", "剿灭", "主线"]):
        log("✅ 终端主界面")
        return True
    log(f"❌ 未进入终端: OCR={text[:100]}", "ERROR")
    return False


def goto_reclamation_tales_main():
    """导航到沙洲遗闻无存档主界面；MAA本身不提供这段导航。"""
    p = shot("ra_entry_probe")
    text = ocr_text(p)
    if "沙洲遗闻" in text and "开始演算" in text:
        log("✅ 已在沙洲遗闻无存档主界面（开始演算）")
        return True
    if "沙洲遗闻" in text and "继续演算" in text:
        log("❌ 检测到沙洲遗闻已有存档；无存档模式可能删除存档，拒绝启动", "ERROR")
        return False

    if not goto_terminal_main():
        return False

    # 0715实机：终端底部x=1435为“长期探索”。
    tap(1435, 1000)
    wait(4)
    p = shot("ra_longterm_exploration")
    items = ocr(p)
    text = ocr_text(p)
    if not ("集成战略" in text and "生息演算" in text):
        log(f"❌ 未进入长期探索页: OCR={text[:120]}", "ERROR")
        return False

    # 两张卡片都有“查看全部主题”；只接受右侧生息演算区域的按钮。
    view_all = next(
        ((x, y) for label, x, y in items if "查看全部主题" in label and x > 1000),
        None,
    )
    if not view_all:
        log("❌ 生息演算卡片未找到右侧‘查看全部主题’", "ERROR")
        return False
    tap(*view_all)
    wait(4)

    p = shot("ra_theme_list")
    items = ocr(p)
    text = ocr_text(p)
    enter_theme = find_text(items, "进入主题", exact=False)
    if "沙洲遗闻" not in text or not enter_theme:
        log(f"❌ 生息演算主题列表未识别到沙洲遗闻: OCR={text[:120]}", "ERROR")
        return False

    # 主题列表默认可能选中中间“重启锚点”；必须先点左侧沙洲遗闻卡。
    tales_card = next(
        ((x, y) for label, x, y in items if "沙洲遗闻" in label and x < 650),
        None,
    )
    if not tales_card:
        log("❌ 未找到左侧沙洲遗闻卡片，拒绝使用盲坐标", "ERROR")
        return False
    tap(*tales_card)
    wait(3)

    p = shot("ra_tales_selected")
    items = ocr(p)
    text = ocr_text(p)
    enter_theme = find_text(items, "进入主题", exact=False)
    if "沙洲遗闻" not in text or not enter_theme:
        log("❌ 沙洲遗闻卡片选中后页面身份未确认", "ERROR")
        return False
    tap(*enter_theme)

    for _ in range(8):
        wait(4)
        p = shot("ra_tales_main_wait")
        text = ocr_text(p)
        if "沙洲遗闻" in text and "开始演算" in text:
            log("✅ 已进入沙洲遗闻无存档主界面（开始演算）")
            return True
        if "沙洲遗闻" in text and "继续演算" in text:
            log("❌ 进入后发现已有存档；拒绝让MAA删除存档", "ERROR")
            return False
    log(f"❌ 进入沙洲遗闻后未出现‘开始演算’: OCR={text[:120]}", "ERROR")
    return False

# ============================================================
# 弹窗与剧情处理
# ============================================================

def handle_popups():
    """处理各种弹窗"""
    p = shot("popup")
    t = ocr_text(p)
    
    # 🔴 退出游戏确认弹窗 (2026-06-28修复: 之前漏检导致unknown死循环)
    if any(k in t for k in ["是否确认退出", "确认退出游戏", "退出游戏?"]):
        tap(665, 742)  # 07/30实机确认的取消按钮中心
        wait(2)
        return True

    # 每日首次登录配给：确认按钮位于屏幕下方中央。
    if "今日配给" in t or ("家具零件" in t and "配给" in t):
        tap(*POS_DISMISS)
        wait(2)
        log("  ✅ 已领取并关闭今日配给")
        return True

    if "签到" in t and any(k in t for k in ("常规配给", "已签到", "加急许可")):
        tap(1820, 105)
        wait(3)
        log("  ✅ 已关闭月度签到奖励页")
        return True

    # 观看序曲弹窗
    if "观看" in t and "序曲" in t:
        tap(960, 540)
        wait(1)
        return True
    
    # 难度兼容警告
    if any(k in t for k in ["高难", "兼容", "环境", "警告"]):
        pos = find_text(ocr(p), "确认") or (1500, 850)
        tap(*pos)
        wait(2)
        return True
    
    # 登录后的全屏公告已经连续多日出现。它必须点击右上角X，不能使用
    # 通用的屏幕下方关闭坐标；背景还会透出章节地图文字，因此只接受
    # 三个固定页签中至少两个作为直接证据。
    announcement_markers = sum(k in t for k in ("活动公告", "系统公告", "资讯速报"))
    if announcement_markers >= 2:
        tap(1807, 105)
        wait(3)
        log("  ✅ 已关闭登录公告覆盖层")
        return True
    
    return False

def skip_story():
    """跳过剧情；优先识别确认按钮，固定坐标只作安全回退。"""
    p = shot("story")
    t = ocr_text(p)
    if "跳过" in t or "SKIP" in t.upper():
        tap(*POS_SKIP)
        wait(1)
        confirm_image = shot("story_skip_confirm")
        confirm_items = ocr(confirm_image)
        confirm = (
            find_text(confirm_items, "确认", exact=True)
            or find_text(confirm_items, "确定", exact=True)
            or find_text(confirm_items, "CONFIRM", exact=True)
            or find_text(confirm_items, "YES", exact=True)
        )
        # 明日方舟的剧情确认框没有“确认”文字，而是“是否跳过剧情？”右侧的
        # 圆形对勾。OCR 能稳定读到问题文字时，从文字中心向右推导按钮位置；
        # OCR 漏字时再使用同一 1920x1080 界面的实机回退点。
        if not confirm:
            prompt = (
                find_text(confirm_items, "是否跳过剧情", exact=False)
                or find_text(confirm_items, "跳过剧情", exact=False)
            )
            if prompt:
                from PIL import Image
                width, height = Image.open(confirm_image).size
                confirm = (min(width - 80, prompt[0] + int(width * 0.125)), prompt[1])
        if confirm:
            tap(*confirm)
        else:
            # 旧版剧情确认框OCR偶尔完全漏字，保留经过实机验证的回退点。
            tap(*POS_SKIP_CONFIRM)
        wait(5)
        return True
    return False


def _leave_story_before_daily(max_attempts=8):
    """最终日常启动前安全退出遗留剧情，不在未知页面盲点。"""
    for attempt in range(max_attempts):
        state = get_state()
        if state != "story":
            return state
        log(f"  [daily] 检测到活动/战后剧情，先跳过再交接MAA ({attempt + 1}/{max_attempts})")
        if not skip_story():
            # 状态分类已经由“跳过/幕间/独立LOG”等剧情语义确认；OCR偶尔会漏掉
            # 右上角按钮，但此时仍只点经过验证的固定跳过坐标及确认坐标。
            tap(*POS_SKIP)
            wait(1)
            tap(*POS_SKIP_CONFIRM)
            wait(5)
        else:
            wait(2)
    return get_state()

def dismiss_reward():
    """关闭奖励界面 — 点一次就够, 点多了会弹回主页"""
    state = get_state()
    if state == "chapter_map":
        return True
    if state in ("victory", "reward"):
        p = shot("dismiss_reward")
        t = ocr_text(p)
        if "获得物资" in t or "至纯源石" in t or "合成玉" in t:
            items = ocr(p)
            pos = find_text(items, "确定") or find_text(items, "确认")
            if pos:
                tap(*pos)
            else:
                tap(*POS_DISMISS)
        else:
            tap(*POS_DISMISS)
        wait(3)  # 等动画播完, 只点一次
        return True
    return True  # 其他状态不点, 直接返回


def _drain_reward_sequence(max_steps=5):
    """关闭连续奖励展示，直到回到非奖励页；每一页都重新图形分类。"""
    dismissed = 0
    for _ in range(max_steps):
        state = get_state()
        if state not in ("victory", "reward"):
            break
        tap(*POS_DISMISS)
        dismissed += 1
        wait(3)
    if dismissed:
        log(f"  [奖励页] 已连续关闭{dismissed}层奖励展示")
    return dismissed

# ============================================================
# 通关确认 (六芒星填充验证)
# ============================================================

def _stage_marker_cyan_ratio(image, pos, save_path=None):
    """截取关卡文字左侧的节点图标，返回青蓝填充占比。"""
    x, y = pos
    left, top, right, bottom = x - 145, y - 50, x - 55, y + 50
    if left < 0 or top < 0 or right > image.width or bottom > image.height:
        return None
    crop = image.crop((left, top, right, bottom)).convert('RGB')
    if save_path:
        crop.save(save_path)
    pixels = list(crop.getdata())
    if not pixels:
        return None
    cyan_count = sum(
        1 for r, g, b in pixels
        if b > 150 and g > 100 and r < 120
    )
    return cyan_count / len(pixels)


def _chapter17_node_completion_status(image, pos, save_path=None):
    """区分第17章沙盘关的最终完成节点与未闭环节点。

    2026-08-21实机复核：17-9/17-11最终完成节点是红紫色外环加亮色中心；
    17-10只完成常规时是灰色外环加灰色中心。单看中性亮色会把灰色节点、
    白色连线和关卡文字一起误判为完成，所以最终完成必须同时命中红紫外环
    和中心亮块。这个函数只用于CHAPTER17_SANDBOX_STAGES。
    """
    if isinstance(image, (str, os.PathLike)):
        from PIL import Image
        image = Image.open(image).convert("RGB")
    else:
        image = image.convert("RGB")
    x, y = pos
    left, top, right, bottom = x - 145, y - 50, x - 55, y + 50
    if left < 0 or top < 0 or right > image.width or bottom > image.height:
        return None
    crop = image.crop((left, top, right, bottom))
    if save_path:
        crop.save(save_path)
    pixels = list(crop.getdata())
    if not pixels:
        return None
    core = crop.crop((30, 25, 60, 75))
    core_pixels = list(core.getdata())
    cyan_ratio = sum(
        1 for r, g, b in pixels
        if b >= 135 and g >= 85 and b >= r + 35 and g >= r + 15
    ) / len(pixels)
    white_ratio = sum(
        1 for r, g, b in pixels
        if min(r, g, b) >= 145 and max(r, g, b) - min(r, g, b) <= 38
    ) / len(pixels)
    completion_red_ratio = sum(
        1 for r, g, b in pixels
        if r >= 95 and r >= g * 1.35 and r >= b * 1.20
    ) / len(pixels)
    core_bright_neutral_ratio = sum(
        1 for r, g, b in core_pixels
        if min(r, g, b) >= 120 and max(r, g, b) - min(r, g, b) <= 45
    ) / max(1, len(core_pixels))
    # 真实样本：17-9/17-11红紫比例0.176/0.148；漏沙盘的17-10为0。
    # 保守阈值留出压缩、亮度和动画波动，但绝不再用白色比例单独判完成。
    if completion_red_ratio >= 0.06 and core_bright_neutral_ratio >= 0.20:
        state = "complete"
    elif (
        cyan_ratio >= 0.035
        or white_ratio >= 0.045
        or core_bright_neutral_ratio >= 0.15
    ):
        state = "risk_or_regular_only"
    else:
        state = "unknown"
    return {
        "state": state,
        "complete": state == "complete",
        "cyan_ratio": cyan_ratio,
        "white_ratio": white_ratio,
        "completion_red_ratio": completion_red_ratio,
        "core_bright_neutral_ratio": core_bright_neutral_ratio,
    }


def _stage_marker_dark_cube_ratio(image, pos):
    """返回节点ROI的中性深灰占比，仅作诊断，不能单独证明已通关。

    0718实机证明：未通关的平面暗六边形同样会得到很高的深灰占比；
    OCR错位时还可能把白色关卡标题卡与背景误算成深灰节点。
    """
    x, y = pos
    left, top, right, bottom = x - 145, y - 50, x - 55, y + 50
    if left < 0 or top < 0 or right > image.width or bottom > image.height:
        return None
    crop = image.crop((left, top, right, bottom)).convert('RGB')
    center = crop.crop((25, 25, 65, 75))
    center_pixels = list(center.getdata())
    all_pixels = list(crop.getdata())
    if not center_pixels or not all_pixels:
        return None
    neutral_dark = sum(
        1 for r, g, b in center_pixels
        if 20 <= r <= 95 and abs(r - g) < 18 and abs(g - b) < 18
    ) / len(center_pixels)
    white_outline = sum(1 for r, g, b in all_pixels if min(r, g, b) > 180) / len(all_pixels)
    return neutral_dark if white_outline >= 0.015 else 0.0


def _stage_marker_fill_features(image, pos):
    """读取六芒星内芯的纯色填充与黑色占比，颜色种类本身不作限制。

    后期章节会更换节点主题色；完美与否的稳定差异是内芯为纯色实心，
    而非完美/未通关节点保留大面积黑色。边框和地图背景不参与统计。
    """
    x, y = pos
    left, top, right, bottom = x - 145, y - 50, x - 55, y + 50
    if left < 0 or top < 0 or right > image.width or bottom > image.height:
        return None
    crop = image.crop((left, top, right, bottom)).convert("RGB")
    core = crop.crop((30, 25, 60, 75))
    pixels = list(core.getdata())
    if not pixels:
        return None
    black_ratio = sum(1 for rgb in pixels if max(rgb) < 90) / len(pixels)
    solid_color_ratio = sum(
        1
        for r, g, b in pixels
        if max(r, g, b) >= 105
        and (max(r, g, b) - min(r, g, b) >= 25 or min(r, g, b) >= 100)
    ) / len(pixels)
    return {
        "solid_color_ratio": solid_color_ratio,
        "black_ratio": black_ratio,
    }


def _stage_marker_orange_boss_ratio(image, pos):
    """返回章节终局橙色节点占比。

    13-21 等章节终局节点不用普通六芒星，而是在关卡文字左侧显示橙色
    首领徽记。它是“已解锁且可进入”的直接图形证据，不能因为普通节点
    的 cyan/dark 两项都为零就降级成未知状态。
    """
    x, y = pos
    left, top, right, bottom = x - 145, y - 50, x - 55, y + 50
    if left < 0 or top < 0 or right > image.width or bottom > image.height:
        return None
    pixels = list(image.crop((left, top, right, bottom)).convert("RGB").getdata())
    if not pixels:
        return None
    orange_count = sum(
        1 for r, g, b in pixels
        if r > 140 and 35 < g < 140 and b < 100 and r > g * 1.4
    )
    return orange_count / len(pixels)


def _stage_marker_status(image, pos, reference_ratio=0.186):
    """以纯色实心/黑色内芯判定完美；青蓝比例仅兼容旧章节。"""
    cyan_ratio = _stage_marker_cyan_ratio(image, pos)
    dark_fill_ratio = _stage_marker_dark_cube_ratio(image, pos)
    fill = _stage_marker_fill_features(image, pos)
    if cyan_ratio is None:
        return None
    threshold = max(0.15, float(reference_ratio or 0.186) * 0.85)
    solid_color_ratio = (fill or {}).get("solid_color_ratio", 0.0)
    black_ratio = (fill or {}).get("black_ratio", 1.0)
    pure_filled = solid_color_ratio >= 0.72 and black_ratio <= 0.22
    cleared = pure_filled or cyan_ratio >= 0.08
    return {
        "cleared": cleared,
        "perfect": pure_filled or (cleared and cyan_ratio >= threshold and black_ratio <= 0.35),
        "cyan_ratio": cyan_ratio,
        "dark_fill_ratio": dark_fill_ratio or 0.0,
        "solid_color_ratio": solid_color_ratio,
        "black_ratio": black_ratio,
        "perfect_threshold": threshold,
    }


DETAIL_BADGE_CHAPTERS = frozenset((15, 16, 17))


def _is_sandbox_score_overlay(text):
    """识别后期章节地图左下角的“推演分数”说明面板。"""
    compact = re.sub(r"\s+", "", str(text or ""))
    return (
        "推演分数" in compact
        and any(key in compact for key in ("沙盘推演", "绝境作战关卡", "当前得分"))
    )


def _open_late_chapter_stage_detail(pos, display_name, screenshot_prefix="detail"):
    """打开15~17章目标详情；误点推演分数面板时改点实际圆形节点。

    17-17一类特殊节点的OCR文字位于节点左下方，文字中心并不是可进入关卡的
    点击区域。只有截图OCR明确证明误入“推演分数”面板时，才回退并尝试
    右上方实际节点，避免把普通节点一律偏移。兼容原规则锚点：
    “回退后改点文字右上方真实节点”；新增第二候选只在第一候选仍未确认时使用。
    """
    x, y = pos
    # 第17章有少数标签贴在顶部快捷栏下方（实机17-15文字中心约
    # y=109）。直接点文字会展开“首页/终端/基建”快捷栏；圆形关卡节点
    # 实际在文字右侧。必须先在仍处于章节地图时点真实节点，不能误点后
    # 再Back——Back会退出到章节概览，使后续候选坐标全部失效。
    # 2026-08-19实机逐点验证：17-15文字中心约(490,109)，圆形节点中心
    # 约(595,100)。点圆心会命中右上角“i”说明，点左下边缘(565,144)
    # 已落在圆外；圆形底部内侧(595,125)可稳定打开详情。因此顶部节点
    # 使用“文字右105、下16”的内侧热区，不再做无效地图拖动。
    primary_pos = (min(1870, x + 105), min(260, y + 16)) if y < 180 else pos
    tap(*primary_pos)
    wait(3)
    detail_path = shot(f"{screenshot_prefix}_{display_name}")
    detail_text = ocr_text(detail_path)
    if _mainline_stage_detail_confirmed(detail_text, display_name):
        return detail_path, detail_text, True

    # 若不同缩放仍误中“i”说明，关闭后再次点击同一个已验证的底部内侧
    # 热区；不再使用已实证落在圆外的左下边缘。
    first_compact = re.sub(r"\s+", "", str(detail_text or ""))
    if y < 180 and "主线作战" in first_compact and "关闭" in first_compact:
        close_pos = find_text(ocr(detail_path), "关闭") or (235, 160)
        tap(*close_pos)
        wait(2)
        node_pos = (min(1870, x + 105), min(260, y + 16))
        tap(*node_pos)
        log(
            f"  [后期章节节点恢复] {display_name}误点信息按钮；"
            f"关闭说明后改点圆形节点底部内侧 @{node_pos}"
        )
        wait(3)
        detail_path = shot(f"{screenshot_prefix}_{display_name}_node_lower_left")
        detail_text = ocr_text(detail_path)
        if _mainline_stage_detail_confirmed(detail_text, display_name):
            return detail_path, detail_text, True

    compact = re.sub(r"\s+", "", str(detail_text or ""))
    map_or_top_overlay = any(
        marker in compact
        for marker in ("当前进度", "共享终端", "采购中心", "干员寻访", "基建")
    )
    if not (_is_sandbox_score_overlay(detail_text) or map_or_top_overlay):
        return detail_path, detail_text, False

    log(
        f"  [后期章节节点恢复] 点击{display_name}文字未进入详情；"
        "回退后依次探测文字右上方/右侧真实圆形节点"
    )
    back()
    wait(2)
    candidates = (
        (min(1870, x + 105), max(60, y - 40)),
        (min(1870, x + 105), max(60, y)),
    )
    for index, node_pos in enumerate(candidates, 1):
        tap(*node_pos)
        wait(3)
        detail_path = shot(f"{screenshot_prefix}_{display_name}_node{index}")
        detail_text = ocr_text(detail_path)
        detail_confirmed = _mainline_stage_detail_confirmed(detail_text, display_name)
        log(
            f"  [后期章节节点恢复] 实际节点候选{index}@{node_pos} "
            f"→ {'已确认详情' if detail_confirmed else '仍未确认详情'}"
        )
        if detail_confirmed:
            return detail_path, detail_text, True
        candidate_compact = re.sub(r"\s+", "", str(detail_text or ""))
        if any(marker in candidate_compact for marker in ("当前进度", "共享终端", "采购中心")):
            back()
            wait(2)
    return detail_path, detail_text, False


def _scored_chapter_detail_star_status(image):
    """Return late-chapter completion from the three detail-panel badges.

    Chapters 15+ have already produced incompatible or false-positive map-node
    colours (17-14 was advanced without a real clear).  Their authoritative
    pre-battle evidence is therefore the three cyan badges at the top-right of
    the opened stage detail panel.  The three fixed slots are deliberately
    checked independently so one or two lit badges cannot be mistaken for a
    perfect clear.
    """
    from PIL import Image

    if isinstance(image, (str, os.PathLike)):
        image = Image.open(image).convert("RGB")
    else:
        image = image.convert("RGB")
    legacy_boxes = (
        (1490, 120, 1590, 235),
        (1580, 120, 1680, 235),
        (1670, 120, 1770, 235),
    )
    # 2026-08-21实机第17章详情：徽记组整体右移约100px，已完成徽记为
    # 白色，未完成徽记位于暗红底板；旧章节/旧资源仍使用上面的蓝色布局。
    modern_boxes = (
        (1590, 120, 1695, 235),
        (1680, 120, 1785, 235),
        (1770, 120, 1880, 235),
    )
    modern_right_pixels = list(image.crop(modern_boxes[-1]).getdata())
    modern_dark_red = (
        sum(
            1 for r, g, b in modern_right_pixels
            if r > 45 and r > g * 1.4 and r > b * 1.2
        ) / len(modern_right_pixels)
    ) if modern_right_pixels else 0.0
    boxes = modern_boxes if modern_dark_red >= 0.20 else legacy_boxes
    ratios = []
    for box in boxes:
        crop = image.crop(box)
        pixels = list(crop.getdata())
        cyan_ratio = (
            sum(1 for r, g, b in pixels if b > 150 and g > 100 and r < 120)
            / len(pixels)
        ) if pixels else 0.0
        white_ratio = (
            sum(
                1 for r, g, b in pixels
                if r > 205 and g > 205 and b > 205
                and max(r, g, b) - min(r, g, b) < 30
            ) / len(pixels)
        ) if pixels else 0.0
        ratio = max(cyan_ratio, white_ratio)
        ratios.append(ratio)
    lit = sum(1 for ratio in ratios if ratio >= 0.12)
    return {
        "cleared": lit > 0,
        "perfect": lit == 3,
        "lit": lit,
        "ratios": ratios,
        "layout": "modern_white_red" if boxes is modern_boxes else "legacy_cyan",
    }

def verify_stage_cleared(ch, display_name, max_retry=3):
    """验证关卡是否真正通关: 检查章节地图上关卡节点的六芒星是否填充
    
    六芒星填充 = 已通关
    六芒星空心 = 未通关
    
    完美 vs 非完美:
    - 完美通关: 纯色六芒星 (平面、均匀颜色)
    - 非完美通关: 带阴影的立方体六芒星 (3D效果, 有亮面和暗面)
    
    原理: 通关后回到章节地图, 已通关的关卡节点六芒星会被填充
    返回: (cleared: bool, is_perfect: bool)
    """
    global _LAST_STAGE_MARKER_VERIFICATION
    _LAST_STAGE_MARKER_VERIFICATION = {
        "stage": display_name,
        "status": "checking",
    }
    log(f"  🔍 六芒星验证 {display_name}...")
    
    # 确保回到章节地图
    for _ in range(max_retry):
        state = get_state()
        if state == "chapter_map":
            break
        if state in ("victory", "reward"):
            tap(*POS_DISMISS)
            wait(2)
        elif state == "main_menu":
            if not goto_chapter(ch):
                _LAST_STAGE_MARKER_VERIFICATION["status"] = "navigation_failed"
                return (False, False)
        else:
            back()
            wait(2)
    else:
        log(f"  ⚠️ 无法回到章节地图验证", "ERROR")
        _LAST_STAGE_MARKER_VERIFICATION["status"] = "navigation_failed"
        return (False, False)
    
    # 找到目标关卡节点位置
    # 🔴 2026-07-10 修复: exact=True要求OCR完全匹配, 但OCR返回"12-11 OPERATION"≠"12-11"
    # 改为exact=False(包含匹配), 和_find_and_enter_stage一致
    map_search = re.sub(r'\([^)]*\)', '', display_name).strip()
    p = shot("verify_map")
    items = ocr(p)
    pos = _find_stage_node_text(items, map_search)
    if not pos:
        # 与进入关卡使用同一搜索策略，确保战前/战后取到的是同一节点。
        search_swipes = (
            [(1500, 500, 300, 500, 1200)] * 5 +
            [(960, 800, 960, 300, 1200)] * 3 +
            [(300, 500, 1500, 500, 1200)] * 5
        )
        for idx, swipe_args in enumerate(search_swipes):
            swipe(*swipe_args)
            wait(2)
            p = shot(f"verify_map_search_{idx}")
            items = ocr(p)
            pos = _find_stage_node_text(items, map_search)
            if pos:
                log(f"  [六芒星验证] 搜索{idx+1}次后找到{display_name}")
                break
    
    if not pos:
        log(f"  ⚠️ 找不到{display_name}节点, 无法验证", "ERROR")
        _LAST_STAGE_MARKER_VERIFICATION["status"] = "node_not_found"
        return (False, False)

    # 第17章沙盘关的详情三徽记只证明当前“险地作战”完成，不代表沙盘已经
    # 闭环。此处必须读取地图红紫外环+亮色中心；灰色/青蓝节点一律保留待办。
    if ch == 17 and _chapter17_stage_requires_sandbox(display_name):
        from PIL import Image
        final_status = _chapter17_node_completion_status(
            Image.open(p).convert("RGB"),
            pos,
            os.path.join(SCREEN_DIR, f"chapter17_final_{display_name}.png"),
        )
        if final_status:
            _LAST_STAGE_MARKER_VERIFICATION.update({
                "status": "verified",
                "cleared": final_status["complete"],
                "perfect": final_status["complete"],
                "chapter17_node_state": final_status["state"],
                "cyan_ratio": final_status["cyan_ratio"],
                "white_ratio": final_status["white_ratio"],
                "completion_red_ratio": final_status["completion_red_ratio"],
                "core_bright_neutral_ratio": final_status["core_bright_neutral_ratio"],
            })
            log(
                f"  [第17章最终节点] {display_name}: {final_status['state']}, "
                f"red_ring={final_status['completion_red_ratio']:.3f}, "
                f"bright_core={final_status['core_bright_neutral_ratio']:.3f}, "
                f"cyan={final_status['cyan_ratio']:.3f}"
            )
            return (final_status["complete"], final_status["complete"])
        _LAST_STAGE_MARKER_VERIFICATION["status"] = "chapter17_node_unknown"
        return (False, False)

    # 后期章节地图节点颜色已出现跨章节差异及17-14假阳性，不能再把地图像素
    # 当作最终通关证据。非沙盘特殊节点点开详情后，以右上角三枚独立蓝色徽记为准。
    if ch in DETAIL_BADGE_CHAPTERS:
        detail_path, detail_text, detail_confirmed = _open_late_chapter_stage_detail(
            pos, display_name, screenshot_prefix="chapter15_detail_verify",
        )
        if detail_confirmed:
            status = _scored_chapter_detail_star_status(detail_path)
            _LAST_STAGE_MARKER_VERIFICATION.update({
                "status": "verified",
                "cleared": status["cleared"],
                "perfect": status["perfect"],
                "detail_lit_badges": status["lit"],
            })
            log(
                f"  [推演章节详情徽记] {display_name}: lit={status['lit']}/3, "
                f"ratios={[round(v, 3) for v in status['ratios']]} "
                f"→ {'完美' if status['perfect'] else ('非完美' if status['cleared'] else '未通关')}"
            )
            return (status["cleared"], status["perfect"])
        log(f"  [推演章节详情徽记] 未确认详情页属于{display_name}", "WARN")
        back()
        wait(2)
        _LAST_STAGE_MARKER_VERIFICATION["status"] = "detail_unconfirmed"
        return (False, False)

    # 新判定：只分析关卡文字左侧节点图标，并使用同屏平面六边形作动态参照。
    # 11章实测：完美平面六边形cyan_ratio≈0.186；11-14立方体≈0.126。
    from PIL import Image
    img = Image.open(p).convert('RGB')
    marker_path = os.path.join(SCREEN_DIR, f"marker_{display_name}.png")
    target_ratio = _stage_marker_cyan_ratio(img, pos, marker_path)
    visible_ratios = []
    for item in items:
        if not isinstance(item, tuple) or len(item) < 3:
            continue
        text, sx, sy = str(item[0]).strip(), item[1], item[2]
        if not re.search(r'(?<!\d)(?:H)?\d{1,2}-\d{1,2}(?!\d)', text, re.I):
            continue
        ratio = _stage_marker_cyan_ratio(img, (sx, sy))
        if ratio is not None and ratio >= 0.08:
            visible_ratios.append(ratio)

    if target_ratio is None:
        log("  ⚠️ 节点图标ROI越界，无法确认完美度", "WARN")
        _LAST_STAGE_MARKER_VERIFICATION["status"] = "roi_invalid"
        return (False, False)
    reference_ratio = max(visible_ratios) if visible_ratios else 0.186
    marker = _stage_marker_status(img, pos, reference_ratio)
    cleared = marker["cleared"]
    is_perfect = marker["perfect"]
    _LAST_STAGE_MARKER_VERIFICATION.update({
        "status": "verified",
        "cleared": cleared,
        "perfect": is_perfect,
        "cyan_ratio": marker["cyan_ratio"],
        "solid_color_ratio": marker["solid_color_ratio"],
        "black_ratio": marker["black_ratio"],
    })
    log(
        f"  [节点ROI] solid_fill={marker['solid_color_ratio']:.3f}, "
        f"black={marker['black_ratio']:.3f}, target_cyan={marker['cyan_ratio']:.3f}, "
        f"dark_fill_diag={marker['dark_fill_ratio']:.3f}, flat_reference={reference_ratio:.3f}, "
        f"threshold={marker['perfect_threshold']:.3f} "
        f"→ {'完美' if is_perfect else ('非完美' if cleared else '未通关')}"
    )
    if not cleared:
        return (False, False)
    return (True, is_perfect)
    
    # 截取关卡节点周围区域分析六芒星
    # 六芒星通常在关卡文字上方或旁边
    x, y = pos
    # 截取节点周围 200x200 区域
    from PIL import Image
    img = Image.open(p)
    # 截取以节点为中心, 向上偏移(六芒星在文字上方)
    crop = img.crop((max(0, x-100), max(0, y-150), x+100, y+50))
    verify_path = os.path.join(SCREEN_DIR, f"star_{display_name}.png")
    crop.save(verify_path)
    
    # 分析颜色: 已通关节点有蓝色六边形/立方体
    # 🔴 2026-07-08 修复v2: 之前的逻辑只检测B>150的亮面像素, 暗面(B=80-120)被遗漏
    # 正确做法: 检测所有蓝色像素(B>40, B>R, B>G), 然后在其中分析亮度方差
    rgb_data = crop.convert('RGB').tobytes()
    hexagram_count = 0   # 金色像素
    bright_count = 0     # 高亮度
    blue_hex_count = 0   # 蓝色亮面像素 (B>150)
    all_blue_pixels = [] # 🔴 所有蓝色像素(含暗面), 用于方差分析
    
    for i in range(0, len(rgb_data), 3):
        r, g, b = rgb_data[i], rgb_data[i+1], rgb_data[i+2]
        brightness = (r + g + b) / 3
        # 金色六芒星: R和G都高, B较低
        if r > 180 and g > 160 and b < 120:
            hexagram_count += 1
        # 蓝色亮面 (已通关标识): B高, R低
        if b > 150 and r < 100 and g < 180:
            blue_hex_count += 1
        # 🔴 所有蓝色像素(含暗面): B>R, B>G, B>40 — 这是六芒星/立方体的完整范围
        if b > r and b > g and b > 40:
            all_blue_pixels.append(brightness)
        # 高亮度(任何颜色)
        if brightness > 180:
            bright_count += 1
    
    total = len(rgb_data) // 3
    hexagram_ratio = hexagram_count / total if total > 0 else 0
    bright_ratio = bright_count / total if total > 0 else 0
    blue_ratio = blue_hex_count / total if total > 0 else 0
    
    # 同时OCR节点周围看是否有"已通关"或三星标记
    crop_ocr_text = ocr_text(verify_path)
    
    # 🔴 完美 vs 非完美: 分析所有蓝色像素内部的亮度方差
    # 完美 = 纯色平面 → 所有蓝色像素亮度接近, 方差小
    # 非完美 = 立方体 → 有亮面(高亮度)和暗面(低亮度), 双峰分布, 方差大
    is_perfect = True
    dark_ratio_in_hex = 0
    brightness_std = 0
    if len(all_blue_pixels) > 20:
        avg_bright = sum(all_blue_pixels) / len(all_blue_pixels)
        variance = sum((v - avg_bright) ** 2 for v in all_blue_pixels) / len(all_blue_pixels)
        brightness_std = variance ** 0.5
        
        # 暗面 = 亮度显著低于平均值的像素(立方体阴影面)
        dark_in_hex = sum(1 for v in all_blue_pixels if v < avg_bright * 0.6)
        dark_ratio_in_hex = dark_in_hex / len(all_blue_pixels)
        
        # 判定: 标准差>35 或 暗面比>20% → 非完美(立方体效果)
        # 🔴 2026-07-10 旧方案废弃: std/dark_ratio被背景干扰, 不可靠
        # 🔴 2026-07-10 新方案: 对角色差检测
        # 完美=纯色六芒星(左下/右上无色差), 非完美=立方体(左下暗/右上亮)
        # i是RGB字节偏移，不是像素序号；必须先除以3再换算(x,y)。
        # 旧实现导致坐标错位约3倍，“左下/右上”实际取到了错误区域。
        blue_bright = []
        for i in range(0, len(rgb_data), 3):
            if rgb_data[i+2] > 150 and rgb_data[i] < 100:
                pixel_index = i // 3
                blue_bright.append((
                    pixel_index % crop.width,
                    pixel_index // crop.width,
                    rgb_data[i], rgb_data[i+1], rgb_data[i+2],
                ))
        if len(blue_bright) > 10:
            cx = sum(p[0] for p in blue_bright) / len(blue_bright)
            cy = sum(p[1] for p in blue_bright) / len(blue_bright)
            bl_vals = [p[4] for p in blue_bright if p[0] < cx - 5 and p[1] > cy + 5]  # 左下
            tr_vals = [p[4] for p in blue_bright if p[0] > cx + 5 and p[1] < cy - 5]  # 右上
            if bl_vals and tr_vals:
                bl_avg = sum(bl_vals) / len(bl_vals)
                tr_avg = sum(tr_vals) / len(tr_vals)
                diag_diff = abs(bl_avg - tr_avg)
                is_perfect = diag_diff < 20  # 色差<20=纯色=完美
                log(f"  [对角色差] 左下B={bl_avg:.0f}({len(bl_vals)}px) 右上B={tr_avg:.0f}({len(tr_vals)}px) 差={diag_diff:.0f} → {'完美' if is_perfect else '非完美'}")
            else:
                is_perfect = brightness_std < 35 and dark_ratio_in_hex < 0.20
                log("  [对角色差] 对角样本不足，回退到亮度方差+暗面比")
        else:
            # 蓝色样本不足时不能乐观标记完美；保守地判为非完美并保留补打机会。
            is_perfect = False
            log("  [对角色差] 蓝色样本不足，保守判为非完美", "WARN")
    
    log(f"  金色比={hexagram_ratio:.4f}, 蓝色比={blue_ratio:.4f}, 亮度比={bright_ratio:.2f}, 蓝色像素={len(all_blue_pixels)}, 标准差={brightness_std:.1f}, 暗面比={dark_ratio_in_hex:.3f}, OCR={crop_ocr_text[:30]}")
    
    # 判定: 蓝色六边形(>0.01) 或 金色六芒星(>0.02) 或 高亮度(>0.30) 或 OCR发现通关标记 → 已通关
    # 🔴 2026-07-10: 剧情关通关后六芒星在编号左侧(和战斗关一样), 下方叠加叶轮图标
    # 但叶轮图标本身是蓝绿色的(B>40), 会干扰all_blue_pixels计数
    # 正确判据: blue_ratio(B>150的亮面) > 0.01 = 有六芒星 = 已通关
    # 叶轮图标的B值<150, 不会影响blue_ratio
    cleared = (blue_ratio > 0.02 or hexagram_ratio > 0.02 or bright_ratio > 0.30 
               or "通关" in crop_ocr_text or "★" in crop_ocr_text)
    
    if not cleared:
        log(f"  ❌ 未检测到通关标识 (蓝色比={blue_ratio:.4f})")
        return (False, False)
    
    if is_perfect:
        log(f"  ✅ 完美通关 (蓝色比={blue_ratio:.4f}, 暗面比={dark_ratio_in_hex:.3f})")
    else:
        log(f"  ⚠️ 非完美通关 (蓝色比={blue_ratio:.4f}, 暗面比={dark_ratio_in_hex:.3f} → 立方体阴影)")
    
    return (cleared, is_perfect)

# ============================================================
# 脚本监控 (Watchdog)
# ============================================================

import time as _time
_SCRIPT_START_TIME = _time.time()
_LAST_CHECKPOINT = _time.time()

def checkpoint():
    """记录进度检查点，用于watchdog自检"""
    global _LAST_CHECKPOINT
    _LAST_CHECKPOINT = _time.time()

def check_stall(timeout=600):
    """检查脚本是否卡住（超过timeout秒无进展）
    返回True表示卡住，False表示正常
    """
    elapsed = _time.time() - _LAST_CHECKPOINT
    if elapsed > timeout:
        log(f"⚠️ 脚本卡住{int(elapsed)}秒，截图检查状态...", "WARN")
        try:
            p = shot("stall_check")
            t = ocr_text(p)
            log(f"  当前画面: {t[:80]}")
        except Exception as e:
            log(f"  截图失败: {e}", "ERROR")
        return True
    return False

# ============================================================
# 难度选择
# ============================================================

def select_hardest_difficulty(ch):
    """选择并确认最难难度；无法确认时失败关闭，绝不自动降级。"""
    diff = DIFFICULTY.get(ch, DIFFICULTY[10])
    hardest = diff["hardest"]
    selector = diff["selector"]
    option = diff["option"]

    if diff.get("per_stage_difficulty"):
        if _verify_target_chapter_map(ch, tag="per_stage_difficulty_verify"):
            log(
                f"  第{ch}章章节地图已确认；险地/沙盘必须在每个关卡详情内逐关闭环 ✅"
            )
            return True
        log(f"  ⛔ 第{ch}章章节地图未能确认，停止本次主线动作", "ERROR")
        return False

    # 新章节不一定沿用10~14章的环境下拉。第15章实机只有一个普通主线环境，
    # 因而“确认最难难度”的正确证据是仍在目标章节地图，而不是点击推演计分说明。
    # 这里只为已经实机验证过的章节启用，不能据此泛化到其他章节。
    if diff.get("single_environment"):
        if _verify_target_chapter_map(ch, tag="single_environment_verify"):
            log(f"  第{ch}章为单一主线环境；章节地图已确认，无难度下拉 ✅")
            return True
        log(f"  ⛔ 第{ch}章单一环境地图未能确认，停止本次主线动作", "ERROR")
        return False
    
    p = shot("diff")
    t = ocr_text(p)
    
    # 已是最难
    if hardest in t and "标准实战" not in t:
        log(f"  难度={hardest} ✅")
        return True
    
    # 展开下拉
    tap(*selector)
    wait(2)
    
    # 选最难
    p = shot("diff_open")
    items = ocr(p)
    pos = find_text(items, hardest)
    if pos:
        tap(*pos)
        wait(2)
        p2 = shot("diff_set")
        if hardest in ocr_text(p2):
            log(f"  ✅ {hardest}")
            return True
    
    # 固定坐标兜底
    if option:
        tap(*option)
        wait(2)
        p2 = shot("diff_fixed")
        if hardest in ocr_text(p2):
            log(f"  ✅ {hardest}(固定坐标)")
            return True

    _record_decision_request(
        "主线难度替代方案",
        f"第{ch}章最难难度“{hardest}”无法由OCR确认，未执行降级或盲目继续",
        ["G-AUTH-001", "G-MAINLINE-001"],
        {"chapter": ch, "requested_difficulty": hardest},
    )
    log(f"  ⛔ 最难难度“{hardest}”未确认，停止本次主线动作", "ERROR")
    return False

# ============================================================
# Copilot作业管理
# ============================================================

def _copilot_exclusion_keys(paths):
    """Normalize previously tried job paths so a retry cannot select them again."""
    keys = set()
    for path in paths or []:
        value = str(path or "").strip()
        if not value:
            continue
        keys.add(os.path.normcase(os.path.abspath(value)))
        keys.add(os.path.normcase(os.path.basename(value)))
    return keys


def _copilot_is_excluded(path, exclusion_keys):
    if not path:
        return False
    return (
        os.path.normcase(os.path.abspath(path)) in exclusion_keys
        or os.path.normcase(os.path.basename(path)) in exclusion_keys
    )


def _load_copilot_data(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fp:
            return json.load(fp)
    except Exception:
        return None


def _relaxed_copilot_job_path(path):
    """生成去除技能/模组建议门槛的临时作业副本，绝不改原作业。"""
    if not RELAX_COPILOT_SKILL_MODULE_REQUIREMENTS:
        return path
    data = _load_copilot_data(path)
    if not isinstance(data, dict):
        return path
    relaxed = deepcopy(data)
    removed = []

    def visit(node):
        if isinstance(node, dict):
            requirements = node.get("requirements")
            if isinstance(requirements, dict):
                for key in ("skill_level", "module"):
                    if key in requirements:
                        removed.append((key, requirements.pop(key)))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(relaxed)
    if not removed:
        return path
    out_dir = os.path.join(BASE, "outputs", "copilot_relaxed")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, os.path.basename(path))
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fp:
        json.dump(relaxed, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    os.replace(tmp_path, out_path)
    log(
        f"  [作业前置] 已生成宽松副本，忽略{len(removed)}项技能/模组建议门槛；"
        "原作业保持不变"
    )
    return out_path


def _copilot_roster_names(data):
    """Return the operator family used by a job; every group occupies one slot."""
    names = {
        str(op.get("name") or "").strip()
        for op in data.get("opers", [])
        if str(op.get("name") or "").strip()
    }
    for group in data.get("groups", []):
        for op in group.get("opers", []):
            name = str(op.get("name") or "").strip()
            if name:
                names.add(name)
    return names


def _copilot_strategy_fingerprint(data):
    """Stable roster plus action fingerprint, independent of the JSON filename."""
    roster = tuple(sorted(_copilot_roster_names(data)))
    actions = [
        (
            str(action.get("type") or ""),
            str(action.get("name") or ""),
            tuple(action.get("location") or ()),
            str(action.get("direction") or ""),
            action.get("kills"),
            action.get("costs"),
        )
        for action in data.get("actions", [])
    ]
    digest = hashlib.sha256(
        json.dumps(actions, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return roster, digest


def _copilot_action_skeleton(data):
    """Return the deployment timeline without operator names or UI-only actions."""
    ignored = {"SpeedUp", "SkillDaemon"}
    return [
        (
            str(action.get("type") or ""),
            tuple(action.get("location") or ()),
            str(action.get("direction") or ""),
        )
        for action in data.get("actions", [])
        if str(action.get("type") or "") not in ignored
    ]


def _copilot_is_same_strategy(data, previous_data):
    """Treat the same roster or deployment timeline as one strategy family."""
    roster, action_fp = _copilot_strategy_fingerprint(data)
    previous_roster, previous_action_fp = _copilot_strategy_fingerprint(previous_data)
    if action_fp == previous_action_fp:
        return True

    # Reuploads often replace one or two operators but keep every deployment
    # tile, retreat and skill timing.  Such a file repeats the same tactical
    # failure and must not consume another retry merely because its roster is
    # cosmetically different.
    skeleton = _copilot_action_skeleton(data)
    previous_skeleton = _copilot_action_skeleton(previous_data)
    if skeleton and previous_skeleton:
        timeline_similarity = SequenceMatcher(
            None, skeleton, previous_skeleton, autojunk=False
        ).ratio()
        if timeline_similarity >= 0.88:
            return True

    left, right = set(roster), set(previous_roster)
    if not left or not right:
        return False
    return len(left & right) / len(left | right) >= 0.85


def _copilot_auto_compatibility(data):
    """Reject prerequisites that contradict unattended MAA auto-formation."""
    formation_slots = len(data.get("opers", [])) + len(data.get("groups", []))
    doc = data.get("doc") or {}
    instructions = f"{doc.get('title', '')}\n{doc.get('details', '')}"
    # “手动点隐藏奖励/绿点”只影响可选掉落，不影响关卡本体通关。
    # 旧逻辑看到任意“手动”就整份作业淘汰，导致17-18这类成熟挂机流
    # 永远进不了候选池。逐行剥离明确限定于隐藏奖励的操作说明，剩余
    # 文本仍按严格无人值守规则检查；真正需要接管战斗的作业继续拒绝。
    operational_lines = []
    for line in instructions.splitlines():
        compact_line = re.sub(r"\s+", "", line)
        optional_hidden_manual = (
            "隐藏" in compact_line
            and any(marker in compact_line for marker in ("手动", "手点", "点绿点", "点光圈"))
            and not any(marker in compact_line for marker in ("否则无法通关", "否则过不了", "战斗必须手动"))
        )
        if not optional_hidden_manual:
            operational_lines.append(line)
    operational_instructions = "\n".join(operational_lines)
    blockers = (
        "不能自动编队", "需要一个助战位", "需要助战", "必须助战",
        "手动接管", "需要手动", "最好手动",
    )
    reasons = []
    if formation_slots > 12:
        reasons.append(f"需要{formation_slots}个编队槽位，超过自动编队上限12")
    matched = next((marker for marker in blockers if marker in operational_instructions), None)
    if matched:
        reasons.append(f"作者说明包含“{matched}”")
    if (
        "手动" in operational_instructions
        and not any(marker in operational_instructions for marker in ("无需手动", "不用手动", "不需要手动"))
    ):
        reasons.append("作者说明包含手动操作要求")
    return not reasons, "；".join(reasons)


def _chapter17_stage_requires_sandbox(display_name):
    stage = re.sub(r"\([^)]*\)", "", str(display_name or "")).strip().upper()
    return stage in CHAPTER17_SANDBOX_STAGES


def _chapter17_sandbox_choices_from_text(text):
    """从当前选中的MAA作业说明读取沙盘LV.1/LV.2左右选项。

    选项必须来自该份作业，不能用网络攻略或另一份同关作业的选择覆盖。
    返回值顺序固定为(LV.1, LV.2)，值为"left"或"right"。
    """
    compact = re.sub(r"[\s：:，,。;；_\-]+", "", str(text or ""))
    aliases = (
        ("沙盘全左", ("left", "left")),
        ("沙盘全选左", ("left", "left")),
        ("沙盘全右", ("right", "right")),
        ("沙盘全选右", ("right", "right")),
        ("沙盘上左下右", ("left", "right")),
        ("沙盘上右下左", ("right", "left")),
    )
    for marker, choices in aliases:
        if marker in compact:
            return choices

    numbered = re.search(r"沙盘.*?[①1一]([左右]).*?[②2二]([左右])", compact)
    if numbered:
        return tuple("left" if side == "左" else "right" for side in numbered.groups())
    return None


def _chapter17_sandbox_choices_from_job(job):
    data = _load_copilot_data(job) if not isinstance(job, dict) else job
    if not data:
        return None
    doc = data.get("doc") or {}
    return _chapter17_sandbox_choices_from_text(
        f"{doc.get('title', '')}\n{doc.get('details', '')}"
    )


CHAPTER17_SANDBOX_CHOICE_COMBINATIONS = (
    ("left", "left"),
    ("left", "right"),
    ("right", "left"),
    ("right", "right"),
)


def _chapter17_sandbox_trial_key(job_path, choices):
    """把一次沙盘尝试标识为“作业+两级假设”，允许同作业换组合复测。"""
    if not job_path or not choices or len(choices) != 2:
        return ""
    code = "".join("L" if value == "left" else "R" for value in choices)
    return f"{os.path.basename(str(job_path))}@{code}"


def _chapter17_random_untried_sandbox_choices(job_path, attempted_trials, chooser=None):
    """随机返回该作业尚未真实执行过的沙盘组合；四种均试过则返回None。"""
    attempted = {str(value) for value in (attempted_trials or []) if str(value).strip()}
    remaining = [
        choices
        for choices in CHAPTER17_SANDBOX_CHOICE_COMBINATIONS
        if _chapter17_sandbox_trial_key(job_path, choices) not in attempted
    ]
    if not remaining:
        return None
    chooser = chooser or random.SystemRandom()
    return chooser.choice(remaining)


def _chapter17_copilot_is_complete(data, display_name):
    """沙盘关作业必须同时匹配关卡且在自身说明中写明两级选项。"""
    if not _chapter17_stage_requires_sandbox(display_name):
        return True
    return _chapter17_sandbox_choices_from_job(data) is not None


def _copilot_previous_jobs(paths):
    jobs = []
    for value in paths or []:
        basename = os.path.basename(str(value))
        for path in (
            str(value),
            os.path.join(BUNDLED_COPILOT_DIR, basename),
            os.path.join(INDEXED_COPILOT_DIR, basename),
            os.path.join(COPILOT_DIR, basename),
        ):
            data = _load_copilot_data(path)
            if data:
                jobs.append(data)
                break
    return jobs


def _resolve_copilot_job_basename(job_name):
    """Resolve a previously executed job without changing its strategy."""
    basename = os.path.basename(str(job_name or "").strip())
    if not basename:
        return None
    for directory in (BUNDLED_COPILOT_DIR, INDEXED_COPILOT_DIR, COPILOT_DIR):
        path = os.path.join(directory, basename)
        if _load_copilot_data(path):
            return path
    return None


def _copilot_account_fit_score(data, display_name):
    """Return an explicit, stage-scoped account-fit preference.

    The user's roster is known to fit 自在道爷's mainline compositions.  Keep
    this preference scoped to normal/H mainline stage codes so it cannot change
    event or other task families. Compatibility and strategy de-duplication
    still run first.
    """
    doc = data.get("doc") or {}
    instructions = f"{doc.get('title', '')}\n{doc.get('details', '')}"
    stage = str(display_name or "").strip().upper()
    mainline_stage = re.fullmatch(r"H?\d{1,2}-\d{1,2}", stage) is not None
    return int(mainline_stage and "自在道爷" in instructions)


def get_copilot_json(
    stage_name,
    display_name=None,
    prefer_multi=False,
    attempt=0,
    excluded_paths=None,
    require_sandbox_choices=True,
):
    """获取Copilot作业JSON (本地优先→在线下载)
    
    🔴 2026-07-01 用户要求: 优先使用多核挂机阵容, 保证容错率
    attempt: 第几次尝试 (0-based), 用于失败重试换作业
      0 = 多核优先(干员数最多, 容错率高)
      1 = 次多核
      2+ = 按赞数排序(单核高赞, 换思路)
    """
    if not display_name:
        display_name = stage_name
    # 🔴 normalize: 去掉所有-和_后比较, 解决"tough_10-10"匹配问题
    safe_norm = stage_name.replace("-", "").replace("_", "")
    # 🔴 2026-07-08 修复: stage_name如"tough_12-08"和文件名"auto_12_9_v96996"不匹配
    # 增加display_name匹配: "12-9"→"129" 能匹配到 "auto129v96996"
    disp_norm = display_name.replace("-", "").replace("_", "") if display_name else ""
    # 🔴 2026-07-01: 默认prefer_multi=True, 多核优先
    prefer_multi = True

    exclusion_keys = _copilot_exclusion_keys(excluded_paths)
    previous_jobs = _copilot_previous_jobs(excluded_paths)

    # 1. 查本地
    cands = []
    for local_dir in (BUNDLED_COPILOT_DIR, INDEXED_COPILOT_DIR, COPILOT_DIR):
        if not os.path.exists(local_dir):
            continue
        for f in os.listdir(local_dir):
            # normalize文件名后比较
            f_norm = f.replace("-", "").replace("_", "")
            if safe_norm in f_norm or (disp_norm and disp_norm in f_norm):
                path = os.path.join(local_dir, f)
                try:
                    with open(path, 'r', encoding='utf-8-sig') as fp:
                        d = json.load(fp)
                    if (
                        'actions' in d and d['actions']
                        and _copilot_matches_stage(d, stage_name, display_name)
                    ):
                        compatible, reason = _copilot_auto_compatibility(d)
                        if not compatible:
                            log(f"  [作业前置] 跳过 {f}: {reason}", "WARN")
                            continue
                        if (
                            require_sandbox_choices
                            and not _chapter17_copilot_is_complete(d, display_name)
                        ):
                            log(
                                f"  [第17章沙盘] 跳过 {f}: 作业自身未写明LV.1/LV.2左右选项",
                                "WARN",
                            )
                            continue
                        if any(_copilot_is_same_strategy(d, old) for old in previous_jobs):
                            log(f"  [战术去重] 跳过同阵容族: {f}")
                            continue
                        opers = len(d.get('opers', []))
                        groups = sum(len(g.get('opers', [])) for g in d.get('groups', []))
                        if not _copilot_is_excluded(path, exclusion_keys):
                            match = re.search(r"_v(\d+)\.json$", f, re.I)
                            version_id = int(match.group(1)) if match else 0
                            cands.append((
                                path,
                                opers + groups,
                                len(d['actions']),
                                version_id,
                                _copilot_account_fit_score(d, display_name),
                            ))
                except:
                    continue
    
    if cands:
        # 🔴 2026-07-01: 多核优先(用户要求容错率)
        # attempt=0,1: 按干员数排序(多核优先, 容错率高)
        # attempt>=2: 按actions数排序(换思路)
        if attempt < 2 and len(previous_jobs) < 2:
            cands.sort(key=lambda x: (x[4], x[1], x[3]), reverse=True)
        else:
            # 多次失败后切换稳定性策略：近期、低操作的挂机流优先。
            cands.sort(key=lambda x: (-x[4], x[2], -x[3], -x[1]))
        
        # 排序策略可以随轮次改变，但每轮都从“尚未执行”的集合中取第一份。
        # 旧逻辑用 cands[attempt]，排序改变后同一文件会占据不同下标，
        # 导致所谓换作业实际重复执行同一 JSON。
        p, n, a, _, account_fit = cands[0]
        sandbox_choices = _chapter17_sandbox_choices_from_job(p)
        if account_fit:
            tag = "账号适配优先:自在道爷"
        else:
            tag = "多核" if attempt < 2 and len(previous_jobs) < 2 else "近期低操作挂机"
        log(f"  作业[#{attempt+1}]: {os.path.basename(p)} ({a}act,{n}人) [{tag},未重复]")
        if sandbox_choices:
            readable = tuple("左" if value == "left" else "右" for value in sandbox_choices)
            log(f"  [第17章沙盘] 严格采用本作业说明: LV.1={readable[0]}, LV.2={readable[1]}")
        return p

    # 本地未找到尚未执行的作业，继续在线查找。
    log(f"  本地没有尚未尝试的{display_name}作业，尝试在线补充")
    
    # 2. 在线下载 (按attempt取第N个)
    return download_copilot(
        display_name,
        prefer_multi,
        attempt,
        stage_name=stage_name,
        excluded_paths=excluded_paths,
        require_sandbox_choices=require_sandbox_choices,
    )


def _fetch_prts_json(url, timeout=15):
    """读取MAA作业站JSON；Python TLS失败时使用系统curl安全兜底。"""
    last_error = None
    for retry in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as e:
            last_error = e
            if retry < 2:
                time.sleep(1 + retry)

    # 仅允许固定的MAA作业站；curl仍保留正常证书校验，不使用-k。
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "prts.maa.plus":
        raise RuntimeError(f"拒绝对非MAA作业站启用下载兜底: {url}") from last_error
    log(f"  [作业下载] Python TLS连续失败，切换系统下载通道: {last_error}", "WARN")
    proc = subprocess.run(
        [
            "curl.exe", "--fail", "--location", "--silent", "--show-error",
            "--retry", "3", "--retry-delay", "1", "-A", "Mozilla/5.0", url,
        ],
        capture_output=True,
        timeout=max(30, timeout * 3),
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Python TLS与系统下载通道均失败: {detail or last_error}")
    return json.loads(proc.stdout.decode("utf-8"))

def download_copilot(
    display_name,
    prefer_multi=False,
    attempt=0,
    stage_name=None,
    excluded_paths=None,
    require_sandbox_choices=True,
):
    """从prts.plus下载作业 (query→get, 必须用get获取actions)
    
    🔴 2026-07-01: 多核优先(用户要求容错率)
    attempt 0,1: 按干员数排序(多核优先)
    attempt 2+: 按赞数排序(换思路)
    """
    try:
        order_by = "hot" if attempt < 2 else "uploadTime"
        url = f"https://prts.maa.plus/copilot/query?page=1&limit=50&desc=true&orderBy={order_by}&document={urllib.parse.quote(display_name)}"
        data = _fetch_prts_json(url, timeout=15)
        
        ops = data.get("data", {}).get("data", [])
        exact_ops = []
        for op in ops:
            try:
                content = json.loads(op.get("content", "{}"))
            except Exception:
                continue
            if _copilot_matches_stage(content, stage_name or display_name, display_name):
                exact_ops.append(op)
        ops = exact_ops
        if not ops:
            log(f"  ❌ prts.plus未找到{display_name}的精确匹配作业", "ERROR")
            return None
        
        # 🔴 2026-07-01: 多核优先。账号已确认更适配“自在道爷”的
        # 主线阵容，因此该作者只在普通/H主线关内提升到排序首位；不影响活动。
        if attempt < 2:
            def score(op):
                try:
                    c = json.loads(op.get("content", "{}"))
                    roster_size = len(c.get("opers", [])) + len(c.get("groups", []))
                    return (_copilot_account_fit_score(c, display_name), roster_size)
                except:
                    return (0, 0)
            ops.sort(key=score, reverse=True)
        else:
            def recent_score(op):
                try:
                    c = json.loads(op.get("content", "{}"))
                except Exception:
                    c = {}
                return (
                    _copilot_account_fit_score(c, display_name),
                    int(op.get("id", 0) or 0),
                )
            ops.sort(key=recent_score, reverse=True)
        
        exclusion_keys = _copilot_exclusion_keys(excluded_paths)
        excluded_ids = set()
        for key in exclusion_keys:
            match = re.search(r"_v(\d+)\.json$", key, re.I)
            if match:
                excluded_ids.add(match.group(1))
        ops = [op for op in ops if str(op.get("id", "")) not in excluded_ids]

        if not ops:
            log(f"  ❌ prts.plus没有尚未尝试的{display_name}作业", "ERROR")
            return None

        previous_jobs = _copilot_previous_jobs(excluded_paths)
        for op in ops:
            op_id = op["id"]
            try:
                gurl = f"https://prts.maa.plus/copilot/get/{op_id}"
                fd = _fetch_prts_json(gurl, timeout=10)
                inner = json.loads(fd["data"].get("content", "{}"))
                if "actions" not in inner or not inner["actions"]:
                    log(f"  跳过作业#{op_id}: 无actions", "WARN")
                    continue
                if not _copilot_matches_stage(inner, stage_name or display_name, display_name):
                    log(f"  跳过作业#{op_id}: 关卡不匹配", "WARN")
                    continue
                compatible, reason = _copilot_auto_compatibility(inner)
                if not compatible:
                    log(f"  [作业前置] 跳过在线作业#{op_id}: {reason}", "WARN")
                    continue
                if (
                    require_sandbox_choices
                    and not _chapter17_copilot_is_complete(inner, display_name)
                ):
                    log(
                        f"  [第17章沙盘] 跳过在线作业#{op_id}: "
                        "该作业自身未写明LV.1/LV.2左右选项",
                        "WARN",
                    )
                    continue
                if any(_copilot_is_same_strategy(inner, old) for old in previous_jobs):
                    log(f"  [战术去重] 跳过在线同战术作业#{op_id}")
                    continue
                fname = f"auto_{display_name.replace('-','_')}_v{op_id}.json"
                fpath = os.path.join(COPILOT_DIR, fname)
                with open(fpath, 'w', encoding='utf-8') as f:
                    json.dump(inner, f, ensure_ascii=False, indent=2)
                log(f"  下载[#{attempt+1}]: {fname} ({len(inner['actions'])}act, 前置兼容且战术未重复)")
                choices = _chapter17_sandbox_choices_from_job(inner)
                if choices:
                    readable = tuple("左" if value == "left" else "右" for value in choices)
                    log(f"  [第17章沙盘] 本作业选择: LV.1={readable[0]}, LV.2={readable[1]}")
                return fpath
            except Exception as e:
                log(f"  跳过下载失败的作业#{op_id}: {e}", "WARN")
                continue
        log(f"  ❌ prts.plus没有前置兼容且战术未重复的{display_name}作业", "ERROR")
        return None
    except Exception as e:
        log(f"  ❌ 下载失败: {e}", "ERROR")
    return None

# ============================================================
# MAA GUI 控制
# ============================================================

def _maa_install_root():
    return os.path.dirname(os.path.abspath(MAA_PATH))


def _maa_version_from_deps(root=None):
    """Read the GUI version without launching MAA."""
    deps_path = os.path.join(root or _maa_install_root(), "MAA.deps.json")
    try:
        with open(deps_path, "r", encoding="utf-8") as f:
            deps = json.load(f)
        for name in (deps.get("libraries") or {}):
            match = re.fullmatch(r"MAA/(\d+(?:\.\d+){1,3})", str(name), re.I)
            if match:
                return match.group(1)
    except Exception:
        pass
    return ""


def _maa_version_key(version):
    parts = [int(item) for item in re.findall(r"\d+", str(version or ""))[:4]]
    return tuple((parts + [0, 0, 0, 0])[:4])


def _maa_full_package_for_version(root, version):
    """Return a locally cached official full package for the installed version."""
    candidates = []
    explicit = os.environ.get("ARKNIGHTS_MAA_FULL_PACKAGE", "").strip()
    if explicit:
        candidates.append(os.path.abspath(explicit))
    parent = os.path.dirname(os.path.abspath(root))
    expected = f"MAA-v{version}-win-x64.zip"
    candidates.extend((os.path.join(parent, expected), os.path.join(root, expected)))
    for path in dict.fromkeys(candidates):
        if os.path.isfile(path):
            return path
    return ""


def _maa_matches_cached_full_package(root, version):
    """Compare runtime sentinels with the same-version official full package.

    A failed OTA can leave MAA.deps.json and MAA.exe reporting the target
    version while runtime/configuration assemblies still come from an older
    tree.  Presence/size checks cannot detect that mixed installation.
    """
    package = _maa_full_package_for_version(root, version)
    if not package:
        return None
    sentinels = (
        "MAA.exe", "MAA.dll", "MaaCore.dll", "MAA.deps.json",
        "MAA.runtimeconfig.json", "MAA.Updater.exe", "hostfxr.dll",
        "hostpolicy.dll", "MaaUtils.dll", "MaaAdbControlUnit.dll",
        "MaaWin32ControlUnit.dll",
    )
    try:
        with zipfile.ZipFile(package, "r") as archive:
            names = {name.replace("\\", "/").lower(): name for name in archive.namelist()}
            required = {name.lower() for name in ("MAA.exe", "MAA.dll", "MaaCore.dll", "MAA.deps.json")}
            if not required.issubset(names):
                return False
            for rel in sentinels:
                member = names.get(rel.lower())
                if not member:
                    continue
                installed = os.path.join(root, rel)
                if not os.path.isfile(installed):
                    return False
                digest = hashlib.sha256()
                with archive.open(member, "r") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != _maa_sha256(installed):
                    return False
    except (OSError, zipfile.BadZipFile):
        return False
    return True


def _maa_critical_files_healthy(root=None):
    root = root or _maa_install_root()
    critical = ("MAA.exe", "MAA.dll", "MaaCore.dll", "MAA.deps.json")
    try:
        if any(os.path.getsize(os.path.join(root, name)) <= 0 for name in critical):
            return False
    except OSError:
        return False
    version = _maa_version_from_deps(root)
    if not version:
        return False
    full_match = _maa_matches_cached_full_package(root, version)
    return full_match is not False


def _maa_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_maa_update_relpath(value):
    rel = os.path.normpath(str(value or "").replace("/", os.sep))
    if not rel or os.path.isabs(rel) or rel == ".." or rel.startswith(".." + os.sep):
        raise ValueError(f"unsafe update path: {value!r}")
    return rel


def _maa_pending_update(root=None):
    """Return the newest official staged update, if one is complete enough."""
    root = root or _maa_install_root()
    stage = os.path.join(root, "NewVersionExtract")
    manifests = []
    try:
        manifests = [
            os.path.join(root, name)
            for name in os.listdir(root)
            if re.fullmatch(r"maa-pending-update-[^.]+\.json", name, re.I)
        ]
    except OSError:
        pass
    manifests.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    if manifests:
        try:
            with open(manifests[0], "r", encoding="utf-8") as f:
                plan = json.load(f)
            move_list = [_safe_maa_update_relpath(p) for p in plan.get("moveList", [])]
            remove_list = [_safe_maa_update_relpath(p) for p in plan.get("removeList", [])]
            if move_list and all(os.path.isfile(os.path.join(stage, p)) for p in move_list):
                return {
                    "stage": stage,
                    "manifest": manifests[0],
                    "move_list": move_list,
                    "remove_list": remove_list,
                    "version": _maa_version_from_deps(stage),
                    "source": "pending_manifest",
                }
        except Exception as exc:
            log(f"  [MAA更新] 待安装清单无效: {exc}", "WARN")

    # Some MAA updater failures lose/quarantine the pending manifest after the
    # package has already been completely extracted.  A newer, internally
    # coherent staged tree is still safe to finish transactionally.
    staged_version = _maa_version_from_deps(stage)
    if staged_version and _maa_critical_files_healthy(stage):
        current_version = _maa_version_from_deps(root)
        if _maa_version_key(staged_version) > _maa_version_key(current_version):
            move_list = []
            for base, _dirs, files in os.walk(stage):
                for name in files:
                    move_list.append(os.path.relpath(os.path.join(base, name), stage))
            return {
                "stage": stage,
                "manifest": "",
                "move_list": move_list,
                "remove_list": [],
                "version": staged_version,
                "source": "staged_tree",
            }
    return None


def _maa_update_package(root=None):
    """Select an already downloaded official OTA/full package usable by MAA."""
    root = root or _maa_install_root()
    candidates = []
    explicit = os.environ.get("ARKNIGHTS_MAA_UPDATE_PACKAGE", "").strip()
    if explicit:
        candidates.append(os.path.abspath(explicit))
    try:
        candidates.extend(
            os.path.join(root, name)
            for name in os.listdir(root)
            if re.fullmatch(r"MAAComponent-(?:OTA|Full)-v?.+\.zip", name, re.I)
        )
    except OSError:
        pass
    parent = os.path.dirname(os.path.abspath(root))
    try:
        candidates.extend(
            os.path.join(parent, name)
            for name in os.listdir(parent)
            if re.fullmatch(r"MAA-v\d+(?:\.\d+){1,3}-win-x64\.zip", name, re.I)
        )
    except OSError:
        pass
    current = _maa_version_key(_maa_version_from_deps(root))
    install_healthy = _maa_critical_files_healthy(root)
    usable = []
    for path in dict.fromkeys(candidates):
        name = os.path.basename(path)
        versions = re.findall(r"v(\d+(?:\.\d+){1,3})", name, re.I)
        target = versions[-1] if versions else ""
        target_key = _maa_version_key(target)
        # 官方更新器可能先替换deps/dll、再因MAA.exe被占用而失败。此时
        # “当前版本号”已经等于目标版本，但安装并不完整；允许用同版本
        # 完整官方包修复。健康安装仍只接受严格更高版本。
        usable_version = (
            target_key > current
            if install_healthy
            else target_key >= current
        )
        if os.path.isfile(path) and target and usable_version:
            usable.append((_maa_version_key(target), path, target))
    if not usable:
        return None
    _key, path, version = max(usable)
    return {"path": path, "version": version, "source": "downloaded_package"}


def _extract_maa_update_package(package_path, root=None):
    root = root or _maa_install_root()
    stage = tempfile.mkdtemp(prefix=".auto-update-stage-", dir=root)
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            move_list = []
            for info in archive.infolist():
                if info.is_dir():
                    continue
                rel = _safe_maa_update_relpath(info.filename)
                dest = os.path.abspath(os.path.join(stage, rel))
                if os.path.commonpath((os.path.abspath(stage), dest)) != os.path.abspath(stage):
                    raise ValueError(f"update archive escapes stage: {info.filename!r}")
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with archive.open(info, "r") as source, open(dest, "wb") as target:
                    shutil.copyfileobj(source, target)
                if rel.lower() != "removelist.txt":
                    move_list.append(rel)
        remove_list = []
        remove_file = os.path.join(stage, "removelist.txt")
        if os.path.isfile(remove_file):
            with open(remove_file, "r", encoding="utf-8-sig", errors="replace") as f:
                remove_list = [_safe_maa_update_relpath(line.strip()) for line in f if line.strip()]
        return stage, move_list, remove_list
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _apply_maa_update_tree(stage, move_list, remove_list, root=None):
    """事务化应用官方更新，删除项也先备份并在失败时完整回滚。"""
    root = root or _maa_install_root()
    rels = [_safe_maa_update_relpath(p) for p in move_list]
    removals = [_safe_maa_update_relpath(p) for p in remove_list]
    if not rels:
        raise RuntimeError("更新清单为空")
    missing = [rel for rel in rels if not os.path.isfile(os.path.join(stage, rel))]
    if missing:
        raise RuntimeError(f"更新暂存区缺少{len(missing)}个文件: {missing[:3]}")

    backup = os.path.join(
        root,
        ".auto-update-backup",
        datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
    )
    changed = []
    removed = []
    moved_set = {os.path.normcase(rel) for rel in rels}
    try:
        # 先备份所有将被覆盖或删除的现有文件，删除型OTA同样可逆。
        for rel in dict.fromkeys(rels + removals):
            dest = os.path.join(root, rel)
            if os.path.isdir(dest):
                raise RuntimeError(f"更新清单包含目录，拒绝自动处理: {rel}")
            if os.path.isfile(dest):
                old = os.path.join(backup, rel)
                os.makedirs(os.path.dirname(old), exist_ok=True)
                shutil.copy2(dest, old)

        for rel in rels:
            source = os.path.join(stage, rel)
            dest = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(source, dest)
            changed.append(rel)

        for rel in removals:
            if os.path.normcase(rel) in moved_set:
                raise RuntimeError(f"同一更新文件同时要求移动与删除: {rel}")
            dest = os.path.join(root, rel)
            if os.path.isfile(dest):
                os.remove(dest)
                removed.append(rel)

        mismatches = [
            rel for rel in rels
            if _maa_sha256(os.path.join(stage, rel)) != _maa_sha256(os.path.join(root, rel))
        ]
        if mismatches:
            raise RuntimeError(f"更新后哈希不一致: {mismatches[:3]}")
        leftovers = [rel for rel in removals if os.path.exists(os.path.join(root, rel))]
        if leftovers:
            raise RuntimeError(f"更新删除项仍残留: {leftovers[:3]}")
        if not _maa_critical_files_healthy(root):
            raise RuntimeError("更新后MAA关键文件仍不完整")
        return backup
    except Exception:
        # 先移除本轮新建/替换内容，再从备份恢复；未曾存在的新文件不保留。
        for rel in reversed(changed):
            dest = os.path.join(root, rel)
            old = os.path.join(backup, rel)
            try:
                if os.path.isfile(old):
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(old, dest)
                elif os.path.isfile(dest):
                    os.remove(dest)
            except Exception:
                pass
        for rel in removed:
            old = os.path.join(backup, rel)
            dest = os.path.join(root, rel)
            try:
                if os.path.isfile(old):
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(old, dest)
            except Exception:
                pass
        raise

def _stop_idle_maa_for_update():
    """Stop only MAA/updater processes; never interrupt a confirmed queue."""
    if _maa_process_ids() and _maa_task_queue_running():
        raise RuntimeError("MAA任务队列仍在运行，禁止为更新终止进程")
    for image in ("MAA.exe", "MAA.Updater.exe"):
        subprocess.run(
            ["taskkill", "/f", "/im", image],
            capture_output=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def ensure_maa_install_ready(allow_recovery=True):
    """Validate/finalize MAA updates before the game enters a battle contract."""
    root = _maa_install_root()
    current = _maa_version_from_deps(root)
    pending = _maa_pending_update(root)
    package = _maa_update_package(root)
    needs_recovery = not _maa_critical_files_healthy(root) or pending or package
    if not needs_recovery:
        log(f"  [MAA自检] 安装完整，版本={current}")
        return True
    if not allow_recovery:
        log("  ❌ MAA安装/更新未完成，且本轮禁止自动恢复", "ERROR")
        return False

    source = pending or package
    if not source:
        log("  ❌ MAA关键文件不完整，且没有完整的官方暂存包可恢复", "ERROR")
        return False
    temp_stage = ""
    try:
        log(
            f"  [MAA更新恢复] 当前={current or '损坏'}，目标={source.get('version') or '未知'}，"
            f"来源={source['source']}"
        )
        _stop_idle_maa_for_update()
        if "path" in source:
            temp_stage, move_list, remove_list = _extract_maa_update_package(
                source["path"], root
            )
            stage = temp_stage
        else:
            stage = source["stage"]
            move_list = source["move_list"]
            remove_list = source["remove_list"]
        backup = _apply_maa_update_tree(stage, move_list, remove_list, root)
        target = _maa_version_from_deps(root)
        if source.get("version") and _maa_version_key(target) < _maa_version_key(source["version"]):
            raise RuntimeError(f"更新目标未达到: expected={source['version']}, actual={target}")
        manifest = source.get("manifest") or ""
        if manifest and os.path.isfile(manifest):
            os.replace(manifest, manifest + ".auto-applied")
        _RUN_SUMMARY["maa_update"] = {
            "status": "recovered",
            "from": current or "damaged",
            "to": target,
            "source": source["source"],
            "backup": backup,
        }
        log(f"  ✅ MAA更新恢复完成: {current or '损坏'} → {target}")
        return True
    except Exception as exc:
        _RUN_SUMMARY["maa_update"] = {
            "status": "failed",
            "from": current or "damaged",
            "target": source.get("version") or "unknown",
            "error": str(exc),
        }
        log(f"  ❌ MAA更新恢复失败（未进入战斗）: {exc}", "ERROR")
        return False
    finally:
        if temp_stage:
            shutil.rmtree(temp_stage, ignore_errors=True)

def _maa_process_ids():
    """Return real MAA.exe PIDs; window titles are not process identity."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq MAA.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            encoding="gbk",
            errors="replace",
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return set()
        return {
            int(pid) for pid in re.findall(r'"MAA\.exe","(\d+)"', result.stdout or "", re.I)
        }
    except Exception:
        return set()


def _find_real_maa_window(ua):
    """Find an enabled UIA window owned by MAA.exe, never a similarly titled app."""
    pids = _maa_process_ids()
    if not pids:
        return None
    candidates = []

    # Prefer native HWND enumeration followed by direct UIA binding.  Scanning
    # every desktop UIA root can block on an unrelated elevated/transient
    # window; direct handles keep MAA discovery bounded and process-owned.
    if os.name == "nt" and hasattr(ua, "ControlFromHandle"):
        try:
            import ctypes
            from ctypes import wintypes

            handles = []
            enum_proc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            @enum_proc
            def collect_handle(hwnd, _lparam):
                pid = wintypes.DWORD()
                ctypes.windll.user32.GetWindowThreadProcessId(
                    hwnd, ctypes.byref(pid)
                )
                if int(pid.value) in pids:
                    handles.append(int(hwnd))
                return True

            ctypes.windll.user32.EnumWindows(collect_handle, 0)
            for hwnd in handles:
                try:
                    window = ua.ControlFromHandle(hwnd)
                    name = str(window.Name or "")
                    rect = window.BoundingRectangle
                    visible = not (
                        rect.left == rect.top == rect.right == rect.bottom == 0
                    )
                    enabled = bool(window.IsEnabled)
                    score = (
                        (100 if enabled else 0)
                        + (50 if name.startswith("MAA") else 0)
                        + (10 if visible else 0)
                    )
                    candidates.append((score, window))
                except Exception:
                    continue
            if candidates:
                return max(candidates, key=lambda item: item[0])[1]
        except Exception:
            candidates = []

    try:
        windows = ua.GetRootControl().GetChildren()
    except Exception:
        return None
    for window in windows:
        try:
            if int(getattr(window, "ProcessId", 0) or 0) not in pids:
                continue
            name = str(window.Name or "")
            rect = window.BoundingRectangle
            visible = not (
                rect.left == rect.top == rect.right == rect.bottom == 0
            )
            enabled = bool(window.IsEnabled)
            child_count = len(window.GetChildren()) if enabled else 0
            score = (
                (100 if enabled else 0)
                + (50 if name.startswith("MAA") else 0)
                + (20 if child_count else 0)
                + (10 if visible else 0)
            )
            candidates.append((score, window))
        except Exception:
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _refresh_windows_taskbar(reason=""):
    """重绘任务栏，清除已退出 MAA/MuMu 遗留的幽灵标签。

    Windows 偶尔不会在后台进程被强制结束后立即刷新任务栏，表现为悬停前
    出现多个已经不存在的 MAA/MuMu 标签。这里只重绘主/副任务栏窗口；不
    重启 Explorer，也不清空图标缓存，避免影响用户正在使用的桌面。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        tray_classes = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
        handles = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def collect(hwnd, _lparam):
            buffer = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, buffer, len(buffer))
            if buffer.value in tray_classes:
                handles.append(hwnd)
            return True

        callback = callback_type(collect)
        user32.EnumWindows(callback, 0)
        # RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW
        redraw_flags = 0x0001 | 0x0004 | 0x0080 | 0x0100
        for hwnd in handles:
            user32.RedrawWindow(hwnd, None, None, redraw_flags)
        if handles:
            suffix = f"（{reason}）" if reason else ""
            log(f"  [任务栏] 已刷新{len(handles)}个任务栏窗口{suffix}")
        return bool(handles)
    except Exception as exc:
        log(f"  ⚠️ 任务栏刷新失败但不阻断自动化: {exc}", "WARN")
        return False


def _launch_maa_for_background_control():
    """Launch MAA with an actual WPF window even from a hidden supervisor.

    ``run_phantom_until_deadline.py`` is intentionally started hidden.  Plain
    ``Popen`` can let MAA inherit that hidden show state, leaving a live process
    with no top-level UIA window and making Link Start impossible to invoke.
    """
    _close_maacore_screenshot_bridge()
    # MAA官方MuMu截图增强必须在进程读取配置前落盘。这里是空闲启动边界；
    # 已运行实例会被prepare函数拒绝改写，避免和WPF自身保存配置竞态。
    screencap = prepare_maa_mumu_screenshot_enhancement()
    _RUN_SUMMARY["maa_screencap"] = screencap
    if screencap.get("status") == "enabled":
        log("  [MAA截图] 已启用MuMu 12增强截图（未启用网络桥接/增强触控）")
    elif screencap.get("status") == "already_enabled":
        log("  [MAA截图] MuMu 12增强截图配置已就绪")
    elif screencap.get("status") not in ("disabled_by_env", "deferred"):
        log(f"  ⚠️ MAA增强截图未应用: {screencap}", "WARN")

    # 先清掉上一实例已退出但 Explorer 尚未重绘的幽灵标签，再创建新窗口。
    _refresh_windows_taskbar("MAA启动前")
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = getattr(subprocess, "SW_SHOWNORMAL", 1)
    return subprocess.Popen(
        [MAA_PATH],
        cwd=os.path.dirname(MAA_PATH),
        startupinfo=startupinfo,
    )


def _maa_declared_update():
    """读取MAA已发现但尚待确认安装的版本与本地更新包。"""
    config_path = os.path.join(MAA_CONFIG, "gui.new.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            update = (json.load(f).get("Update") or {})
        target = str(update.get("Name") or "").lstrip("vV")
        package_name = str(update.get("UpdatePackage") or "").strip()
        package_path = (
            os.path.join(_maa_install_root(), package_name)
            if package_name else ""
        )
        return target, package_path
    except Exception:
        return "", ""


def _finalize_maa_update_before_control(ua, maa, wait_seconds=20):
    """把MAA启动时出现的“更新待确认”闭环后再交给任务控制。

    MAA默认会在启动后下载更新，但 ``AutoInstallUpdatePackage=false``，
    因而下载完成与真正安装是两个状态。这里仅在队列尚未开始时等待完整
    官方包落盘，关闭空闲MAA、事务化完成安装，再用新版本重启。更新器或
    MAA窗口在此期间消失属于更新过程，不能报成作业崩溃。
    """
    current = _maa_version_from_deps()
    target, package_path = _maa_declared_update()
    if not target or _maa_version_key(target) <= _maa_version_key(current):
        return maa
    log(f"  [MAA更新确认] 已发现 {current or '未知'} → {target}，等待官方包完整落盘")
    deadline = time.time() + max(0, int(wait_seconds))
    while package_path and not os.path.isfile(package_path) and time.time() < deadline:
        wait(1)
        target, package_path = _maa_declared_update()
    if not package_path or not os.path.isfile(package_path):
        log("  ❌ MAA更新包尚未完整下载，未启动任何任务", "ERROR")
        return None
    if _maa_task_queue_running():
        log("  ❌ MAA队列已运行，禁止中途确认安装更新", "ERROR")
        return None
    if not ensure_maa_install_ready(allow_recovery=True):
        return None
    installed = _maa_version_from_deps()
    if _maa_version_key(installed) < _maa_version_key(target):
        log(f"  ❌ MAA更新确认后版本仍为{installed}，目标={target}", "ERROR")
        return None
    log(f"  ✅ MAA更新已确认并安装到 {installed}，正在重启同一任务")
    try:
        _launch_maa_for_background_control()
    except Exception as exc:
        log(f"  ❌ MAA更新后重启失败: {exc}", "ERROR")
        return None
    fresh = None
    for _ in range(30):
        wait(1)
        fresh = _find_real_maa_window(ua)
        if fresh:
            break
    if not fresh:
        log("  ❌ MAA更新后窗口30秒仍未出现", "ERROR")
        return None
    wait(5)
    return fresh

def _is_formation_page_text(text):
    """编队页专属文字；关卡详情页的“开始行动/代理指挥”不算。"""
    compact = re.sub(r"\s+", "", str(text or "")).upper()
    return any(marker in compact for marker in (
        "快捷编队", "助战干员", "SUPPORTUNIT", "OPERATORSELECTION",
    ))


def _is_sss_deploy_page_text(text):
    """保全派驻完成编队后的开始部署/当前进度页专属证据。

    该页不是普通编队页，不能复用 ``_is_formation_page_text``。同时必须
    要求保全专属进度文字，避免仅凭普通页面上的“开始部署”放宽Copilot
    战前门槛。
    """
    compact = re.sub(r"\s+", "", str(text or "")).upper()
    has_progress = "初始危险等级" in compact or "当前进度" in compact
    has_action = "开始部署" in compact or (
        "暂停任务" in compact and "结束委托" in compact
    )
    return has_progress and has_action


def _uia_descendants(root, max_depth=12):
    """Return a fresh, bounded UIA subtree without relying on newer helpers."""
    result = []

    def walk(node, depth=0):
        if depth > max_depth:
            return
        try:
            children = node.GetChildren()
        except Exception:
            return
        for child in children:
            result.append(child)
            walk(child, depth + 1)

    walk(root)
    return result


def _uia_control_visible(control):
    try:
        rect = control.BoundingRectangle
        return rect.right > rect.left and rect.bottom > rect.top
    except Exception:
        return False


def _dismiss_maa_setup_guide(maa):
    """Dismiss MAA's post-update setup guide without mouse/keyboard input.

    The guide is a recurring post-update state, not a battle/job failure.  It
    covers the normal task pages, so acting on the underlying tree can select
    an unrelated Edit control.  Require the guide title or its unique three
    navigation buttons before invoking ``完成``.
    """
    nodes = _uia_descendants(maa)
    text_names = {
        str(getattr(node, "Name", "") or "")
        for node in nodes
        if getattr(node, "ControlTypeName", "") == "TextControl"
    }
    buttons = {
        str(getattr(node, "Name", "") or ""): node
        for node in nodes
        if getattr(node, "ControlTypeName", "") == "ButtonControl"
        and _uia_control_visible(node)
    }
    guide_signature = (
        any("设置指引" in name for name in text_names)
        or {"上一步", "下一步", "完成"}.issubset(buttons)
    )
    if not guide_signature:
        return False
    finish = buttons.get("完成")
    if not finish:
        raise RuntimeError("检测到MAA设置指引，但未找到完成按钮")
    finish.GetInvokePattern().Invoke()
    return True


def _is_maa_announcement_window(window):
    """只用公告专属控件组合识别MAA更新公告，禁止猜测普通确认框。"""
    if not window:
        return False
    nodes = [window] + _uia_descendants(window)
    title = str(getattr(window, "Name", "") or "").strip()
    has_checkbox = any(
        getattr(node, "ControlTypeName", "") == "CheckBoxControl"
        and "下次公告更新前不再显示" in str(getattr(node, "Name", "") or "")
        for node in nodes
    )
    has_confirm = any(
        getattr(node, "ControlTypeName", "") == "ButtonControl"
        and str(getattr(node, "Name", "") or "").strip() == "确认"
        for node in nodes
    )
    has_title = title == "公告" or any(
        getattr(node, "ControlTypeName", "") == "TextControl"
        and str(getattr(node, "Name", "") or "").strip() == "公告"
        for node in nodes
    )
    return has_title and has_checkbox and has_confirm


def _find_maa_announcement_window(ua, fallback=None):
    """在真实MAA进程拥有的顶层窗口中定位公告窗口。"""
    pids = _maa_process_ids()
    candidates = [fallback] if fallback else []
    try:
        candidates.extend(
            window for window in ua.GetRootControl().GetChildren()
            if int(getattr(window, "ProcessId", 0) or 0) in pids
        )
    except Exception:
        pass
    for candidate in candidates:
        try:
            if _is_maa_announcement_window(candidate):
                return candidate
        except Exception:
            continue
    return None


def _dismiss_maa_announcement(window):
    """滚到公告正文底部，勾选不再提示并确认，全程使用后台UIA。"""
    if not _is_maa_announcement_window(window):
        return False
    nodes = [window] + _uia_descendants(window)

    # 公告在正文滚到底之前不会开放完整确认流程。优先操作ScrollPattern；
    # 某些WPF版本只暴露右侧ScrollBar的RangeValuePattern，两种都兼容。
    scrolled = False
    for node in nodes:
        try:
            scroll_pattern = node.GetScrollPattern()
            if bool(getattr(scroll_pattern, "VerticallyScrollable", False)):
                scroll_pattern.SetScrollPercent(-1.0, 100.0)
                scrolled = True
        except Exception:
            pass
        if getattr(node, "ControlTypeName", "") == "ScrollBarControl":
            try:
                range_pattern = node.GetRangeValuePattern()
                range_pattern.SetValue(float(range_pattern.Maximum))
                scrolled = True
            except Exception:
                pass
    if not scrolled:
        raise RuntimeError("检测到MAA公告，但未找到可后台滚动的正文控件")
    time.sleep(0.4)

    checkbox = next(
        node for node in nodes
        if getattr(node, "ControlTypeName", "") == "CheckBoxControl"
        and "下次公告更新前不再显示" in str(getattr(node, "Name", "") or "")
    )
    toggle = checkbox.GetTogglePattern()
    if int(getattr(toggle, "ToggleState", 0)) == 0:
        toggle.Toggle()
    time.sleep(0.2)

    confirm = next(
        node for node in nodes
        if getattr(node, "ControlTypeName", "") == "ButtonControl"
        and str(getattr(node, "Name", "") or "").strip() == "确认"
    )
    if not bool(getattr(confirm, "IsEnabled", True)):
        raise RuntimeError("MAA公告已滚到底并勾选，但确认按钮仍不可用")
    confirm.GetInvokePattern().Invoke()
    return True


def _maa_copilot_page_controls(maa):
    """Return Copilot controls only when the complete page signature exists."""
    nodes = _uia_descendants(maa)
    auto_formation = next((
        node for node in nodes
        if getattr(node, "ControlTypeName", "") == "CheckBoxControl"
        and "自动编队" in str(getattr(node, "Name", "") or "")
        and _uia_control_visible(node)
    ), None)
    start_btn = next((
        node for node in nodes
        if getattr(node, "ControlTypeName", "") == "ButtonControl"
        and str(getattr(node, "Name", "") or "").strip() == "开始"
        and _uia_control_visible(node)
    ), None)
    if not auto_formation or not start_btn:
        return None

    start_rect = start_btn.BoundingRectangle
    edits = []
    for node in nodes:
        if getattr(node, "ControlTypeName", "") != "EditControl":
            continue
        if not _uia_control_visible(node):
            continue
        try:
            rect = node.BoundingRectangle
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            # In every supported MAA layout the job path is the wide Edit
            # directly above Start.  This rejects task-queue and numeric edits.
            if width >= 180 and height <= 120 and rect.bottom <= start_rect.top + 8:
                edits.append((width, node))
        except Exception:
            continue
    if not edits:
        return None
    edit_ctrl = max(edits, key=lambda item: item[0])[1]
    return edit_ctrl, auto_formation, start_btn


def _prepare_maa_copilot_page(ua, maa, attempts=6):
    """Dismiss announcement/guide, select Copilot, and verify its full UI signature."""
    diagnostics = []
    for attempt in range(1, attempts + 1):
        fresh = _find_real_maa_window(ua)
        if fresh:
            maa = fresh
        try:
            announcement = _find_maa_announcement_window(ua, maa)
            if announcement and _dismiss_maa_announcement(announcement):
                log("  [MAA更新恢复] 公告已滚到底、勾选不再提示并确认；不计入作业失败")
                time.sleep(1.5)
                fresh = _find_real_maa_window(ua)
                if fresh:
                    maa = fresh

            if _dismiss_maa_setup_guide(maa):
                log("  [MAA更新恢复] 已关闭设置指引，不计入作业失败")
                time.sleep(1.5)
                fresh = _find_real_maa_window(ua)
                if fresh:
                    maa = fresh

            tabs = [
                node for node in _uia_descendants(maa, max_depth=7)
                if getattr(node, "ControlTypeName", "") == "TabItemControl"
                and "Copilot" in str(getattr(node, "Name", "") or "")
            ]
            if not tabs:
                diagnostics.append(f"#{attempt}:无自动战斗Tab")
            else:
                # WPF TabItem supports SelectionItem, not Invoke.  Falling
                # back to Invoke caused the 6.15.1 retry path to fail.
                tabs[0].GetSelectionItemPattern().Select()
                time.sleep(1.2)
                fresh = _find_real_maa_window(ua)
                if fresh:
                    maa = fresh
                controls = _maa_copilot_page_controls(maa)
                if controls:
                    return maa, controls
                diagnostics.append(f"#{attempt}:自动战斗页签名不完整")
        except Exception as exc:
            diagnostics.append(f"#{attempt}:{type(exc).__name__}:{exc}")
        time.sleep(1.0)
    log(f"  ❌ MAA自动战斗页未就绪（{' ; '.join(diagnostics)}）", "ERROR")
    return maa, None


def run_maa_copilot(json_path, allow_sss_deploy=False):
    """MAA Copilot: 导入JSON→开始 (前提: 游戏在编队界面)
    
    2026-06-28 重写: 全部用uiautomation控件操作, 不用屏幕坐标点击
    控件结构(实测v6.12.2):
      TabControl > TabItem(CopilotViewModel) > CustomControl
        > ListControl (作业类型选择)
        > EditControl (路径输入框)
        > ButtonControl x3 (导入/??/??)
        > ButtonControl "开始" (启动按钮)
        > CheckBoxControl "自动编队"
    """
    import uiautomation as ua
    import time

    # 新进程的DEVICE仍可能是默认端口；必须先同步当前MuMu端口，
    # 否则连“是否在编队页”的截图都会从旧设备读取并产生假失败。
    old_device = DEVICE
    detect_mumu_adb_port()
    if DEVICE != old_device:
        reload_maa_after_config_switch(f"ADB端口变化 {old_device}→{DEVICE}")

    # 硬前置：普通作业只有真实编队页才允许启动Copilot。保全作业完成
    # 原生20/20编队后会进入专属“开始部署/当前进度”页，仅由显式参数放行。
    # 关卡详情页同样有“开始行动/代理指挥”，不能据此启动。
    pre_path = shot("copilot_precondition")
    pre_text = ocr_text(pre_path)
    formation_ready = _is_formation_page_text(pre_text)
    sss_deploy_ready = allow_sss_deploy and _is_sss_deploy_page_text(pre_text)
    if not (formation_ready or sss_deploy_ready):
        expected = "真实编队页或保全开始部署页" if allow_sss_deploy else "真实编队页"
        log(f"  ❌ MAA启动前置失败：尚未进入{expected}，OCR={pre_text[:100]}", "ERROR")
        return False

    page_name = "保全开始部署页" if sss_deploy_ready else "编队页"
    log(f"  [MAA前置] {page_name}已确认，连接地址={DEVICE}")
    # MAA更新是战斗前环境恢复，不是一次作业失败。只有安装完整后才允许
    # 进入Copilot启动；恢复成功后继续原作业，不消耗关卡/作业重试预算。
    if not ensure_maa_install_ready(allow_recovery=True):
        return False
    
    # 1. 找MAA窗口
    maa = _find_real_maa_window(ua)
    if not maa:
        # 🔴 2026-07-01 修复: MAA未启动时自动启动 (之前只查找不启动, 导致mainline模式永远失败)
        log("  → MAA未运行, 启动MAA.exe...")
        try:
            _launch_maa_for_background_control()
        except Exception as e:
            log(f"  ⚠️ MAA首次启动失败，尝试就地完成更新后重启: {e}", "WARN")
            if not ensure_maa_install_ready(allow_recovery=True):
                return False
            try:
                _launch_maa_for_background_control()
            except Exception as retry_error:
                log(f"  ❌ MAA更新恢复后仍无法启动: {retry_error}", "ERROR")
                return False
        for i in range(30):
            wait(1)
            maa = _find_real_maa_window(ua)
            if maa:
                break
        if not maa:
            # 官方更新器可能在首次启动后短暂替换/重启主程序。此时仍未
            # 开始战斗，允许清理空闲MAA并对同一作业重启一次。
            log("  ⚠️ MAA窗口30秒未出现，执行一次更新后同任务重启", "WARN")
            if not ensure_maa_install_ready(allow_recovery=True):
                return False
            try:
                _stop_idle_maa_for_update()
                _launch_maa_for_background_control()
                for _ in range(30):
                    wait(1)
                    maa = _find_real_maa_window(ua)
                    if maa:
                        break
            except Exception as retry_error:
                log(f"  ❌ MAA同任务重启失败: {retry_error}", "ERROR")
                return False
            if not maa:
                log("  ❌ MAA更新恢复后窗口仍未出现", "ERROR")
                return False
        log("  ✅ MAA窗口已出现")
        wait(8)  # 冷启动后先等UI框架，后续控件查找仍会继续刷新

    maa = _finalize_maa_update_before_control(ua, maa)
    if not maa:
        return False

    # 不置顶、不抢焦点；用户同时使用鼠标键盘时，MAA控制仍应在后台完成。
    time.sleep(0.5)

    # 2-3. MAA更新后可能先显示设置指引。先关闭指引，再强制切到自动
    # 战斗页，并同时确认路径框/自动编队/开始三项，禁止在错误页面猜控件。
    maa, page_controls = _prepare_maa_copilot_page(ua, maa)
    if not page_controls:
        return False
    edit_ctrl, auto_formation, start_btn = page_controls
    log("  [MAA] 自动战斗页四项联合确认通过 ✅")
    
    # 4. 后台写入路径。技能/模组建议门槛可按当前用户策略放宽，但原始
    # 作业不可改写；缺员和真实战败仍由MAA/游戏照常返回。
    json_path = _relaxed_copilot_job_path(json_path)
    # 禁止Click/SendKeys/Ctrl+V，避免与用户鼠标键盘、剪贴板冲突。
    try:
        value_pattern = edit_ctrl.GetValuePattern()
        value_pattern.SetValue(json_path)
        time.sleep(0.8)
        actual_value = str(edit_ctrl.GetValuePattern().Value or "")
        expected_name = os.path.basename(json_path)
        if expected_name not in actual_value:
            raise RuntimeError(
                f"后台赋值校验失败(expected={expected_name}, actual={actual_value[-60:]})"
            )
        log(f"  [MAA] 作业路径已后台写入并校验: {expected_name}")
    except Exception as e:
        log(f"  ❌ 后台写入作业路径失败(未使用鼠标键盘): {e}", "ERROR")
        return False
    
    # 5. 🔴 不点Import按钮! (用户2026-06-28确认: 粘贴路径后MAA自动加载作业,
    #    不需要点Edit右侧任何按钮, 直接勾选自动编队→点开始)
    #    之前点Import/按Enter会弹出文件对话框, 造成干扰
    time.sleep(3)  # 🔴 2026-07-01: 2s→3s, 给MAA更多时间加载作业
    log("  [MAA] 路径已后台写入, MAA自动加载作业 (跳过Import按钮)")
    
    # 6. 勾选"自动编队" (如果未勾选)。该控件已在页面联合确认阶段锁定。
    if auto_formation:
        try:
            if not auto_formation.GetTogglePattern().ToggleState:  # 未勾选
                auto_formation.GetTogglePattern().Toggle()
                log("  [MAA] 自动编队已勾选 ✅")
            else:
                log("  [MAA] 自动编队已勾选")
        except Exception as e:
            log(f"  ❌ 自动编队后台勾选失败: {e}", "ERROR")
            return False
    else:
        log("  ❌ 自动编队控件未找到，拒绝盲目启动", "ERROR")
        return False
    
    # 7. 点击"开始"按钮。该按钮同样来自已验真的自动战斗页。
    if start_btn:
        try:
            start_btn.GetInvokePattern().Invoke()
        except Exception as e:
            log(f"  ❌ 无法在后台调用MAA开始按钮(未使用鼠标): {e}", "ERROR")
            return False
        log("  ✅ MAA Copilot已启动!")
        # MAA配置页会成为前台窗口；开始后立即把游戏画面还给用户观看。
        # 这只改变显示焦点，不参与MAA/游戏控制，也不会抢鼠标完成作业。
        wait(1)
        _foreground_mumu_display()
        return True

    log("  ❌ '开始'按钮未找到", "ERROR")
    return False


def _verify_edit_has_text(maa, expected_text):
    """验证Edit控件是否已包含指定文本"""
    def search(r, d=0):
        if d > 12: return False
        for c in r.GetChildren():
            if c.ControlTypeName == "EditControl":
                try:
                    v = c.GetValuePattern().Value
                    if expected_text in v:
                        return True
                except: pass
            if search(c, d+1): return True
        return False
    return search(maa)


def _find_control_absolute(root, ctrl_type, screen_x, screen_y, tolerance=20):
    """按类型+屏幕绝对坐标查找控件 (容差更大)"""
    found = [None]
    def search(r, d=0):
        if d > 12 or found[0]: return
        for c in r.GetChildren():
            if c.ControlTypeName == ctrl_type:
                try:
                    rc = c.BoundingRectangle
                    if abs(rc.left - screen_x) < tolerance and abs(rc.top - screen_y) < tolerance:
                        found[0] = c; return
                except: pass
            search(c, d+1)
    search(root)
    return found[0]

def _find_control(root, ctrl_type, pos):
    """按类型+位置查找控件"""
    x, y = pos
    found = [None]
    def search(r, d=0):
        if d > 12 or found[0]: return
        for c in r.GetChildren():
            if c.ControlTypeName == ctrl_type:
                try:
                    rc = c.BoundingRectangle
                    if abs(rc.left - x) < 5 and abs(rc.top - y) < 5:
                        found[0] = c; return
                except: pass
            search(c, d+1)
            if found[0]: return
    search(root)
    return found[0]

def run_maa_daily_tasks(enabled_tasks=None):
    """执行MAA任务链；默认运行日常，也可显式指定任务类型。"""
    import uiautomation as ua

    # 保留显式清单，既便于审阅，也满足BR53对日常任务完整性的启动前检查。
    enable_set = {"StartUp", "Infrast", "Recruit", "Mall", "Award"}
    if enabled_tasks is None:
        enabled_tasks = enable_set
    else:
        enabled_tasks = set(enabled_tasks)

    # 必须在MAA进程启动前把任务清单写入配置。MAA启动后只读内存配置；
    # 此时再改gui.new.json虽然文件正确，当前窗口仍会显示“未选择任务”。
    # 若发现已有空闲窗口且配置发生变化，先关闭它让下一次启动真实重载。
    try:
        config_path = os.path.join(MAA_CONFIG, "gui.new.json")
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        before = [(t.get("TaskType"), t.get("IsEnable")) for t in _task_queue(cfg)]
        _set_enabled_tasks(cfg, enabled_tasks)
        after = [(t.get("TaskType"), t.get("IsEnable")) for t in _task_queue(cfg)]
        changed = before != after
        if changed:
            _atomic_write_json(config_path, cfg)
            if _maa_process_exists() is True:
                reload_maa_after_config_switch(
                    f"TaskQueue切换为{','.join(sorted(enabled_tasks))}"
                )
            log(f"✅ MAA TaskQueue已落盘并等待重载: {','.join(sorted(enabled_tasks))}")
        else:
            log("✅ MAA TaskQueue配置正常")
    except Exception as e:
        log(f"❌ 配置MAA TaskQueue失败: {e}", "ERROR")
        return False
    
    # 只接受真实 MAA.exe 拥有的窗口。Codex/WorkBuddy任务标题也可能包含
    # “MAA”，仅按标题匹配会把其他应用的按钮当成 Link Start。
    maa = _find_real_maa_window(ua)
    
    # 如果没找到, 启动MAA.exe并等待窗口出现
    if not maa:
        log("→ MAA未运行, 启动MAA.exe...")
        try:
            _launch_maa_for_background_control()
        except Exception as e:
            log(f"❌ MAA启动失败: {e}", "ERROR")
            return False
        # 等待窗口出现 (最多30s — MAA启动较慢)
        for i in range(30):
            wait(1)
            maa = _find_real_maa_window(ua)
            if maa:
                break
        if not maa:
            log("❌ MAA窗口未出现(等30s)", "ERROR")
            return False
        log("✅ MAA窗口已出现")
        wait(5)  # 等MAA UI完全加载

    maa = _finalize_maa_update_before_control(ua, maa)
    if not maa:
        return False
    
    # 日常控制同样不得置顶或抢用户鼠标键盘。
    wait(0.5)
    
    # 🔴 2026-07-07 修复: 切到TaskQueue标签 (之前是空循环, Link Start在TaskQueue页才找得到)
    # MAA可能在Copilot页(跑完作业后停在Copilot), 必须切回TaskQueue才能找到Link Start
    import uiautomation as _ua
    def _find_tab(root, depth=0):
        if depth > 5: return None
        for c in root.GetChildren():
            name = str(c.Name)
            if c.ControlType == _ua.ControlType.TabItemControl and ('TaskQueue' in name or '一键' in name or '长草' in name):
                return c
            r = _find_tab(c, depth+1)
            if r: return r
        return None
    _tab = None
    for tab_attempt in range(10):
        # 冷启动时窗口已出现但内容树可能仍为空；每轮重取窗口避免缓存节点失效。
        try:
            maa = _find_real_maa_window(ua) or maa
            _tab = _find_tab(maa)
        except Exception:
            _tab = None
        if _tab:
            break
        if tab_attempt < 9:
            log(f"  TaskQueue页面尚未装载，刷新控件树 {tab_attempt + 1}/10", "WARN")
            wait(2)
    if _tab:
        log("→ 切换到TaskQueue标签")
        try:
            _tab.GetSelectionItemPattern().Select()
        except Exception:
            try:
                _tab.GetInvokePattern().Invoke()
            except Exception as e:
                log(f"❌ 无法在后台切换TaskQueue标签: {e}", "ERROR")
                return False
        wait(2)
    else:
        log("⚠️ 未找到TaskQueue标签, 尝试继续", "WARN")
    
    # 🔴 找Link Start按钮 (加重试3次, MAA UI加载需要时间, 2026-06-29修复)
    # 🔴 2026-06-29关键修复1: MAA窗口可能在副屏(left为负), 旧过滤r.left>100会漏掉!
    # 🔴 2026-06-29关键修复2: 有多个Link Start按钮(d=3主页/d=6其他页), 必须选最浅深度的!
    #   Link Start按钮真实名称="Link Start!"(带感叹号)
    link_btn = None
    for find_attempt in range(10):
        link_btn = None
        best_depth = 99
        def find_link(root, d=0):
            nonlocal link_btn, best_depth
            if d > 12 or d >= best_depth: return
            for c in root.GetChildren():
                if c.ControlTypeName == "ButtonControl":
                    name = str(c.Name)
                    if "Link" in name and "Start" in name:
                        try:
                            r = c.BoundingRectangle
                            if not (r.left == 0 and r.top == 0 and r.right == 0 and r.bottom == 0):
                                if d < best_depth:
                                    link_btn = c
                                    best_depth = d
                        except: pass
                find_link(c, d+1)
        find_link(maa)
        if link_btn:
            try:
                r = link_btn.BoundingRectangle
                log(f"  [Link Start] 找到按钮 d={best_depth} rect=({r.left},{r.top},{r.right},{r.bottom})")
            except: pass
            break
        if find_attempt < 9:
            log(f"  Link Start未找到(第{find_attempt+1}次), 刷新MAA UI...")
            wait(2)

    if link_btn:
        # 只允许后台Invoke；禁止Click/移动鼠标，避免干扰用户操作。
        try:
            # 必须在Invoke之前切日志边界。MAA可能在Invoke返回前就写入
            # TaskChainStart；若事后才记行号，等待器会漏掉启动事件并误报90秒未启动。
            global _LAST_MAA_RUN_START_LINE, _LAST_MAA_RUN_LOG
            try:
                with open(MAA_LOG, 'r', encoding='utf-8', errors='replace') as f:
                    _LAST_MAA_RUN_START_LINE = sum(1 for _line in f)
            except Exception:
                _LAST_MAA_RUN_START_LINE = 0
            _LAST_MAA_RUN_LOG = ""
            link_btn.GetInvokePattern().Invoke()
            log("  [Link Start] Invoke()成功")
        except Exception as e:
            log(f"❌ Link Start后台调用失败(未使用鼠标): {e}", "ERROR")
            return False
        log("✅ MAA日常任务链已启动")
        # TaskQueue 的 Link Start 也会把 MAA 配置窗带到前台。与 Copilot
        # 保持同一条显示契约：后台 Invoke 启动后把游戏画面还给用户观看，
        # 不使用鼠标点击，也不干预已经运行的 MAA 队列。
        wait(1)
        _foreground_mumu_display()
        return True

    log("❌ Link Start按钮未找到(约30秒恢复后)", "ERROR")
    return False

def _taskchain_status(log_text, chain):
    """按该任务链最后一个终态判断结果；重试成功可以覆盖更早的失败。"""
    started = f'"taskchain":"{chain}"' in (log_text or "")
    terminal = []
    for match in re.finditer(
        rf'(TaskChainCompleted|TaskChainError)[^\n\r]*"taskchain":"{re.escape(chain)}"',
        log_text or "",
    ):
        terminal.append((match.start(), match.group(1)))
    last = terminal[-1][1] if terminal else None
    return {
        "started": started,
        "completed": last == "TaskChainCompleted",
        "errored": last == "TaskChainError",
        "ok": last == "TaskChainCompleted",
    }


def _failed_taskchains(log_text):
    chains = set(re.findall(r'"taskchain":"([^"]+)"', log_text or ""))
    return sorted(chain for chain in chains if _taskchain_status(log_text, chain)["errored"])


def _stopped_taskchains(log_text):
    return sorted(set(re.findall(
        r'TaskChainStopped\s+\{"taskchain":"([^"]+)"', log_text or ""
    )))


def _maa_wait_decision(log_text, continue_after_chain_error=False):
    """把队列级完成与子任务失败分开，返回(completed/failed/running, 失败链)。"""
    failed = _failed_taskchains(log_text)
    if "AllTasksCompleted" in (log_text or ""):
        return ("completed_with_errors" if failed else "completed", failed)
    stopped = _stopped_taskchains(log_text)
    if stopped:
        return "stopped", stopped
    if failed and not continue_after_chain_error:
        return "failed", failed
    return "running", failed


def _merge_maa_log_segment(accumulated, previous_segment, current_segment):
    """保留asst.log轮转前后的本轮证据，并替换正常增长的当前片段。"""
    accumulated = accumulated or ""
    previous_segment = previous_segment or ""
    current_segment = current_segment or ""
    if not previous_segment:
        return current_segment
    if current_segment.startswith(previous_segment):
        if accumulated.endswith(previous_segment):
            return accumulated[:-len(previous_segment)] + current_segment
        return accumulated + current_segment[len(previous_segment):]
    if current_segment and current_segment != previous_segment:
        return accumulated + "\n# MAA LOG ROTATION\n" + current_segment
    return accumulated


def _join_bounded_indexed_lines(indexed_lines, max_chars=None):
    """按原日志顺序拼接，并在超限时同时保留最早边界和最新终态。"""
    max_chars = int(max_chars or MAA_LOG_MEMORY_MAX_CHARS)
    ordered = sorted({int(index): line for index, line in indexed_lines}.items())
    total = sum(len(line) for _index, line in ordered)
    if total <= max_chars:
        return "".join(line for _index, line in ordered)

    marker = "\n# MAA IN-MEMORY EVIDENCE COMPACTED\n"
    head_budget = max(1, max_chars // 4)
    tail_budget = max(1, max_chars - head_budget - len(marker))
    head = []
    used = 0
    for item in ordered:
        if head and used + len(item[1]) > head_budget:
            break
        head.append(item)
        used += len(item[1])

    head_indexes = {index for index, _line in head}
    tail = []
    used = 0
    for item in reversed(ordered):
        if item[0] in head_indexes:
            continue
        if tail and used + len(item[1]) > tail_budget:
            break
        tail.append(item)
        used += len(item[1])
    tail.reverse()
    return "".join(line for _index, line in head) + marker + "".join(
        line for _index, line in tail
    )


def _read_bounded_maa_log(after_line=0, path=None):
    """流式读取MAA日志，返回有界证据、最近尾部和累计活动量。

    ``after_line``超出当前文件时表示日志已轮转/截断；此时只取当前文件最近
    ``MAA_LOG_ROTATION_FALLBACK_LINES``行，避免把旧行号误作空证据。函数不把
    整个日志装进列表，内存占用与日志文件大小解耦。
    """
    path = path or MAA_LOG
    after_line = max(0, int(after_line or 0))
    fallback = deque(maxlen=MAA_LOG_ROTATION_FALLBACK_LINES)
    recent = deque(maxlen=MAA_LOG_EVIDENCE_TAIL_LINES)
    evidence_head = []
    evidence_tail = deque()
    evidence_head_chars = 0
    evidence_tail_chars = 0
    marker_chars = len("\n# MAA IN-MEMORY EVIDENCE COMPACTED\n")
    evidence_head_budget = max(1, MAA_LOG_MEMORY_MAX_CHARS // 4)
    evidence_tail_budget = max(
        1, MAA_LOG_MEMORY_MAX_CHARS - evidence_head_budget - marker_chars
    )
    activity_chars = 0
    total_lines = 0

    with open(path, "r", encoding="utf-8", errors="replace") as stream:
        for index, line in enumerate(stream):
            total_lines = index + 1
            fallback.append((index, line))
            if index < after_line:
                continue
            activity_chars += len(line)
            recent.append((index, line))
            if any(marker in line for marker in _MAA_LOG_EVIDENCE_MARKERS):
                if evidence_head_chars < evidence_head_budget:
                    evidence_head.append((index, line))
                    evidence_head_chars += len(line)
                else:
                    evidence_tail.append((index, line))
                    evidence_tail_chars += len(line)
                    while len(evidence_tail) > 1 and evidence_tail_chars > evidence_tail_budget:
                        _old_index, old_line = evidence_tail.popleft()
                        evidence_tail_chars -= len(old_line)

    rotated = after_line > 0 and total_lines <= after_line
    if rotated:
        selected = list(fallback)
        structured = list(fallback)
        recent = deque(fallback, maxlen=MAA_LOG_EVIDENCE_TAIL_LINES)
        activity_chars = sum(len(line) for _index, line in fallback)
    else:
        evidence = evidence_head + list(evidence_tail)
        selected = evidence + list(recent)
        structured = evidence

    return {
        "evidence_text": _join_bounded_indexed_lines(selected),
        # 只含稳定的结构化事件，用于跨轮询/跨日志轮转累计。最近尾部会随
        # 每次轮询滑动，若拿它判断“文件是否增长”，会被误判成日志轮转并
        # 反复追加相同内容。轮转时旧行号失效，才用当前文件有界尾部兜底。
        "structured_text": _join_bounded_indexed_lines(structured),
        "tail_text": "".join(line for _index, line in recent),
        "activity_chars": activity_chars,
        "line_count": total_lines,
        "rotated": rotated,
    }


def _initialize_current_run_evidence_boundary(now=None):
    """在任何MAA动作之前固定本进程日志边界。"""
    global _LAST_MAA_RUN_START_LINE, _LAST_MAA_RUN_LOG, _LAST_MAA_RUN_SEGMENT
    global _CURRENT_RUN_STARTED_AT, _CURRENT_RUN_EVIDENCE_BOUNDARY_READY
    _CURRENT_RUN_STARTED_AT = now or datetime.now()
    try:
        with open(MAA_LOG, "r", encoding="utf-8", errors="replace") as stream:
            _LAST_MAA_RUN_START_LINE = sum(1 for _line in stream)
    except OSError:
        _LAST_MAA_RUN_START_LINE = 0
    _LAST_MAA_RUN_LOG = ""
    _LAST_MAA_RUN_SEGMENT = ""
    _CURRENT_RUN_EVIDENCE_BOUNDARY_READY = True
    boundary = {
        "initialized_at": _CURRENT_RUN_STARTED_AT.isoformat(timespec="seconds"),
        "maa_log_start_line": _LAST_MAA_RUN_START_LINE,
        "source": os.path.abspath(MAA_LOG),
    }
    _RUN_SUMMARY["run_evidence_boundary"] = boundary
    log(
        "  [本轮证据边界] 已在MAA动作前建立: "
        f"line={_LAST_MAA_RUN_START_LINE}, time={boundary['initialized_at']}"
    )
    return boundary


def _maa_log_not_before_current_run(text):
    """日志轮换时按时间再次裁切，旧日志永远不能回流进本轮日报。"""
    if not text or _CURRENT_RUN_STARTED_AT is None:
        return text or ""
    threshold = _CURRENT_RUN_STARTED_AT - timedelta(seconds=2)
    kept = []
    for line in text.splitlines(keepends=True):
        match = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\]", line)
        if not match:
            if kept:
                kept.append(line)
            continue
        try:
            stamp = datetime.fromisoformat(match.group(1))
        except ValueError:
            continue
        if stamp >= threshold:
            kept.append(line)
    return "".join(kept)


def wait_maa_complete(
    timeout=900,
    continue_after_chain_error=False,
    resume_existing=False,
    prestarted_boundary=False,
    active_battle_extension=1800,
):
    """等待MAA任务链完成 (最多15分钟, 含错误检测)
    
    🔴 2026-06-29 严格判据重写:
    - 完成判据: 必须在本次run日志中出现 AllTasksCompleted
    - 不再用"主界面+时间"作为完成判据 (Infrast中途会经过主界面导致误判)
    - 记录本次run的日志起始行, 只检查本次新增日志
    - Copilot/Fight默认遇TaskChainError立即返回；日常队列可继续等到AllTasksCompleted
    - task_started: 检测TaskChainStart或battle状态确认MAA已启动
    """
    global _LAST_MAA_RUN_START_LINE, _LAST_MAA_RUN_LOG, _LAST_MAA_RUN_SEGMENT
    log(f"等待MAA任务完成(基础时限{timeout}s)...")
    start = time.time()
    effective_timeout = timeout
    battle_wait_extended = False
    # 🔴 记录MAA日志起始行, 只检查本次新增的日志
    maa_log_start_line = 0
    try:
        with open(MAA_LOG, 'r', encoding='utf-8', errors='replace') as f:
            existing_line_count = sum(1 for _line in f)
        if resume_existing:
            # 崩溃恢复时接管正在运行的队列：从最近一次队列完成之后读取，
            # 保留StartUp/Infrast等已发生事件，而不是从接管时刻截断证据。
            with open(MAA_LOG, 'r', encoding='utf-8', errors='replace') as f:
                last_all_done = max(
                    (i for i, line in enumerate(f) if "AllTasksCompleted" in line),
                    default=-1,
                )
            maa_log_start_line = last_all_done + 1
        elif prestarted_boundary:
            # 正常启动由run_maa_daily_tasks在点击Link Start之前记录边界，
            # 防止TaskChainStart在Invoke返回前写入而被截掉；0也是有效行号。
            maa_log_start_line = max(0, _LAST_MAA_RUN_START_LINE)
        else:
            maa_log_start_line = existing_line_count
    except: pass
    # 🔴 全局保存, 供generate_daily_report使用
    _LAST_MAA_RUN_START_LINE = maa_log_start_line
    _LAST_MAA_RUN_LOG = ""
    _LAST_MAA_RUN_SEGMENT = ""
    task_started = bool(resume_existing)  # 🔴 追踪MAA任务链是否真正启动
    last_chain = ""  # 🔴 追踪当前任务链名称

    while time.time() - start < effective_timeout:
        wait(30)
        el = int(time.time() - start)

        # 🔴 先获取游戏状态 (仅用于task_started判断, 不再用于完成判据)
        try:
            state = get_state()
        except:
            state = "unknown"

        # 读asst.log检查完成状态
        try:
            snapshot = _read_bounded_maa_log(maa_log_start_line)
            # 结构化证据与最近尾部由流式读取器产生；不会再随64MiB日志线性复制。
            full_run_text = snapshot["evidence_text"]
            stable_run_text = snapshot["structured_text"]
            log_text = snapshot["tail_text"]
            # 保存直接观察到的本轮证据。MAA在长时间Infrast期间会把
            # asst.log轮转为asst.bak.log：新文件虽含AllTasksCompleted，却
            # 不再含StartUp。按“当前文件片段”识别正常增长或轮转并拼接，
            # 避免最终报告把真实完成的StartUp误记为未执行。
            _LAST_MAA_RUN_LOG = _join_bounded_indexed_lines(enumerate(
                _merge_maa_log_segment(
                    _LAST_MAA_RUN_LOG,
                    _LAST_MAA_RUN_SEGMENT,
                    stable_run_text,
                ).splitlines(keepends=True)
            ))
            _LAST_MAA_RUN_SEGMENT = stable_run_text

            # 🔴 检查任务链是否启动
            if not task_started:
                # 肉鸽启动阶段日志非常密集，第一次30秒轮询时启动行可能已经
                # 超出末尾800行；启动证据必须查本轮完整切片，不能只查尾部。
                if "TaskChainStart" in full_run_text or "append_task" in full_run_text.lower():
                    task_started = True
                    # 🔴 提取当前任务链名称
                    m = re.search(r'"taskchain":"([^"]+)"', full_run_text)
                    if m:
                        last_chain = m.group(1)
                        log(f"  {el}s: ✅ MAA任务链已启动 (当前: {last_chain})")
                    else:
                        log(f"  {el}s: ✅ MAA任务链已启动")
                elif state == "battle":
                    task_started = True
                    log(f"  {el}s: ✅ MAA任务链已启动(检测到战斗状态)")
                elif el > 90:
                    log(f"  {el}s: ❌ MAA任务链90s未启动(无TaskChainStart且非战斗状态)", "ERROR")
                    return "maa_not_started"

            # 🔴 实时追踪当前任务链 (用于日志可读性)
            if task_started:
                chains_in_log = re.findall(r'"taskchain":"([^"]+)"', log_text)
                if chains_in_log:
                    cur_chain = chains_in_log[-1]
                    if cur_chain != last_chain:
                        last_chain = cur_chain
                        log(f"  {el}s: → 任务链切换到: {cur_chain}")

            decision, failed_chains = _maa_wait_decision(
                full_run_text,
                continue_after_chain_error=continue_after_chain_error,
            )
            # 🔴 完成判据: 必须出现 AllTasksCompleted (在本次run内)
            if decision == "completed":
                log(f"  {el}s: ✅ MAA全部任务完成 (AllTasksConfirmed)")
                _guard_check("G04", context="wait_maa_complete用AllTasksCompleted判据", 
                             condition=True)
                return True
            if decision == "completed_with_errors":
                log(
                    f"  {el}s: ⚠️ MAA队列已结束，但失败链需补跑: {', '.join(failed_chains)}",
                    "WARN",
                )
                return "maa_completed_with_errors"
            if decision == "failed":
                log(f"  {el}s: ❌ TaskChainError: {', '.join(failed_chains)}", "ERROR")
                return "maa_taskchain_error"
            if decision == "stopped":
                log(f"  {el}s: ⏹ MAA任务已停止: {', '.join(failed_chains)}", "WARN")
                return "maa_stopped"
            if failed_chains:
                log(
                    f"  {el}s: ⚠️ 子任务出错但MAA仍在继续: {', '.join(failed_chains)}",
                    "WARN",
                )
        except:
            pass

        # 🔴 不再用"主界面+时间"作为完成判据!
        # 仅在日志中输出当前状态供观察
        if task_started:
            log(f"  {el}s: 等待中... (状态={state}, 链={last_chain})")
        else:
            log(f"  {el}s: 等待中... (状态={state})")

        # 基础时限只是异常检查点，不是强制中止点。保全派驻等长战斗可能在
        # 30分钟后仍正常推进；此时停止MAA会破坏正在进行的战斗，并把真实
        # 成功误记为失败。只在游戏画面明确仍为battle时延长一次，unknown、
        # 编队页或中间页均不放宽，额外上限仍保证真正卡死能够退出。
        if (
            not battle_wait_extended
            and active_battle_extension > 0
            and el >= timeout
            and task_started
            and state == "battle"
        ):
            battle_wait_extended = True
            effective_timeout = timeout + active_battle_extension
            log(
                f"  {el}s: ⏳ 基础时限已到，但游戏仍在真实战斗；"
                f"继续等待最多{active_battle_extension}s，不停止MAA",
                "WARN",
            )

    log(f"  超时({effective_timeout}s)")
    return False


def _get_current_maa_run_log():
    """返回本轮MAA日志；优先使用等待器保存的快照，兼容日志轮换。"""
    if _LAST_MAA_RUN_LOG:
        return _LAST_MAA_RUN_LOG
    try:
        text = _read_bounded_maa_log(_LAST_MAA_RUN_START_LINE)["evidence_text"]
        return _maa_log_not_before_current_run(text)
    except Exception:
        return ""


def _maa_gui_queue_state(text):
    """返回MAA GUI队列的最新状态；恢复流程只区分running与idle。"""
    text = text or ""
    running_markers = [
        text.rfind("正在运行中……"),
        text.rfind("Start Task Chain:"),
        text.rfind("开始任务:"),
    ]
    # A long Roguelike queue can push its original start line out of the
    # bounded tail.  Only semantic business callbacks count as continuing
    # activity.  The generic TaskQueueViewModel prefix also appears on
    # LinkStart Exit after a failed connection and must never revive an idle
    # queue by itself.
    for marker in (
        "已开始探索",
        "关卡:",
        "开始战斗:",
        "战斗完成",
        "战斗失败",
        "事件:",
        "节点:",
        "已投资",
        "肉鸽结算:",
    ):
        running_markers.append(text.rfind(marker))
    running = max(running_markers)
    ended = max(
        text.rfind("任务已全部完成"),
        text.rfind("Completed Task Chain:"),
        text.rfind("TaskChainError"),
        text.rfind("Post actions:"),
        text.rfind("已停止"),
        text.rfind("Idle: false to true"),
        text.rfind("called from SetStopped"),
    )
    return "running" if running > ended else "idle"


def _maa_process_exists():
    try:
        return "MAA.exe" in _tasklist_snapshot()
    except Exception:
        return None


def _tasklist_snapshot():
    """读取真实进程表；查询失败必须显式报错，不能被解释成“全部已关闭”。"""
    result = subprocess.run(
        ["tasklist"], capture_output=True, encoding="gbk", errors="replace", timeout=8,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "未知错误").strip()
        raise RuntimeError(f"tasklist失败: {detail}")
    return result.stdout or ""


def _running_process_images(image_names):
    """返回仍在运行的目标镜像；进程表不可读时返回None。"""
    try:
        snapshot = _tasklist_snapshot().lower()
    except Exception as e:
        log(f"  ⚠️ 无法核对进程状态: {e}", "WARN")
        return None
    return [name for name in image_names if name.lower() in snapshot]


def _maa_task_queue_running():
    process_exists = _maa_process_exists()
    if process_exists is False:
        return False
    try:
        with open(MAA_GUI_LOG, "r", encoding="utf-8") as f:
            text = f.read()[-250000:]
        return _maa_gui_queue_state(text) == "running"
    except Exception:
        return False


def _maa_daily_queue_running():
    """True only for the five-chain daily queue, never for a Copilot residue."""
    if _maa_process_exists() is not True:
        return False
    try:
        with open(MAA_GUI_LOG, "r", encoding="utf-8") as f:
            text = f.read()[-250000:]
    except Exception:
        return False
    if _maa_gui_queue_state(text) != "running":
        return False
    starts = list(re.finditer(r"Start Task Chain:\s*([^,\r\n]+)", text))
    if not starts:
        return False
    latest_chain = starts[-1].group(1).strip()
    return latest_chain in {"StartUp", "Infrast", "Recruit", "Mall", "Award"}


def _prepare_daily_maa_boundary(reason):
    """活动/Fight到日常的唯一边界：运行中只接管，空闲时才重载配置。"""
    if _maa_daily_queue_running():
        log(f"  [日常恢复] MAA队列仍在运行，禁止结束进程：{reason}")
        return "resume"
    reload_maa_after_config_switch(reason)
    return "restart"

# ============================================================
# 战斗验证
# ============================================================

def check_maa_errors(after_line=0):
    """检查MAA日志中的错误标记 (战斗出错/练度不足/干员缺失)
    
    MAA错误模式 (asst.log):
    - OperatorMissing / reason:"Missing" → 干员缺失(练度不足/没有该干员)
    - SubTaskError + BattleFormationTask → 编队失败
    - TaskChainError + Copilot → Copilot任务链出错
    - BattleStartPre SubTaskError → 战斗启动失败
    
    返回: (has_error: bool, error_type: str, detail: str)
    """
    try:
        snapshot = _read_bounded_maa_log(after_line)
        log_text = snapshot["evidence_text"]

        # 新活动刚开放而本地资源尚未热更新时，MaaCore会在真正进入战斗前
        # 明确给出UnsupportedLevel/Not support stage。它属于技术错误，
        # 不能继续在编队页空等3分钟，更不能计作关卡或作业失败。
        if (
            '"what":"UnsupportedLevel"' in log_text
            or "Not support stage" in log_text
        ):
            stage_match = re.search(r'"level":"([^"]+)"', log_text)
            stage = stage_match.group(1) if stage_match else "未知内部关卡"
            return (
                True,
                "unsupported_level",
                f"MAA资源尚不支持关卡: {stage}",
            )
        
        # 干员缺失本身不一定是终态：MAA可能继续选择作业里声明的替代干员。
        # 只有同一次新增日志中，Missing之后又出现Copilot TaskChainError，
        # 才能确认自动编队已经终止。此时错误可明确归因到当前作业，应换作业，
        # 而不是把它升级为总控技术错误并冻结全天剩余理智。
        missing_pos = max(
            log_text.rfind("OperatorMissing"),
            log_text.rfind('"reason":"Missing"'),
        )
        copilot_chain_error_pos = log_text.rfind("TaskChainError")
        if (
            missing_pos >= 0
            and copilot_chain_error_pos > missing_pos
            and '"taskchain":"Copilot"' in log_text[copilot_chain_error_pos:]
        ):
            missing_record_start = log_text.rfind("SubTaskError", 0, missing_pos)
            if missing_record_start < 0:
                missing_record_start = max(0, log_text.rfind("\n", 0, missing_pos))
            missing_segment = log_text[missing_record_start:copilot_chain_error_pos]
            name_match = re.search(
                r'"name":"([^"]+)","reason":"Missing"',
                missing_segment,
            )
            name = name_match.group(1) if name_match else "未知干员"
            return (
                True,
                "formation_unavailable",
                f"自动编队缺少作业干员且MAA已终止: {name}",
            )

        # MAA已经完成账号侧校验并明确指出指定模组/技能/练度不满足。
        # 这不是可由后续战斗弥补的告警；继续启动只会形成残缺阵容。
        if '"what":"BattleFormationOperUnavailable"' in log_text:
            name_match = re.search(r'"oper_name":"([^"]+)"', log_text)
            type_match = re.search(r'"requirement_type":"([^"]+)"', log_text)
            name = name_match.group(1) if name_match else "未知干员"
            requirement = type_match.group(1) if type_match else "配置"
            return (
                True,
                "formation_unavailable",
                f"自动编队不满足作业要求: {name} ({requirement})",
            )
        
        # 编队失败 - 同样不立即返回! MAA可能用替代干员继续
        # if "BattleFormationTask" in log_text and "SubTaskError" in log_text:
        #     return (True, "formation_error", "编队失败(可能干员不可用)")
        
        # Copilot任务链错误
        if "TaskChainError" in log_text and "Copilot" in log_text:
            return (True, "taskchain_error", "Copilot任务链出错")
        
        # 🔴 战斗启动失败: BattleStartPre SubTaskError不一定是真的失败
        # (可能只是跳过剧情失败, 战斗仍在进行), 不立即返回错误
        # 只有TaskChainError才算真正失败
        
        return (False, "", "")
    except:
        return (False, "", "")


def read_maa_copilot_status(after_line=0):
    """读取本次Copilot日志状态，供图像状态交叉验证。"""
    try:
        snapshot = _read_bounded_maa_log(after_line)
        text = snapshot["tail_text"]
    except Exception as e:
        return {"status": "unavailable", "activity": 0, "detail": str(e)}

    lower = text.lower()
    status = "unknown"
    detail = ""
    if "TaskChainError" in text and "Copilot" in text:
        status, detail = "error", "Copilot TaskChainError"
    elif any(marker in text for marker in ("TaskChainStopped", "CopilotTask stopped", "AsstStop")):
        status, detail = "stopped", "Copilot已停止"
    elif any(marker in lower for marker in ("copilot paused", "taskchainpaused", "task chain paused")):
        status, detail = "paused", "Copilot已暂停"
    elif (
        "Completed Task Chain: Copilot" in text
        or (("TaskChainCompleted" in text or "AllTasksCompleted" in text) and "Copilot" in text)
    ):
        status, detail = "completed", "Copilot任务链完成"
    elif any(marker in text for marker in (
        "BattleProcessTask", "BattleFormationTask", "BattleStartTask",
        "pause_button_analyze", '"taskchain":"Copilot"',
    )):
        status, detail = "running", "Copilot日志持续推进"

    return {
        "status": status,
        "activity": snapshot["activity_chars"],
        "detail": detail,
    }

def _battle_has_leak(image_path):
    """只检测顶部生命栏右侧的红底白字扣减标签。

    只统计红色仍会把贴近顶栏的敌方红门轮廓误判成漏怪；真实标签必须
    同时具备密集红底和白色心形/负数字形。两项缺一均视为地图物件。
    """
    try:
        from PIL import Image
        with Image.open(image_path) as source:
            im = source.convert("RGB")
            w, h = im.size
            # 实机1920x1080: 红底“心形× -N”约在 x=1210..1350, y=8..68。
            crop = im.crop((int(w * 0.63), int(h * 0.007), int(w * 0.703), int(h * 0.063)))
            red_pixels = sum(
                1 for r, g, b in crop.getdata()
                if r > 120 and r > g * 1.8 and r > b * 1.5
            )
            white_pixels = sum(
                1 for r, g, b in crop.getdata()
                if r > 200 and g > 200 and b > 200 and max(r, g, b) - min(r, g, b) < 35
            )
            area = crop.width * crop.height
            return (
                red_pixels >= max(700, int(area * 0.08))
                and white_pixels >= max(80, int(area * 0.008))
            )
    except Exception as e:
        log(f"  [漏怪检测] 图形分析失败: {e}", "WARN")
        return False


def _battle_selection_overlay_visible(text):
    """识别战斗中长期残留的干员/装置选中详情框。"""
    normalized = str(text or "")
    markers = ("攻击", "防御", "法抗", "阻挡", "技能")
    return sum(marker in normalized for marker in markers) >= 3


def _victory_three_star_status(image_path):
    """读取结算页左侧三枚独立蓝色徽记；三枚齐亮即为完美通关。"""
    try:
        from PIL import Image

        with Image.open(image_path) as source:
            image = source.convert("RGB")
            # 1920x1080实机结算页：三枚徽记固定排列在左侧。逐槽判断，不能用
            # 一整块蓝色像素总量代替，否则一枚特效过亮也可能伪装成三星。
            boxes = (
                (85, 415, 205, 535),
                (195, 415, 315, 535),
                (305, 415, 425, 535),
            )
            ratios = []
            for box in boxes:
                crop = image.crop(box)
                cyan = sum(
                    1
                    for r, g, b in crop.getdata()
                    if b > 120 and g > 90 and b > r * 1.35 and g > r * 1.2
                )
                ratios.append(cyan / max(1, crop.width * crop.height))
            lit = sum(ratio >= 0.12 for ratio in ratios)
            return {"lit": lit, "ratios": ratios, "perfect": lit == 3}
    except Exception as exc:
        log(f"  [结算徽记] 图形分析失败: {exc}", "WARN")
        return {"lit": 0, "ratios": [], "perfect": False}


def verify_battle(timeout=300, stage_name=None):
    """等待战斗完成并交叉验证；活动中的真实战斗不设固定时长上限。

    ``timeout`` 仅保留以兼容旧调用者，不再作为战斗硬截止时间。只有画面已
    离开战斗且MAA日志也连续5分钟没有变化时，才按失联退出。
    """
    global _LAST_VERIFY_ENTERED_BATTLE
    _LAST_VERIFY_ENTERED_BATTLE = False
    log("  等待战斗(活动期间无固定时长上限)...")
    start = time.time()
    last_k = ""
    last_k_change_time = time.time()
    kills_full_time = None
    maa_error_checked = False
    last_maa_status = None
    last_maa_activity = -1
    last_maa_activity_time = time.time()
    last_visual_check = 0
    # 部分主线关会在第一段自动战斗结束后插入剧情，再显示0/3中段页，
    # 点击后才进入后续自动战斗。该页面不是最终结算，不能交给通用复位流程，
    # 否则 _force_to_chapter_map 会把正在进行的后半段当异常战斗放弃。
    post_maa_story_seen = False
    segment_advance_count = 0
    battle_record_sync_retries = 0
    leak_confirmed = False
    # 🔴 关键: 记录当前MAA日志行数, 只检查本次新增的日志
    maa_log_start_line = 0
    try:
        with open(MAA_LOG, 'r', encoding='utf-8', errors='replace') as f:
            maa_log_start_line = sum(1 for _line in f)
    except: pass
    
    while True:
        # MAA日志轻量轮询5秒一次；正常战斗截图/OCR每30秒一次。
        wait(5)
        el = int(time.time() - start)
        
        # 🔴 优先检查MAA错误 (战斗出错/干员缺失)
        has_err, err_type, err_detail = check_maa_errors(maa_log_start_line)
        if has_err:
            log(f"  {el}s: ❌ MAA错误: {err_detail}", "ERROR")
            return f"maa_{err_type}"  # 返回具体错误类型

        maa = read_maa_copilot_status(maa_log_start_line)
        if maa["activity"] != last_maa_activity:
            last_maa_activity = maa["activity"]
            last_maa_activity_time = time.time()
        if maa["status"] != last_maa_status:
            log(f"  {el}s: [MAA监控] {maa['status']} {maa['detail']}")
            last_maa_status = maa["status"]
        if maa["status"] == "stopped":
            # MAA 的 Copilot 在已经进入战斗后，可能因为某个部署动作长期无法
            # 完成而自行停止。今天 TO-EX-1 的直接证据是：画面一直停在
            # 0/129，凛御银灰已落地，圣聆初雪部署动作等待约 420 秒后
            # TaskChainStopped。这个终态能够归因到当前作业/控制组合，应换
            # 不同作业，而不是把它升级成基础设施故障并冻结整天理智。
            stalled_for = time.time() - last_k_change_time
            if (
                _LAST_VERIFY_ENTERED_BATTLE
                and last_k
                and stalled_for >= 120
            ):
                log(
                    f"  {el}s: MAA已停止，且真实战斗击杀{last_k}连续"
                    f"{int(stalled_for)}秒无推进；判定当前作业控制死锁并切换作业",
                    "ERROR",
                )
                return "maa_control_stall"
            log(f"  {el}s: MAA状态异常: {maa['detail']}", "ERROR")
            return "maa_stopped"
        if maa["status"] == "error":
            # MAA GUI/Core 的终态日志并非原子落盘。实机 TO-EX-7 中，监督器
            # 先读到了 Copilot TaskChainError，约几百毫秒后 asst.log 才补出
            # OperatorMissing(予愿安洁莉娜)。给终态一个很短的落盘宽限期，
            # 优先把可归因的编队不兼容交给换作业逻辑；宽限后仍只有通用
            # TaskChainError 才按技术错误冻结，绝不把未知错误猜成缺干员。
            terminal_error = (False, "", "")
            for grace_attempt in range(3):
                if grace_attempt:
                    wait(1)
                candidate = check_maa_errors(maa_log_start_line)
                if candidate[0]:
                    terminal_error = candidate
                    if candidate[1] != "taskchain_error":
                        break
            if terminal_error[0]:
                _has_err, terminal_type, terminal_detail = terminal_error
                log(f"  {el}s: ❌ MAA终态复核: {terminal_detail}", "ERROR")
                return f"maa_{terminal_type}"
            log(f"  {el}s: MAA状态异常: {maa['detail']}", "ERROR")
            return "maa_error"
        if maa["status"] == "paused":
            log(f"  {el}s: MAA状态异常: {maa['detail']}", "ERROR")
            return "maa_paused"

        if maa["status"] != "completed" and time.time() - last_visual_check < 30:
            continue
        last_visual_check = time.time()
        
        state = get_state()

        if state == "battle_record_sync_error":
            battle_record_sync_retries += 1
            retry_path = shot(f"battle_record_sync_retry_{battle_record_sync_retries}")
            retry_pos = find_text(ocr(retry_path), "重试")
            if battle_record_sync_retries <= 3:
                # 1920x1080实机右侧按钮中心是(1265,742)；OCR定位优先，固定
                # 坐标仅用于对话框文字被字体/遮罩拆分时的同一按钮兜底。
                retry_pos = retry_pos or (1265, 742)
                log(
                    f"  {el}s: 战斗记录同步失败，点击重试 "
                    f"{battle_record_sync_retries}/3 @{retry_pos}",
                    "WARN",
                )
                tap(*retry_pos)
                wait(5)
                # 点击后立刻复查，不受正常战斗30秒截图节流影响。
                last_visual_check = 0
                continue
            log(
                "  战斗记录同步连续3次失败；战斗已经发生但结算无法闭环，"
                "停止本关且禁止重复扣理智",
                "ERROR",
            )
            return "completed_sync_blocked"

        if maa["status"] == "completed":
            if state == "formation":
                log(
                    f"  {el}s: MAA已结束但仍停在编队页；"
                    "判定当前作业未进入战斗，切换作业",
                    "ERROR",
                )
                return "maa_formation_stall"
            if state == "story":
                log(f"  {el}s: MAA已完成，战后剧情→立即跳过")
                post_maa_story_seen = True
                skip_story()
                continue
            if state == "battle":
                log(f"  {el}s: MAA已完成回调，但画面仍在战斗，继续等待结算")
                continue
            if state == "victory":
                victory_path = shot("victory_badges")
                star_status = _victory_three_star_status(victory_path)
                if star_status["perfect"]:
                    log(
                        f"  {el}s: MAA已完成，结算三枚蓝色徽记齐亮，"
                        "确认完美通关"
                    )
                    return "perfect"
                if post_maa_story_seen and star_status["lit"] == 0:
                    segment_advance_count += 1
                    label = f" {stage_name}" if stage_name else ""
                    log(
                        f"  {el}s:{label} 战后剧情后的0/3页面判定为分段战斗中转；"
                        "继续进入后半段，不落账、不复位、不计失败"
                    )
                    tap(*POS_DISMISS)
                    wait(2)
                    continue
                log(
                    f"  {el}s: MAA已完成，结算徽记={star_status['lit']}/3，"
                    "进入地图节点复核"
                )
                return "cleared"
            if state in ("reward", "chapter_map"):
                log(f"  {el}s: MAA已完成，游戏画面={state}，进入地图节点验证")
                return "cleared"
            if state == "defeat":
                log(f"  {el}s: MAA已完成但游戏显示失败", "ERROR")
                return "failed"
            if time.time() - last_maa_activity_time >= 300:
                log(
                    f"  {el}s: MAA已完成但游戏状态={state}持续5分钟未变化，"
                    "转交地图验证",
                    "WARN",
                )
                return "timeout"
            log(f"  {el}s: MAA已完成，等待游戏进入结算/地图 (state={state})")
            continue
        
        # 剧情
        if state == "story":
            log(f"  {el}s: 剧情→跳过")
            skip_story()
            continue
        
        # 胜利
        if state == "victory":
            victory_path = shot("victory_badges")
            star_status = _victory_three_star_status(victory_path)
            if star_status["perfect"]:
                log(f"  {el}s: ✅ 结算三枚蓝色徽记齐亮，完美通关")
                return "perfect"
            log(f"  {el}s: ✅ 已通关；结算徽记={star_status['lit']}/3，转地图复核")
            return "cleared"
        
        # 失败
        if state == "defeat":
            # 🔴 2026-07-06 修复: 击杀满10/10后的defeat可能是结算页过渡画面误识别
            # (H关结算页有时瞬间显示"任务失败"文字, 但实际通关了)
            # 击杀满后不立即判定failed, 继续等victory/reward
            if kills_full_time:
                log(f"  {el}s: 击杀满后检测到defeat, 可能误识别, 继续等结算")
                continue
            log(f"  {el}s: ❌ 失败")
            return "failed"
        
        # 战斗中
        if state == "battle":
            _LAST_VERIFY_ENTERED_BATTLE = True
            p = shot(f"v{el}")
            if _battle_has_leak(p):
                # 单帧红色不能作为停止依据；两秒后同一窄区仍有标签才止损。
                # 这也防止技能特效或压缩噪点造成瞬时误报。
                wait(2)
                confirm = shot(f"v{el}_leak_confirm")
                if _battle_has_leak(confirm):
                    if not leak_confirmed:
                        log(
                            f"  {el}s: 顶部漏怪扣减标签连续两帧成立；"
                            "保持MAA运行直到真实结算，继续等待胜败结果",
                            "WARN",
                        )
                        leak_confirmed = True
                    continue
                log(f"  {el}s: 单帧疑似漏怪未复现，继续战斗", "WARN")
            t = ocr_text(p)
            km = re.search(r'(\d+)/(\d+)', t)
            if km:
                k = f"{km.group(1)}/{km.group(2)}"
                if k != last_k:
                    log(f"  {el}s: 击杀{k}")
                    last_k = k
                    last_k_change_time = time.time()
                elif (
                    time.time() - last_k_change_time >= 300
                    and _battle_selection_overlay_visible(t)
                ):
                    log(
                        f"  {el}s: 击杀{last_k}已5分钟无变化，且干员/装置选中框持续残留；"
                        "判定MAA控制死锁并切换作业",
                        "ERROR",
                    )
                    return "maa_control_stall"
                if km.group(1) == km.group(2) and kills_full_time is None:
                    kills_full_time = time.time()
                    log(f"  {el}s: 击杀满! 等待结算...")
                if kills_full_time and time.time() - kills_full_time > 90:
                    log(f"  {el}s: 击杀满90s未结算, 跳过剧情")
                    skip_story()
                    kills_full_time = time.time()
        
        # 编队页停滞不是游戏内战败。旧逻辑在180秒后返回 ``failed``，
        # 活动控制器因而会消耗一次真实战斗预算，并把同一关错误写成战败。
        # 现在同时要求“仍在编队页 + 本次MAA日志长期无推进”，再返回独立的
        # 前置控制状态；调用者会停止当前作业、排除它并换下一份，但不会记作
        # 已进入战斗。若日志仍在更新，则继续等待自动编队完成。
        if state == "formation":
            formation_quiet = int(time.time() - last_maa_activity_time)
            if el >= 60 and el % 60 < 5:
                log(
                    f"  {el}s: [编队跟踪] 仍在编队页；"
                    f"MAA日志静默{formation_quiet}s，状态={maa['status']}"
                )
            if el > 180 and formation_quiet >= 150:
                log(
                    f"  {el}s: 编队页停滞，且MAA日志已静默"
                    f"{formation_quiet}s；停止当前作业并切换，不计战败",
                    "ERROR",
                )
                return "maa_formation_stall"

        # 非战斗画面且MAA日志也连续5分钟无推进，才判定为失联；真实战斗
        # 无论已经运行多久都不会在这里被停止或返回失败。
        if state not in ("battle", "formation", "story"):
            quiet = time.time() - last_maa_activity_time
            if quiet >= 300:
                log(f"  {el}s: 非战斗状态={state}且MAA日志静默{int(quiet)}s", "WARN")
                return "timeout"

# ============================================================
# 进度管理
# ============================================================

def _migrate_chapter17_legacy_progress(prog):
    """撤销把17章青蓝险地徽记误记成最终完成的旧记录。"""
    data = deepcopy(prog or {})
    if data.get("migrations", {}).get("chapter17_sandbox_v1"):
        return data, False
    notes = data.get("notes") or {}
    reset = []
    for stage in sorted(CHAPTER17_SANDBOX_STAGES - {"17-2"}, key=_mainline_target_sort_key):
        note = str(notes.get(stage, ""))
        if any(marker in note for marker in ("单一主线环境", "三枚蓝色徽记", "详情徽记")):
            reset.append(stage)
    if not reset:
        return data, False

    for key in ("cleared", "imperfect", "failed", "shelved", "cleared_standard_only"):
        data[key] = [stage for stage in data.get(key, []) if stage not in reset]
    phases = data.setdefault("chapter17_phases", {})
    for stage in reset:
        phases[stage] = {
            "risk": "pending",
            "sandbox": "pending",
            "reason": "legacy_single_environment_record_retracted",
        }
        notes[stage] = "旧版仅确认青蓝节点/险地徽记，未确认沙盘最终白色节点；已重置待办"
    data["notes"] = notes
    current = str(data.get("current") or "").strip()
    earliest = reset[0]
    if not current or _mainline_target_sort_key(earliest) < _mainline_target_sort_key(current):
        data["current"] = earliest
    data.setdefault("migrations", {})["chapter17_sandbox_v1"] = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "reset": reset,
    }
    return data, True


def _migrate_chapter17_generic_completion_bug(prog):
    """纠正通用地图分支把“险地已过”误写成“险地+沙盘完成”的记录。

    真正完成沙盘的记录使用“险地+沙盘闭环，地图最终白色节点确认”；只有
    旧漏口生成的固定文案“险地作战+沙盘推演, 完美通关”会被撤回。已明确
    ``sandbox=cleared`` 的记录永不修改。
    """
    data = deepcopy(prog or {})
    if data.get("migrations", {}).get("chapter17_generic_completion_v2"):
        return data, False

    notes = data.get("notes") or {}
    phases = data.setdefault("chapter17_phases", {})
    repaired = []
    for stage in sorted(CHAPTER17_SANDBOX_STAGES, key=_mainline_target_sort_key):
        note = str(notes.get(stage, ""))
        phase = phases.get(stage) or {}
        if (
            "险地作战+沙盘推演, 完美通关" not in note
            or phase.get("sandbox") == "cleared"
        ):
            continue
        job_match = re.search(r"([^,，]+\.json)\s*$", note, re.I)
        job_name = os.path.basename(job_match.group(1).strip()) if job_match else ""
        for key in ("cleared", "imperfect", "failed", "shelved", "cleared_standard_only"):
            data[key] = [item for item in data.get(key, []) if item != stage]
        repaired_phase = {
            "risk": "cleared",
            "sandbox": "pending",
            "reason": "generic_completion_branch_skipped_sandbox",
        }
        if job_name:
            repaired_phase["risk_job"] = job_name
        phases[stage] = repaired_phase
        notes[stage] = (
            f"险地战斗已完成；沙盘未执行，已撤销整关完成记录"
            + (f"；作业:{job_name}" if job_name else "")
        )
        repaired.append(stage)

    if not repaired:
        return data, False
    data["notes"] = notes
    current = str(data.get("current") or "").strip()
    earliest = repaired[0]
    if not current or _mainline_target_sort_key(earliest) <= _mainline_target_sort_key(current):
        data["current"] = earliest
    data.setdefault("migrations", {})["chapter17_generic_completion_v2"] = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "repaired": repaired,
    }
    return data, True


def load_progress():
    """加载进度文件，并一次性迁移已证伪的17章单环境记录。"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        migrated, changed_v1 = _migrate_chapter17_legacy_progress(raw)
        migrated, changed_v2 = _migrate_chapter17_generic_completion_bug(migrated)
        changed = changed_v1 or changed_v2
        if changed:
            backup_names = []
            if changed_v1:
                backup_names.append("主线通关进度.before_chapter17_sandbox_migration.json")
            if changed_v2:
                backup_names.append("主线通关进度.before_chapter17_generic_completion_v2.json")
            for backup_name in backup_names:
                backup = os.path.join(os.path.dirname(PROGRESS_FILE), backup_name)
                if not os.path.exists(backup):
                    shutil.copy2(PROGRESS_FILE, backup)
            _atomic_write_json(PROGRESS_FILE, migrated)
            log(
                "  [进度迁移] 已撤销第17章未完成沙盘却标记整关完成的记录: "
                f"{migrated.get('migrations', {}).get('chapter17_generic_completion_v2', {}).get('repaired', [])}"
            )
        return migrated
    return {"cleared": [], "failed": [], "current": None, "notes": {}}

def save_progress(prog):
    """保存进度文件"""
    prog["last_update"] = datetime.now().isoformat()
    _atomic_write_json(PROGRESS_FILE, prog)


def _record_chapter17_phase(
    stage, phase, status, job_name="", note="", sandbox_trial_key="",
    sanity_cost=None,
):
    prog = load_progress()
    record = prog.setdefault("chapter17_phases", {}).setdefault(stage, {})
    record[phase] = status
    record["last_update"] = datetime.now().isoformat(timespec="seconds")
    if job_name:
        record[f"{phase}_job"] = os.path.basename(job_name)
        if phase == "sandbox" and status == "failed":
            attempted = record.setdefault("sandbox_attempted_jobs", [])
            basename = os.path.basename(job_name)
            if basename not in attempted:
                attempted.append(basename)
    if phase == "sandbox" and sandbox_trial_key:
        if status == "failed":
            trials = record.setdefault("sandbox_attempted_trials", [])
            if sandbox_trial_key not in trials:
                trials.append(sandbox_trial_key)
        elif status == "cleared":
            record["sandbox_cleared_trial"] = sandbox_trial_key
    if status == "cleared" and isinstance(sanity_cost, int) and sanity_cost > 0:
        record[f"{phase}_sanity_cost"] = sanity_cost
    if note:
        record[f"{phase}_note"] = note
    elif status == "cleared":
        # 成功证据必须覆盖先前技术阻塞备注；否则账本会同时显示
        # sandbox=cleared 与 sandbox_note=blocked，误导后续调度和报告。
        record.pop(f"{phase}_note", None)
    # 阶段状态不是证据本身。只有对应界面/结算闭环成功的写入才生成
    # 可供调度器跳过的直接证据；pending/failed必须同步撤销旧证据。
    if status == "cleared":
        record[f"{phase}_evidence"] = (
            "sandbox_settlement_plus_final_map_node"
            if phase == "sandbox"
            else "risk_detail_or_battle_settlement"
        )
        record[f"{phase}_verified_at"] = datetime.now().isoformat(timespec="seconds")
    else:
        record.pop(f"{phase}_evidence", None)
        record.pop(f"{phase}_verified_at", None)
    save_progress(prog)


def _chapter17_sandbox_failed_jobs(phase_record):
    """读取已真实战败的沙盘作业，兼容旧版只保留最后一次备注的账本。"""
    record = phase_record or {}
    jobs = [
        os.path.basename(str(value))
        for value in (record.get("sandbox_attempted_jobs") or [])
        if str(value).strip()
    ]
    legacy_job = record.get("sandbox_job")
    legacy_note = str(record.get("sandbox_note") or "")
    legacy_outcome = legacy_note.rsplit(":", 1)[-1].strip().lower()
    technical = {
        "sandbox_entry_failed", "maa_control_failed", "navigation_failed",
        "completed_navigation_failed",
    }
    if (
        legacy_job
        and (
            record.get("sandbox") == "failed"
            or (
                legacy_note.startswith("sandbox_only_blocked:")
                and legacy_outcome not in technical
            )
        )
    ):
        jobs.append(os.path.basename(str(legacy_job)))
    return list(dict.fromkeys(jobs))


def _chapter17_sandbox_attempted_trials(phase_record):
    """读取已真实执行的“作业+沙盘组合”；旧账本继续由failed_jobs计次。"""
    trials = list(dict.fromkeys(
        str(value)
        for value in ((phase_record or {}).get("sandbox_attempted_trials") or [])
        if str(value).strip()
    ))
    represented_jobs = {
        value.rsplit("@", 1)[0] for value in trials if "@" in value
    }
    # 迁移旧账本：若失败作业本身写明选项，可无损恢复当时真实组合，
    # 防止升级后把同一作业同一组合再打一遍。
    for job_name in _chapter17_sandbox_failed_jobs(phase_record):
        if job_name in represented_jobs:
            continue
        job_path = _resolve_copilot_job_basename(job_name)
        choices = _chapter17_sandbox_choices_from_job(job_path) if job_path else None
        trial_key = _chapter17_sandbox_trial_key(job_name, choices)
        if trial_key:
            trials.append(trial_key)
            represented_jobs.add(job_name)
    return list(dict.fromkeys(trials))


def _chapter17_sandbox_historical_attempts(phase_record):
    """合并新旧账本，确保同作业不同组合各算一次真实战斗。"""
    trials = _chapter17_sandbox_attempted_trials(phase_record)
    represented_jobs = {
        value.rsplit("@", 1)[0] for value in trials if "@" in value
    }
    legacy_jobs = [
        job for job in _chapter17_sandbox_failed_jobs(phase_record)
        if job not in represented_jobs
    ]
    identities = trials + legacy_jobs
    return [
        {
            "number": index,
            "job": identity.rsplit("@", 1)[0],
            "trial": identity if "@" in identity else "",
            "phase": "sandbox",
            "outcome": "historical_failed",
        }
        for index, identity in enumerate(identities, start=1)
    ]


def _record_training_stage_completed(stage, job_name):
    """只记录TR前置完成证据，不把零理智教学关混入普通主线关列表。"""
    prog = load_progress()
    prog.setdefault("notes", {})[stage] = (
        f"MAA Copilot零理智通关；作业:{job_name}；"
        f"完成时间:{datetime.now().isoformat(timespec='seconds')}"
    )
    save_progress(prog)

def update_progress(stage, status, note=""):
    """更新进度文件 — 以地图六芒星检测为最高标准，实时同步
    
    🔴 2026-07-10 根源修订:
    - cleared: 六芒星验证已通关 → 同时清理failed/imperfect
    - imperfect: 六芒星验证非完美 → 同时加入cleared+imperfect，清理failed
    - failed: 地图节点未填充且尝试未通关 → 加入failed，并清理冲突的cleared/imperfect
    - current: 每次更新后自动指向第一个未通关关卡
    """
    prog = load_progress()
    prog.setdefault("cleared", [])
    prog.setdefault("failed", [])
    prog.setdefault("imperfect", [])
    prog.setdefault("shelved", [])
    
    if status == "cleared":
        if stage not in prog["cleared"]:
            prog["cleared"].append(stage)
        # 在当前章节最难难度下取得完美地图证据后，旧的“仅标准通关”
        # 提示已经失效；不清除会让调度器无限重选同一关。
        standard_only = prog.setdefault("cleared_standard_only", [])
        if stage in standard_only:
            standard_only.remove(stage)
            log(f"  [进度] {stage} 从cleared_standard_only移除(最难难度已确认完美)")
        # 🔴 实时清理: 已通关的关卡不可能同时在failed/imperfect里
        if stage in prog["failed"]:
            prog["failed"].remove(stage)
            log(f"  [进度] {stage} 从failed移除(已通关)")
        if stage in prog["imperfect"]:
            prog["imperfect"].remove(stage)
            log(f"  [进度] {stage} 从imperfect移除(已完美通关)")
        if stage in prog["shelved"]:
            prog["shelved"].remove(stage)
            log(f"  [进度] {stage} 从shelved移除(已有完美通关证据)")
    elif status == "imperfect":
        if stage not in prog["cleared"]:
            prog["cleared"].append(stage)
        if stage not in prog["imperfect"]:
            prog["imperfect"].append(stage)
        if stage in prog["failed"]:
            prog["failed"].remove(stage)
            log(f"  [进度] {stage} 从failed移除(已通关,非完美)")
        if stage in prog["shelved"]:
            prog["shelved"].remove(stage)
            log(f"  [进度] {stage} 从shelved移除(已有通关证据)")
    elif status == "cleared_standard":
        prog.setdefault("cleared_standard_only", [])
        if stage not in prog["cleared_standard_only"]:
            prog["cleared_standard_only"].append(stage)
    elif status == "failed":
        if stage not in prog["failed"]:
            prog["failed"].append(stage)
        # clear_stage只有在战前/战后地图均无通关证据时才会落到failed。
        # 若历史文件仍把同一关写在cleared/imperfect，必须让最新地图真值覆盖旧记录，
        # 否则调度器会同时把它当作已通关和失败，下一次继续选择错误前沿。
        if stage in prog["cleared"]:
            prog["cleared"].remove(stage)
            log(f"  [进度] {stage} 从cleared移除(最新地图节点未填充)")
        if stage in prog["imperfect"]:
            prog["imperfect"].remove(stage)
            log(f"  [进度] {stage} 从imperfect移除(最新地图节点未填充)")
    
    # current是待验证候选，不是“最后写入关卡”。尚未完成的既有待办
    # 不能被更晚章节的局部通关结果覆盖；H关完成后按同章H链推进。
    current = re.sub(r'\([^)]*\)', '', str(prog.get("current") or "")).strip()
    current_pending = bool(
        current
        and current not in set(prog.get("shelved", []))
        and (
            current not in set(prog.get("cleared", []))
            or current in set(prog.get("imperfect", []))
        )
    )
    if current_pending and current != stage:
        # 新发现的失败/非完美关如果实际更早，必须回退到它；否则保留
        # 原有更早待办。这样既不会让17章局部结果覆盖H13-3，也不会
        # 在13-7重新证实未通关时错误保留13-8。
        should_rewind = status in {"failed", "imperfect"} and (
            _mainline_target_sort_key(stage) < _mainline_target_sort_key(current)
        )
        if should_rewind:
            prog["current"] = stage
            log(f"  [进度] 发现更早未闭环关{stage}，从{current}回退")
        else:
            log(f"  [进度] 保留更早未闭环待办{current}，不被{stage}局部结果覆盖")
    elif status == "cleared":
        next_hard = _next_hard_stage(stage, prog)
        prog["current"] = next_hard or _next_unshelved_mainline_target(
            prog, start_chapter=_stage_chapter(stage)
        )
    else:
        prog["current"] = stage
    
    if note:
        prog.setdefault("notes", {})[stage] = note
    save_progress(prog)

def _check_standard_cleared(display_name):
    """检查关卡是否在标准模式下已通关 (通过章节地图蓝色六芒星检测)
    
    用于10-15这类关卡: 磨难模式作业失效, 但标准模式已通关
    返回True表示标准模式已通关, 可以跳过磨难继续推进
    """
    # 简单实现: 检查进度文件的notes字段
    prog = load_progress()
    notes = prog.get("notes", {})
    note = notes.get(display_name, "")
    return "标准模式" in note or "标准通关" in note

# ============================================================
# 单关通关流程 (主线/活动通用)
# ============================================================

def _run_chapter17_sandbox_phase(display_name, job_path, sandbox_choices=None):
    """使用同一份MAA作业完成第17章沙盘，并以地图白色节点验收。"""
    if not _force_to_chapter_map(17):
        return "navigation_failed"
    enter_result = _find_and_enter_stage(
        17,
        display_name,
        force_replay=True,
        chapter17_phase="sandbox",
        chapter17_job_path=job_path,
        chapter17_sandbox_choices=sandbox_choices,
    )
    if isinstance(enter_result, tuple) and enter_result[0] == "already_cleared":
        return True if enter_result[1] else "verification_failed"
    if not (
        isinstance(enter_result, tuple)
        and len(enter_result) >= 2
        and enter_result[0] is True
    ):
        log(f"  ⛔ {display_name}未能进入沙盘编队，不启动MAA", "ERROR")
        return "sandbox_entry_failed"

    started = False
    for control_retry in range(1, 4):
        if run_maa_copilot(job_path):
            started = True
            break
        log(
            f"  [第17章沙盘] MAA控件恢复 {control_retry}/3；不计作战失败",
            "WARN",
        )
        wait(2)
    if not started:
        return "maa_control_failed"

    result = verify_battle(timeout=300, stage_name=display_name)
    if result not in ("perfect", "cleared"):
        log(f"  [第17章沙盘] {display_name}未取得三星结算: {result}", "WARN")
        _stop_maa_task_queue(timeout=30)
        return result
    dismiss_reward()
    wait(3)
    if not _force_to_chapter_map(17):
        return "completed_navigation_failed"
    cleared, perfect = verify_stage_cleared(17, display_name)
    if not (cleared and perfect):
        log(
            f"  ⛔ {display_name}沙盘虽有三星结算，但地图尚未形成最终白色节点；"
            "保留待验证，禁止提前落账",
            "ERROR",
        )
        return "verification_failed"
    return True


def mode_chapter17_sandbox(stage, max_attempts=5):
    """只补第17章沙盘阶段；失败后换不同沙盘作业，绝不回退险地/普通战斗。"""
    global _MAINLINE_RUN_SNAPSHOT, _MAINLINE_STAGE_ATTEMPTS
    display_name = re.sub(r"\([^)]*\)", "", str(stage or "")).strip()
    if _stage_chapter(display_name) != 17:
        log(f"⛔ 沙盘恢复模式只接受第17章关卡，收到: {display_name or '空'}", "ERROR")
        return False

    prog = load_progress()
    phase = (prog.get("chapter17_phases") or {}).get(display_name) or {}
    _MAINLINE_RUN_SNAPSHOT = {
        "started_at": datetime.now().isoformat(),
        "cleared": set(prog.get("cleared", [])),
        "imperfect": set(prog.get("imperfect", [])),
        "failed": set(prog.get("failed", [])),
        "shelved": set(prog.get("shelved", [])),
    }
    failed_jobs = _chapter17_sandbox_failed_jobs(phase)
    historical_attempts = _chapter17_sandbox_historical_attempts(phase)
    _MAINLINE_STAGE_ATTEMPTS = {
        display_name: {
            "status": "running",
            "detail": "第17章沙盘专项换作业验证运行中",
            "attempt_count": len(historical_attempts),
            "attempted_jobs": list(failed_jobs),
            "attempts": historical_attempts,
            "outcome_counts": (
                {"historical_failed": len(historical_attempts)}
                if historical_attempts else {}
            ),
            "preflight_rejections": [],
        }
    }
    if _chapter17_phase_has_direct_evidence(
        prog, display_name, "sandbox"
    ):
        log(f"✅ {display_name}沙盘已有完成记录；本轮不重复执行")
        _MAINLINE_STAGE_ATTEMPTS[display_name].update({
            "status": "already_cleared",
            "detail": "沙盘阶段已有最终白色节点完成记录，本轮未重复战斗",
        })
        _RUN_SUMMARY["mainline"] = {
            "status": "completed",
            "starting_target": display_name,
            "next_target": prog.get("current"),
            "progressed": False,
            "targeted": True,
            "sandbox_only": True,
            "detail": f"{display_name}沙盘已有完成记录，本轮未重复执行",
        }
        _save_mainline_handoff("completed", _RUN_SUMMARY["mainline"]["detail"], _RUN_SUMMARY["mainline"])
        return True
    if not _chapter17_phase_has_direct_evidence(
        prog, display_name, "risk"
    ):
        log(
            f"⛔ {display_name}险地阶段没有已完成证据，沙盘专用模式拒绝进入任何战斗",
            "ERROR",
        )
        return False

    _RUN_SUMMARY["mainline"] = {
        "status": "running",
        "starting_target": display_name,
        "next_target": display_name,
        "progressed": False,
        "targeted": True,
        "sandbox_only": True,
    }
    log(
        f"[沙盘硬门禁] {display_name}: 险地=cleared；"
        f"只允许进入沙盘，不存在普通/险地战斗回退；"
        f"本地及在线筛选带两级假设说明的不同作业，最多{max_attempts}份真实战斗"
    )
    result = clear_stage(
        17,
        display_name,
        _internal_stage_name(17, display_name),
        max_attempts=max_attempts,
        force_replay=True,
        initial_used_ops=failed_jobs,
    )
    if result is True:
        _set_mainline_run_status("completed", f"{display_name}沙盘及最终白色节点已确认")
        return True

    _set_mainline_run_status("blocked", f"{display_name}沙盘未闭环: {result}")
    return False


def clear_stage(
    ch,
    display_name,
    internal_name,
    max_attempts=5,
    force_replay=False,
    force_enter=False,
    initial_used_ops=None,
    training_stage=False,
):
    """通关一个关卡 (含失败换作业重试, 最多max_attempts次)
    
    🔴 2026-06-28 用户确认核心流程:
      每次attempt都必须: 退出到章节地图 → 找关卡 → 进编队 → 启动MAA
      不能在原编队页面直接重启MAA (会导致taskchain_error)
    
    重试策略:
      attempt 0: 最高赞作业 (单核)
      attempt 1: 次高赞作业  
      attempt 2+: 多核作业 (按干员数排序)
      全部失败 → 停止并向用户报错
    """
    log(f"\n{'='*50}")
    log(f"攻关: {display_name} (最多{max_attempts}次尝试)")
    log(f"{'='*50}")

    used_ops = [os.path.basename(p) for p in (initial_used_ops or []) if str(p).strip()]
    stage_run = _MAINLINE_STAGE_ATTEMPTS.setdefault(display_name, {
        "status": "running",
        "detail": "",
        "attempt_count": 0,
        "attempted_jobs": [],
        "attempts": [],
        "outcome_counts": {},
        "preflight_rejections": [],
    })
    stage_run.setdefault("preflight_rejections", [])
    for previous_job in used_ops:
        if previous_job not in stage_run["attempted_jobs"]:
            stage_run["attempted_jobs"].append(previous_job)
    if used_ops:
        log(f"  [续跑] 已执行过的不同作业不再重复: {used_ops}")
    first_clear_marked = False  # 🔴 跟踪是否首次通关(非完美)
    chapter17_sandbox_stage = ch == 17 and _chapter17_stage_requires_sandbox(display_name)
    chapter17_progress = load_progress() if chapter17_sandbox_stage else {}
    chapter17_phase_record = (
        (chapter17_progress.get("chapter17_phases") or {}).get(display_name) or {}
        if chapter17_sandbox_stage else {}
    )
    sandbox_trial_ids = set(
        _chapter17_sandbox_attempted_trials(chapter17_phase_record)
        if chapter17_sandbox_stage else []
    )
    chapter17_phase_incomplete = chapter17_sandbox_stage and not (
        _chapter17_phase_has_direct_evidence(
            chapter17_progress, display_name, "risk"
        )
        and _chapter17_phase_has_direct_evidence(
            chapter17_progress, display_name, "sandbox"
        )
    )
    combat_attempts = len(stage_run.get("attempts") or [])
    candidate_index = len(used_ops)
    # 五次预算只约束“真正进入战斗但未完美”的次数。缺员、模组/技能不满足、
    # 编队前TaskChainError等只是作业前置不兼容，允许继续筛选其它候选。
    candidate_limit = candidate_index + max_attempts + 20
    jobs_exhausted = False
    while combat_attempts < max_attempts and candidate_index < candidate_limit:
        attempt = candidate_index
        chapter17_risk_already = False
        log(
            f"\n--- 作业候选 #{attempt+1} | "
            f"真实战斗 {combat_attempts}/{max_attempts} ---"
        )
        
        # 🔴 2026-07-08 自检: 每10分钟检查脚本是否卡住
        if check_stall(600):
            log(f"  ⚠️ 脚本卡住，尝试恢复后重试", "WARN")
            goto_main_menu()
            wait(3)
        
        # 1. 强制退出到章节地图 (无论当前在哪)
        # 🔴 2026-07-01 修复: _force_to_chapter_map失败时continue不break, 让后续尝试有机会
        if not _force_to_chapter_map(ch):
            # 导航没有成功时尚未选择作业、更没有启动战斗。它属于流程故障，
            # 绝不能伪装成一次“换作业重试”并消耗五份作业预算。
            log("  ❌ 无法回到章节地图；未启动MAA，不计入作业尝试次数", "ERROR")
            return "navigation_failed"

        # 强制补打的首轮先记录旧六芒星分类，作为同一关战前/战后的校准样本。
        if force_replay and attempt == 0 and not training_stage:
            baseline_cleared, baseline_perfect = verify_stage_cleared(ch, display_name)
            log(
                f"  [补打基线] {display_name}: cleared={baseline_cleared}, "
                f"perfect={baseline_perfect}（战后将用同一算法复测）"
            )
            if baseline_cleared and baseline_perfect and not chapter17_phase_incomplete:
                update_progress(display_name, "cleared", "最新节点ROI验证: 已完美通关")
                log(f"  ✅ {display_name} 最新图形验证已完美，无需重复补打")
                return True
            if baseline_cleared and baseline_perfect and chapter17_phase_incomplete:
                log(
                    f"  [第17章阶段闭环] {display_name}地图节点虽为白色，"
                    "但险地/沙盘账本未闭环；禁止通用预检短路，继续打开详情"
                )
            if baseline_cleared and not baseline_perfect:
                # 深色立方体已经证明关卡通关，只是没有完美。后续五份作业
                # 即使全部漏怪/失败，也必须归类为“未完美搁置”，不能谎报
                # 成“从未通关的五次全失败”。
                first_clear_marked = True
                update_progress(
                    display_name,
                    "imperfect",
                    "补打前节点ROI验证: 已通关但未完美，继续尝试不同作业",
                )
        
        # 2. 找关卡+选难度+进编队 (每次都重新走完整流程)
        # 🔴 2026-07-02 修复: _find_and_enter_stage可能修改display_name(如11-2→11-1)
        # 需要返回实际进入的关卡名, 同步更新internal_name, 否则作业套错关卡
        original_display = display_name
        # Once this clear_stage call has produced a non-perfect clear, remaining
        # attempts must actually replay the node instead of the precheck ending
        # the loop on the same dark cube.
        enter_result = _find_and_enter_stage(
            ch,
            display_name,
            # 进度文件明确记录为未通关时，节点像素预检查只是弱证据。
            # force_enter 允许真正点开详情页取证，但不把战前空标志记成非完美首通。
            force_replay=(force_replay or force_enter or first_clear_marked),
        )
        # 使用临期药剂后游戏会回到章节地图；必须重新定位同一关详情页，
        # 不能沿用恢复弹窗前的“开始行动”坐标。此时尚未启动MAA，不计作业次数。
        potion_retries = 0
        while enter_result == "retry_stage" and potion_retries < 3:
            potion_retries += 1
            log(f"  [临期药剂] 返回地图后重新定位{display_name} (第{potion_retries}次)")
            if not _force_to_chapter_map(ch):
                return "navigation_failed"
            enter_result = _find_and_enter_stage(ch, display_name, force_replay=True)
        if enter_result == "retry_stage":
            log("  ❌ 连续使用药剂后仍无法进入编队，暂停且不计作业次数", "ERROR")
            return "navigation_failed"
        if enter_result == "stamina":
            log(f"  ⚠️ 理智不足, 停止推进 (不换作业)", "ERROR")
            return "stamina"  # 特殊返回值, mode_mainline会处理
        if enter_result == "story_cleared":
            # 🔴 2026-07-02: 剧情关(三角叶轮)已自动通关, 不需要MAA战斗
            log(f"  ✅ {display_name} 剧情关已通关(无战斗)")
            return True
        if (
            isinstance(enter_result, tuple)
            and len(enter_result) >= 2
            and enter_result[0] == "tr_required"
        ):
            stage_run.update({
                "status": "waiting_prerequisite",
                "detail": f"等待零理智教学关{enter_result[1]}",
            })
            return enter_result
        if (
            chapter17_sandbox_stage
            and isinstance(enter_result, tuple)
            and enter_result[0] == "chapter17_risk_cleared"
        ):
            chapter17_risk_already = True
            _record_chapter17_phase(
                display_name, "risk", "cleared", note="险地详情三枚徽记已确认"
            )
            log(f"  [第17章阶段] {display_name}险地已完成，本轮只执行沙盘")
        # 🔴 2026-07-10: 六芒星预检查发现已通关, 直接跳过
        if isinstance(enter_result, tuple) and enter_result[0] == "already_cleared":
            is_perf = enter_result[1]
            if is_perf:
                log(f"  ✅ {display_name} 已完美通关(六芒星验证), 跳过")
                update_progress(display_name, "cleared", "地图六芒星验证: 已完美通关")
                stage_run["status"] = "already_cleared"
                stage_run["detail"] = "战前直接证据已确认完美，未启动MAA"
                return True
            else:
                log(f"  ⚠️ {display_name} 已非完美通关(六芒星验证), 标记imperfect")
                update_progress(display_name, "imperfect", "地图六芒星验证: 非完美通关")
                return "imperfect"
        # 🔴 2026-07-02 修复: 如果_find_and_enter_stage返回了新的关卡名(如11-1), 同步更新
        if isinstance(enter_result, str) and enter_result not in ("stamina", "story_cleared", "True", "False", ""):
            if enter_result != display_name:
                log(f"  ℹ️ 关卡名变更: {display_name} → {enter_result}")
                display_name = enter_result
                # 同步更新internal_name (11-2→tough_11-01, 11-1→tough_11-00)
                internal_name = _internal_stage_name(ch, display_name)
                log(f"  ℹ️ internal_name同步更新: {internal_name}")
        if not enter_result:
            # 地图没有目标节点/未能进入编队时，尚不存在“当前作业”。立即把
            # 原因交还调度层，由它检查前置关或报告导航失败，禁止空耗五次。
            log("  ❌ 地图未定位目标或未能进入编队；未启动MAA，不计入作业尝试次数", "ERROR")
            return "stage_not_found"
        
        # 3. 获取作业 (按attempt取不同作业)
        jp = None
        sandbox_choices = None
        sandbox_choices_fallback = False
        sandbox_trial_key = ""
        if chapter17_risk_already and not used_ops:
            phase_record = (
                load_progress().get("chapter17_phases", {}).get(display_name, {})
            )
            remembered_job = phase_record.get("risk_job")
            remembered_path = _resolve_copilot_job_basename(remembered_job)
            if (
                remembered_path
                and _chapter17_sandbox_choices_from_job(remembered_path)
            ):
                jp = remembered_path
                log(
                    f"  [第17章沙盘续跑] 复用已完成险地的同一作业: "
                    f"{os.path.basename(jp)}"
                )
        if not jp:
            jp = get_copilot_json(
                internal_name,
                display_name,
                attempt=attempt,
                excluded_paths=used_ops,
                # 险地尚未通关时，作业只负责险地战斗；沙盘选项可在险地
                # 成功后由受控兜底单独生成，不能提前淘汰成熟险地作业。
                require_sandbox_choices=chapter17_risk_already,
            )
        # 专用沙盘作业稀缺时，复用本关已通关险地的作业，并随机选择一组
        # 尚未真实执行过的LV.1/LV.2组合。组合而非文件名是此处的去重单位。
        if not jp and chapter17_risk_already:
            phase_record = (
                load_progress().get("chapter17_phases", {}).get(display_name, {})
            )
            remembered_path = _resolve_copilot_job_basename(
                phase_record.get("risk_job")
            )
            if remembered_path:
                sandbox_choices = _chapter17_random_untried_sandbox_choices(
                    remembered_path, sandbox_trial_ids,
                )
                if sandbox_choices:
                    jp = remembered_path
                    sandbox_choices_fallback = True
                    sandbox_trial_key = _chapter17_sandbox_trial_key(
                        jp, sandbox_choices,
                    )
                    log(
                        f"  [第17章沙盘兜底] 专用作业不足，复用险地作业 "
                        f"{os.path.basename(jp)}，本次={sandbox_trial_key.rsplit('@', 1)[-1]}"
                    )
        if not jp:
            log(f"  ❌ 无更多作业可尝试 (attempt={attempt})")
            jobs_exhausted = True
            break
        job_name = os.path.basename(jp)
        if chapter17_risk_already and not sandbox_choices:
            sandbox_choices = _chapter17_sandbox_choices_from_job(jp)
            sandbox_trial_key = _chapter17_sandbox_trial_key(jp, sandbox_choices)
        if sandbox_trial_key and sandbox_trial_key in sandbox_trial_ids:
            log(f"  [第17章沙盘] 组合已真实执行过，跳过: {sandbox_trial_key}")
            candidate_index += 1
            continue
        if job_name in used_ops and not sandbox_trial_key:
            log(f"  ❌ 作业选择器返回了已执行作业 {job_name}，拒绝重复计次", "ERROR")
            candidate_index += 1
            continue
        if job_name not in used_ops:
            used_ops.append(job_name)
        candidate_index += 1

        if chapter17_risk_already:
            sandbox_result = _run_chapter17_sandbox_phase(
                display_name,
                jp,
                sandbox_choices=(sandbox_choices if sandbox_choices_fallback else None),
            )
            attempt_record = {
                "number": combat_attempts + 1,
                "job": job_name,
                "trial": sandbox_trial_key,
                "phase": "sandbox",
                "outcome": "perfect" if sandbox_result is True else str(sandbox_result),
            }
            if job_name not in stage_run["attempted_jobs"]:
                stage_run["attempted_jobs"].append(job_name)
            # 入口/控件问题不属于真实战斗失败；其余结果说明沙盘已实际启动。
            if sandbox_result not in (
                "sandbox_entry_failed", "maa_control_failed", "navigation_failed"
            ):
                stage_run["attempts"].append(attempt_record)
                combat_attempts += 1
                stage_run["attempt_count"] = combat_attempts
                if sandbox_trial_key:
                    sandbox_trial_ids.add(sandbox_trial_key)
            if sandbox_result is True:
                _record_chapter17_phase(
                    display_name, "sandbox", "cleared", jp,
                    sandbox_trial_key=sandbox_trial_key,
                )
                update_progress(
                    display_name,
                    "cleared",
                    f"险地+沙盘闭环，地图最终白色节点确认，{job_name}",
                )
                stage_run.update({"status": "completed", "detail": "险地+沙盘闭环"})
                log(f"  ✅ {display_name}险地+沙盘均完成，最终白色节点已确认")
                return True
            technical_sandbox_results = {
                "sandbox_entry_failed", "maa_control_failed", "navigation_failed",
                "completed_navigation_failed",
            }
            _record_chapter17_phase(
                display_name,
                "sandbox",
                "pending" if sandbox_result in technical_sandbox_results else "failed",
                jp,
                str(sandbox_result),
                sandbox_trial_key=(
                    sandbox_trial_key
                    if sandbox_result not in technical_sandbox_results else ""
                ),
            )
            log(f"  [第17章沙盘] {display_name}本作业未闭环: {sandbox_result}", "WARN")
            if sandbox_result in (
                "maa_control_failed", "navigation_failed", "completed_navigation_failed"
            ):
                return sandbox_result
            continue
        
        # 4. MAA执行。GUI控件故障不是作业/战斗失败，不能消耗关卡尝试次数。
        maa_started = False
        for control_retry in range(1, 4):
            if run_maa_copilot(jp):
                maa_started = True
                break
            log(
                f"  ⚠️ MAA桌面控件操作失败，原作业原编队恢复 {control_retry}/3；"
                "不计入关卡尝试次数",
                "WARN",
            )
            wait(2)
        if not maa_started:
            log(
                "  ❌ MAA桌面控件连续恢复失败；未启动战斗，停止本关并保留待办",
                "ERROR",
            )
            return "maa_control_failed"

        attempt_record = {
            "number": combat_attempts + 1,
            "job": job_name,
            "outcome": "running",
        }
        if job_name not in stage_run["attempted_jobs"]:
            stage_run["attempted_jobs"].append(job_name)
        
        # 🔴 2026-07-10: 战斗前更新checkpoint, 避免stall检测器误触发
        checkpoint()
        
        # 5. 验证战斗结果。一般状态仍须回地图复核；但结算页三枚独立蓝色
        # 徽记是直接、权威的本局完美证据，优先于17章尚未刷新的灰白地图节点。
        r = verify_battle(timeout=300, stage_name=display_name)

        entered_battle = bool(_LAST_VERIFY_ENTERED_BATTLE)
        noncombat_rejection = (
            not entered_battle
            and (
                (isinstance(r, str) and r.startswith("maa_"))
                or r in ("failed", "timeout")
            )
        )
        if noncombat_rejection:
            detail = r[4:] if isinstance(r, str) and r.startswith("maa_") else str(r)
            stage_run["preflight_rejections"].append({
                "job": job_name,
                "reason": detail,
                "counts_as_battle": False,
            })
            log(
                f"  [作业前置不满足] {job_name}: {detail}；"
                f"未进入战斗，不计入{max_attempts}次失败预算",
                "WARN",
            )
            _stop_maa_task_queue(timeout=30)
            if not _force_to_chapter_map(ch):
                log("  [作业前置恢复] 未能回到章节地图，下个候选继续恢复", "WARN")
            checkpoint()
            continue

        # 到这里才说明本候选真正进入过战斗，或已经取得通关结算证据。
        # 它才属于用户定义的关卡尝试。
        stage_run["attempts"].append(attempt_record)
        combat_attempts += 1
        stage_run["attempt_count"] = combat_attempts
        
        # MAA错误 (干员缺失/任务链出错) → 换作业
        if isinstance(r, str) and r.startswith("maa_"):
            err_type = r[4:]
            attempt_record.update({"outcome": "maa_error", "detail": err_type})
            stage_run["outcome_counts"]["maa_error"] = (
                stage_run["outcome_counts"].get("maa_error", 0) + 1
            )
            log(f"  ❌ MAA错误: {err_type}, 换作业重试")
            _stop_maa_task_queue(timeout=30)
            if not _force_to_chapter_map(ch):
                log("  [MAA错误恢复] 未能回到章节地图，下次尝试继续恢复", "WARN")
            checkpoint()
            continue

        if r == "leaked":
            attempt_record.update({"outcome": "leaked", "detail": "检测到漏怪并立即止损"})
            stage_run["outcome_counts"]["leaked"] = (
                stage_run["outcome_counts"].get("leaked", 0) + 1
            )
            log("  [完美止损] 停止MAA当前作业并放弃本局，直接切换下一份作业", "WARN")
            _stop_maa_task_queue(timeout=30)
            if not _force_to_chapter_map(ch):
                log("  [完美止损] 放弃后未能回到章节地图，下次尝试继续恢复", "WARN")
            checkpoint()
            continue

        # TR 教学关不消耗理智，也没有普通主线六芒星可供可靠复核。
        # 只在 Copilot 已完成且游戏进入胜利/奖励/地图结算状态时记为完成，
        # 随后由原目标关重新出现这一直接解锁结果继续验收。
        if training_stage:
            if r in ("perfect", "cleared"):
                attempt_record.update({
                    "outcome": "completed",
                    "detail": "Copilot完成且游戏进入教学关结算状态",
                })
                stage_run.update({"status": "completed", "detail": "零理智教学关完成"})
                stage_run["outcome_counts"]["completed"] = (
                    stage_run["outcome_counts"].get("completed", 0) + 1
                )
                dismiss_reward()
                wait(3)
                _record_training_stage_completed(display_name, job_name)
                if not _force_to_chapter_map(ch):
                    log(
                        f"  ⚠️ {display_name}已取得结算证据，但返回章节地图失败；"
                        "保留完成记录并暂停后续理智",
                        "WARN",
                    )
                    return "completed_navigation_failed"
                log(f"  ✅ {display_name} 教学关已完成（零理智），恢复原主线目标")
                return True

            outcome = "failed" if r == "failed" else "verification_failed"
            attempt_record.update({"outcome": outcome, "detail": str(r)})
            stage_run["outcome_counts"][outcome] = (
                stage_run["outcome_counts"].get(outcome, 0) + 1
            )
            log(f"  ❌ {display_name} 教学关未取得完成结算: {r}", "ERROR")
            _stop_maa_task_queue(timeout=30)
            if not _force_to_chapter_map(ch):
                log("  [教学关恢复] 未能回到章节地图，下次尝试继续恢复", "WARN")
            checkpoint()
            continue

        # 第17章沙盘关的本局三星只关闭“险地”阶段，绝不能直接写入整关完成。
        # 随后必须用同一份作业按其说明选择沙盘两级假设，并以地图白色节点验收。
        if chapter17_sandbox_stage and r in ("perfect", "cleared"):
            attempt_record.update({
                "outcome": "risk_perfect",
                "detail": "险地已通关且无漏怪证据；等待同作业沙盘闭环",
            })
            _record_chapter17_phase(
                display_name, "risk", "cleared", jp,
                sanity_cost=_mainline_sanity_cost(ch, display_name),
            )
            dismiss_reward()
            wait(3)
            sanity_cost = _mainline_sanity_cost(ch, display_name)
            log(f"[STAMINA] 险地作战: {display_name}, 消耗: {sanity_cost}, 尝试: {combat_attempts}")
            checkpoint()
            sandbox_choices = _chapter17_sandbox_choices_from_job(jp)
            if not sandbox_choices:
                sandbox_choices = _chapter17_random_untried_sandbox_choices(
                    jp, sandbox_trial_ids,
                )
                if sandbox_choices:
                    sandbox_choices_fallback = True
                    readable = tuple(
                        "左" if value == "left" else "右"
                        for value in sandbox_choices
                    )
                    log(
                        f"  [第17章沙盘兜底] 险地已通关但作业未标沙盘；"
                        f"随机未试组合 LV.1={readable[0]}, LV.2={readable[1]}"
                    )
            sandbox_trial_key = _chapter17_sandbox_trial_key(jp, sandbox_choices)
            if not sandbox_choices:
                log(
                    f"  ⛔ {display_name}该险地作业的四种沙盘组合均已执行；"
                    "保留险地完成记录并停止重复扣理智",
                    "ERROR",
                )
                return "jobs_unavailable"
            sandbox_result = _run_chapter17_sandbox_phase(
                display_name,
                jp,
                sandbox_choices=(sandbox_choices if sandbox_choices_fallback else None),
            )
            if sandbox_result is True:
                _record_chapter17_phase(
                    display_name, "sandbox", "cleared", jp,
                    sandbox_trial_key=sandbox_trial_key,
                )
                update_progress(
                    display_name,
                    "cleared",
                    f"险地+沙盘闭环，地图最终白色节点确认，{job_name}",
                )
                attempt_record.update({
                    "outcome": "perfect",
                    "detail": "险地三星+沙盘三星+地图最终白色节点",
                })
                stage_run.update({"status": "completed", "detail": "险地+沙盘闭环"})
                stage_run["outcome_counts"]["perfect"] = (
                    stage_run["outcome_counts"].get("perfect", 0) + 1
                )
                log(f"  ✅ {display_name}险地+沙盘均完成，最终白色节点已确认")
                return True
            _record_chapter17_phase(
                display_name, "sandbox", "failed", jp, str(sandbox_result),
                sandbox_trial_key=(
                    sandbox_trial_key
                    if sandbox_result not in (
                        "sandbox_entry_failed", "maa_control_failed", "navigation_failed",
                    ) else ""
                ),
            )
            if sandbox_trial_key and sandbox_result not in (
                "sandbox_entry_failed", "maa_control_failed", "navigation_failed",
            ):
                sandbox_trial_ids.add(sandbox_trial_key)
            stage_run["outcome_counts"]["sandbox_failed"] = (
                stage_run["outcome_counts"].get("sandbox_failed", 0) + 1
            )
            attempt_record.update({
                "outcome": "sandbox_failed",
                "detail": str(sandbox_result),
            })
            if sandbox_result in ("maa_control_failed", "navigation_failed"):
                return sandbox_result
            continue

        if r == "completed_sync_blocked":
            sanity_cost = _mainline_sanity_cost(ch, display_name)
            log(
                f"[STAMINA] 战斗: {display_name}, 消耗: {sanity_cost}, "
                "结算同步未闭环；禁止重复战斗"
            )
            attempt_record.update({
                "outcome": "verification_blocked",
                "detail": "战斗记录同步连续失败；未重复扣理智",
            })
            stage_run.update({
                "status": "verification_blocked",
                "detail": "战斗已发生但同步弹窗未能关闭",
            })
            checkpoint()
            return "verification_blocked"

        # 三枚独立蓝色徽记是普通关卡本局完美通关的直接、权威证据。必须在任何
        # 结算关闭/地图恢复动作之前立即落账；导航复位失败只能影响下一关
        # 的入口，不能反过来抹掉已经发生的通关并再次扣理智。
        direct_perfect_recorded = r == "perfect"
        if direct_perfect_recorded:
            diff = DIFFICULTY.get(ch, {}).get("hardest", "标准")
            update_progress(
                display_name,
                "cleared",
                f"{diff}, 结算三枚蓝色徽记确认完美, {os.path.basename(jp)}",
            )
            attempt_record.update({
                "outcome": "perfect",
                "detail": "结算页三枚独立蓝色徽记确认完美",
            })
            stage_run.update({"status": "completed", "detail": "完美通关"})
            stage_run["outcome_counts"]["perfect"] = (
                stage_run["outcome_counts"].get("perfect", 0) + 1
            )
            log(
                f"  ✅ {display_name} 完美通关证据已先行落账 "
                f"(结算三徽记, 第{combat_attempts}次真实战斗)"
            )

        log(f"  verify_battle返回={r}, 关闭结算并回章节地图复位...")
        dismiss_reward()
        wait(3)
        
        # 🔴 2026-07-10 修复: STAMINA日志只在战斗实际发生时记录
        # verify_battle返回perfect/cleared/timeout = 战斗发生了(理智确实消耗)
        # verify_battle返回maa_error/failed = MAA没跑成功(理智没消耗)
        if r in ("perfect", "cleared", "timeout"):
            sanity_cost = _mainline_sanity_cost(ch, display_name)
            log(f"[STAMINA] 战斗: {display_name}, 消耗: {sanity_cost}, 尝试: {combat_attempts}")
        
        # 🔴 2026-07-10: 战斗后更新checkpoint
        checkpoint()
        
        # 必须回到章节地图才能验证六芒星
        if not _force_to_chapter_map(ch):
            if direct_perfect_recorded:
                log(
                    f"  ⚠️ {display_name}已由结算三徽记确认完美，但下一关导航复位失败；"
                    "保留通关结果并交由调度层重新导航，禁止重复战斗",
                    "WARN",
                )
                return "completed_navigation_failed"
            attempt_record.update({"outcome": "verification_failed", "detail": "战后无法返回地图复核"})
            stage_run["outcome_counts"]["verification_failed"] = (
                stage_run["outcome_counts"].get("verification_failed", 0) + 1
            )
            log(f"  ⚠️ 无法回到章节地图验证", "ERROR")
            continue
        
        # 结算三星已直接确认时，地图只负责复位而不再推翻结算证据。第17章
        # 首次完美后节点曾仍呈灰白，若继续把地图样式当唯一真理会重复扣理智。
        if direct_perfect_recorded:
            log(
                f"  ✅ {display_name} 完美通关! "
                f"(结算三徽记验证, 第{combat_attempts}次真实战斗)"
            )
            return True

        # 未取得结算三星直接证据时，继续使用地图节点图形复核。
        cleared, is_perfect = verify_stage_cleared(ch, display_name)
        if not cleared:
            attempt_record.update({"outcome": "failed", "detail": "战后节点未填充"})
            stage_run["outcome_counts"]["failed"] = (
                stage_run["outcome_counts"].get("failed", 0) + 1
            )
            # 六芒星没填充 → 确实没通关, 换作业
            log(f"  ❌ 六芒星未填充 → 战斗确实失败 (verify_battle={r})")
            continue
        
        if not is_perfect:
            attempt_record.update({"outcome": "imperfect", "detail": "战后节点为非完美"})
            stage_run["outcome_counts"]["imperfect"] = (
                stage_run["outcome_counts"].get("imperfect", 0) + 1
            )
            # 非完美通关: 六芒星有立方体阴影
            log(f"  ⚠️ 非完美通关 (立方体阴影六芒星), 换作业追求完美通关", "WARN")
            first_clear_marked = True
            continue
        
        # 完美通关!
        diff = DIFFICULTY.get(ch, {}).get("hardest", "标准")
        update_progress(display_name, "cleared", f"{diff}, 完美通关, {os.path.basename(jp)}")
        marker_label = "白色最终节点验证" if chapter17_sandbox_stage else "六芒星验证完美"
        attempt_record.update({"outcome": "perfect", "detail": marker_label})
        stage_run.update({"status": "completed", "detail": "完美通关"})
        stage_run["outcome_counts"]["perfect"] = (
            stage_run["outcome_counts"].get("perfect", 0) + 1
        )
        log(f"  ✅ {display_name} 完美通关! ({marker_label}, 第{combat_attempts}次真实战斗)")
        return True

    # 全部失败 (所有路径已在上面用六芒星判定, 这里只在所有attempt都continue后才到达)
    log(f"\n{'='*50}")
    if combat_attempts < max_attempts:
        detail = (
            f"仅发生{combat_attempts}/{max_attempts}次真实战斗；"
            f"另有{len(stage_run['preflight_rejections'])}份作业前置不满足"
        )
        if jobs_exhausted:
            detail += "，当前没有更多兼容作业"
        log(f"⚠️ {display_name}未用完战斗预算：{detail}", "WARN")
        stage_run.update({"status": "jobs_unavailable", "detail": detail})
        return "jobs_unavailable"
    if chapter17_sandbox_stage:
        detail = f"沙盘阶段已执行{combat_attempts}份不同作业仍未形成最终白色节点"
        log(f"❌ {display_name}{detail}；保留已完成险地，不回退普通/险地战斗", "ERROR")
        stage_run.update({"status": "failed", "detail": detail})
        return "failed"
    if first_clear_marked:
        # 至少首次通关了, 但没完美: 标记imperfect, 继续推进(不阻塞)
        log(f"⚠️ {display_name} {combat_attempts}次真实战斗未完美通关 (首次通关已记录)", "WARN")
        log(f"   已尝试作业: {used_ops}")
        log(f"   标记为imperfect, 继续推进后续关卡")
        log(f"{'='*50}")
        update_progress(display_name, "imperfect", f"非完美, 作业:{used_ops}")
        stage_run.update({
            "status": "imperfect",
            "detail": f"{stage_run['attempt_count']}份不同作业后仍未完美",
        })
        return "imperfect"  # 🔴 特殊返回值: 首次通关但非完美, mode_mainline继续推进
    else:
        log(f"❌ {display_name} {combat_attempts}次真实战斗全失败!", "ERROR")
        log(f"   已尝试作业: {used_ops}")
        log(f"   可能原因: 作业失效/练度不足/干员缺失/关卡机制特殊")
        log(f"{'='*50}")
        update_progress(display_name, "failed", f"{combat_attempts}次真实战斗全失败, 作业:{used_ops}")
        stage_run.update({
            "status": "failed",
            "detail": f"{stage_run['attempt_count']}份不同作业后仍未通关",
        })
        return False


def _force_to_chapter_map(ch):
    """强制退出到章节地图 (无论当前在哪个界面)

    🔴 关键: MAA任务链出错后, 游戏可能还停留在编队页面,
    但直接在原编队页面重启MAA会立即taskchain_error,
    必须退出编队→回到章节地图→重新点击关卡进编队

    🔴 2026-06-28修复: 增加弹窗检测(exit_dialog/announcement),
    unknown状态时主动检查并处理弹窗, 循环次数8→15
    """
    for i in range(15):  # 🔴 从8增加到15, 游戏启动+加载需要更长时间
        state = get_state()
        log(f"  [恢复] 当前状态={state} (第{i+1}次)")
        
        if state == "chapter_map":
            if _verify_target_chapter_map(ch, "chapter_identity"):
                handle_popups()
                log(f"  [恢复] 已确认位于第{ch}章地图")
                return True
            log(f"  [恢复] 当前章节不符或无法确认，重新导航到第{ch}章", "WARN")
            if not goto_main_menu():
                wait(2)
                continue
            return goto_chapter(ch)
        
        if state == "main_menu":
            return goto_chapter(ch)

        if state == "sanity_restore":
            log("  [恢复] 理智恢复窗口仍覆盖地图，关闭窗口后再操作")
            tap(1170, 865)  # 左侧X；绝不触碰右侧源石页签/确认区域
            wait(2)
            continue

        if state == "monthly_sign_in":
            _dismiss_reward_overlay_for_main_menu()
            continue

        if state in ("victory", "reward", "defeat"):
            # 🔴 2026-07-01 修复: 连续3次reward/victory/defeat说明tap(POS_DISMISS)无效(可能是误判)
            # 第3次起改用back()兜底, 避免死循环
            if i >= 2:
                log(f"  [恢复] reward/victory/defeat已{i+1}次, 改用back()兜底")
                back()
                wait(2)
            else:
                tap(*POS_DISMISS)
                wait(2)
            continue

        if state == "story":
            skip_story()
            wait(3)
            continue
        
        if state == "formation":
            # 🔴 关键: 退出编队 (可能需要确认)
            back()
            wait(2)
            # 检查是否有退出确认框
            t = ocr_text(shot("exit_confirm"))
            if "退出" in t or "确认" in t or "离开" in t:
                # 点"确认/离开"按钮 (不是取消)
                items = ocr(shot("exit_confirm2"))
                for keyword in ["确认", "离开", "确定"]:
                    pos = find_text(items, keyword)
                    if pos:
                        tap(*pos)
                        log(f"  [恢复] 点击'{keyword}'确认退出")
                        break
                else:
                    # 找不到按钮, 再back一次
                    back()
                wait(2)
            continue
        
        if state == "stage_detail":
            # 关卡详情页, back到章节地图
            back()
            wait(2)
            continue

        # 🔴 2026-07-12: 战斗中/战斗失败后卡在battle状态
        # 需要暂停→放弃→确认退出
        if state == "battle":
            log(f"  [恢复] 战斗中, 尝试暂停并放弃")
            # 点暂停按钮 (右上角)
            tap(1800, 100)
            wait(2)
            # 暂停本身只显示继续按钮；真正的“放弃行动”入口在左上角齿轮。
            # 若当前有干员选择层，暂停仍能打开，但不会直接出现可OCR的放弃文字。
            tap(115, 80)
            wait(2)
            # 找“放弃行动”按钮
            p_abandon = shot("abandon")
            items_ab = ocr(p_abandon)
            # 页面上方说明也包含“放弃行动”；必须优先点击底部精确按钮。
            exact_ab = [
                (item[1], item[2])
                for item in items_ab
                if isinstance(item, tuple)
                and len(item) >= 3
                and str(item[0]).strip() == "放弃行动"
            ]
            pos_ab = max(exact_ab, key=lambda pos: pos[1]) if exact_ab else None
            if not pos_ab:
                fallback_ab = [
                    (item[1], item[2])
                    for item in items_ab
                    if isinstance(item, tuple)
                    and len(item) >= 3
                    and any(k in str(item[0]) for k in ("放弃", "退出"))
                ]
                pos_ab = max(fallback_ab, key=lambda pos: pos[1]) if fallback_ab else None
            if pos_ab:
                tap(*pos_ab)
                log(f"  [恢复] 点击底部'放弃行动'按钮 @{pos_ab}")
                # 该页面本身就是最终确认页，不存在第二个“确认”按钮。
                wait(5)
            else:
                # 没找到放弃按钮, 可能暂停菜单没弹出, 试back
                back()
                wait(2)
            continue
        
        # 弹窗/对话框处理
        if state == "exit_dialog":
            # "是否确认退出游戏?" → 点✕取消 (不要真的退出游戏!)
            log(f"  [恢复] 检测到退出确认弹窗, 点击✕取消")
            # 07/30实机1920x1080：取消按钮中心约(665,742)。旧坐标
            # (580,870)落在弹窗外，导致同一个退出确认框空转15次。
            tap(665, 742)
            wait(2)
            continue

        if state == "announcement":
            # 登录后的全屏公告只能点右上角X；Android back和屏幕中央均无效。
            log(f"  [恢复] 检测到公告弹窗, 尝试关闭")
            if not _dismiss_announcement_overlay():
                items = ocr(shot("announce_close"))
                pos = find_text(items, "关闭") or find_text(items, "知道了") or find_text(items, "确定")
                if pos:
                    tap(*pos)
                    wait(2)
            continue

        if state == "network_error":
            log(f"  [恢复] 检测到网络错误弹窗, 点击重试或关闭")
            items = ocr(shot("net_err"))
            pos = find_text(items, "重新连接") or find_text(items, "重试") or find_text(items, "确定")
            if pos:
                tap(*pos)
            else:
                tap(960, 540)
            wait(3)
            continue

        # 🔴 Android桌面: 游戏未启动! 重新启动游戏
        if state == "home_screen":
            log(f"  [恢复] 检测到Android桌面, 重新启动游戏...")
            # 先重新检测ADB端口 (可能变化)
            detect_mumu_adb_port()
            # 启动游戏
            subprocess.run([ADB, "-s", DEVICE, "shell", "monkey", "-p", PKG, "-c",
                            "android.intent.category.LAUNCHER", "1"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            wait(15)  # 等待游戏启动
            continue

        # login/unknown: 游戏可能在加载中, 等待而不是back (back会干扰加载)
        if state in ("login", "unknown"):
            log(f"  [恢复] {state}状态, 等待游戏加载...")
            # 🔴 主动检查是否有漏检的弹窗
            unknown_path = shot("unknown_check")
            unknown_items = ocr(unknown_path)
            t_detail = " ".join(str(item[0]) for item in unknown_items if isinstance(item, tuple))
            # 放弃确认页当前归类为unknown；命中底部精确按钮后立刻完成退出。
            abandon_buttons = [
                (item[1], item[2])
                for item in unknown_items
                if isinstance(item, tuple)
                and len(item) >= 3
                and str(item[0]).strip() == "放弃行动"
            ]
            if abandon_buttons:
                pos_ab = max(abandon_buttons, key=lambda pos: pos[1])
                tap(*pos_ab)
                log(f"  [恢复] unknown确认页点击底部'放弃行动' @{pos_ab}")
                wait(5)
                continue
            # 检测常见但get_state可能漏检的关键词
            popup_found = False
            for keyword in ["确认退出", "退出游戏", "公告", "关闭", "知道了", "确定", \
                           "重新连接", "网络异常", "是否确认"]:
                if keyword in t_detail:
                    log(f"  [恢复] 发现漏检弹窗: '{keyword}'")
                    popup_found = True
                    break

            if popup_found:
                # 尝试点击✕位置(退出确认) 或 屏幕中央(通用)
                if "退出" in t_detail:
                    tap(580, 870)  # ✕按钮 (左侧)
                else:
                    tap(960, 540)  # 屏幕中央
                wait(2)
                continue

            if state == "login":
                # 🔴 登录界面 → 点击中间下方黄色菱形(开始唤醒), 用户2026-06-29要求
                tap(*POS_LOGIN_START)
                wait(3)

            # 前几次等待久一点, 后面可以短一点
            wait_time = 10 if i < 8 else 5
            wait(wait_time)
            continue
        
        # 其他未知状态, 尝试back
        back()
        wait(2)
        # 检查退出确认框
        t = ocr_text(shot("exit_check"))
        if ("退出" in t or "离开" in t) and "确认" in t:
            items = ocr(shot("exit_check2"))
            for keyword in ["确认", "离开", "确定"]:
                pos = find_text(items, keyword)
                if pos:
                    tap(*pos)
                    wait(2)
                    break
    
    # 兜底: 如果还是回不到章节地图, 尝试goto_chapter
    log(f"  [恢复] {15}次未回到章节地图, 尝试goto_chapter")
    return goto_chapter(ch)


def _find_next_hard_stage_from_full_map(ch):
    """逐屏扫描整张章节地图，再把真实出现的H节点交给详情页判定。

    H节点可能分散在章节地图左右两侧。只检查最右一屏会看到H14-2/H14-4
    却漏掉H14-1/H14-3；这里从当前视野采样，滑到最右，再以重叠步长扫回
    左侧。候选数组不参与选关，只在外层决定需要扫描哪一章。
    """
    frames = []

    def capture(tag):
        path = shot(tag)
        items = ocr(path)
        frames.append((path, items))

    capture(f"hard_map_{ch}_start")
    for index in range(5):
        swipe(1500, 500, 300, 500, 1000)
        wait(1)
        capture(f"hard_map_{ch}_right_{index}")
    # 从右边界以有重叠的步长向左完整回扫；节点文字恰落在屏幕边缘时，
    # 下一帧仍能进入OCR有效区，避免只因一次裁切而消失。
    for index in range(8):
        swipe(350, 500, 1150, 500, 900)
        wait(1)
        capture(f"hard_map_{ch}_left_{index}")

    global _MAINLINE_HARD_MAP_EVIDENCE
    observations = {}
    pattern = re.compile(rf"^H{int(ch)}-(\d{{1,2}})$", re.I)
    for path, items in frames:
        for item in items or []:
            if not isinstance(item, tuple) or len(item) < 3:
                continue
            text, x, y = str(item[0]).strip(), item[1], item[2]
            match = pattern.fullmatch(text)
            if not match:
                continue
            stage_name = f"H{int(ch)}-{int(match.group(1))}"
            observations.setdefault(stage_name, []).append((path, (x, y)))

    chapter_evidence = _MAINLINE_HARD_MAP_EVIDENCE.setdefault(int(ch), set())
    newly_observed = set(observations)
    chapter_evidence.update(newly_observed)

    if not chapter_evidence:
        log(
            f"  [H关全图验证] 第{ch}章共采样{len(frames)}屏，未识别到H节点；"
            "不以候选编号替代解锁证据",
            "WARN",
        )
        return None, None, "hard_not_visible"

    visible = sorted(chapter_evidence, key=_mainline_target_sort_key)
    log(
        f"  [H关全图验证] {len(frames)}屏本次识别={sorted(newly_observed, key=_mainline_target_sort_key)}；"
        f"本轮累计证据={visible}"
    )
    progress = load_progress()
    known_cleared = set(progress.get("cleared", []))
    shelved = set(progress.get("shelved", []))
    from PIL import Image

    for stage_name in visible:
        if stage_name in shelved:
            log(f"  [H关全图验证] {stage_name}已按预算搁置，本轮不重入")
            continue
        current_observations = observations.get(stage_name, [])
        if not current_observations:
            if stage_name in known_cleared:
                log(
                    f"  [H关全图验证] {stage_name}本轮先前已见且账本已有直接完成证据；"
                    "本次OCR漏字不撤销完成状态"
                )
                continue
            log(
                f"  [H关全图验证] {stage_name}本轮先前已由地图OCR确认可见；"
                "本次重扫漏字，仍交给精确详情页复核"
            )
            return stage_name, None, "uncertain_probe"

        strongest = None
        perfect_seen = False
        for path, pos in current_observations:
            try:
                image = Image.open(path).convert("RGB")
                cyan = _stage_marker_cyan_ratio(image, pos) or 0.0
                dark = _stage_marker_dark_cube_ratio(image, pos) or 0.0
                marker = _stage_marker_status(image, pos, max(0.186, cyan))
                score = (int(bool(marker and marker.get("perfect"))), cyan, dark)
                if strongest is None or score > strongest[0]:
                    strongest = (score, pos)
                perfect_seen = perfect_seen or bool(marker and marker.get("perfect"))
            except Exception as exc:
                log(f"  [H关全图验证] {stage_name}节点采样异常: {exc}", "WARN")
        best_pos = strongest[1] if strongest else current_observations[0][1]
        if stage_name in known_cleared and perfect_seen:
            log(f"  [H关全图验证] {stage_name}账本+当前完成色一致，跳过战斗")
            continue
        # 未记账的完成色、深色节点和像素不确定都只允许进入精确详情页；
        # 详情三徽记负责决定补账还是开战。
        reason = "账本无完成记录" if stage_name not in known_cleared else "当前节点未复现完成色"
        log(f"  [H关全图验证] 选择{stage_name}进入详情复核: {reason}")
        return stage_name, best_pos, "uncertain_probe"

    return None, None, None


def _find_next_stage_from_map(ch, retry_imperfect=False, hard_only=False):
    """进入章节地图, 滑到最右边, 检查可见关卡的六芒星

    🔴 2026-07-10 用户设计:
    日常主线优先未通关新关卡；非完美关只在显式补打模式中重选。
    只检查最右边的几个关卡, 始终基于地图实际状态

    返回: (stage_name, pos, status) status="imperfect"|"uncleared"|None
    """
    if hard_only:
        return _find_next_hard_stage_from_full_map(ch)

    # 普通/剧情前沿沿用最右端递进；H关使用上面的全图累计扫描。
    # 滑到最右边
    for i in range(5):
        swipe(1500, 500, 300, 500, 1000)
        wait(1)

    # OCR当前视图的所有关卡
    p = shot("map_rightmost")
    items = ocr(p)
    stages_found = []
    for item in items:
        if isinstance(item, tuple):
            txt, x, y = item[0], item[1], item[2]
            m = re.match(r'^(H?)(\d{1,2})-(\d{1,2})$', txt.strip(), re.I)
            if m:
                prefix = "H" if m.group(1) else ""
                stage_name = f"{prefix}{m.group(2)}-{m.group(3)}"
                if int(m.group(2)) == ch:
                    stages_found.append((stage_name, x, y))

    if not stages_found:
        log(f"  [地图] 最右边未找到第{ch}章关卡", "WARN")
        return None, None, None

    if hard_only:
        stages_found = [row for row in stages_found if row[0].upper().startswith("H")]
        if not stages_found:
            log(
                f"  [H关地图验证] 第{ch}章当前视野没有任何H节点；"
                "候选数组不能替代真实解锁证据",
                "WARN",
            )
            return None, None, "hard_not_visible"
        log(f"  [H关地图验证] OCR确认可见H节点: {[row[0] for row in stages_found]}")

    # 普通/剧情主线优先于H关；同类节点再按地图从左到右处理。
    # 13章实机曾同时出现H13-1与13-22，纯x排序会先打H关并漏掉新解锁
    # 剧情及其奖励。这里修的是节点类别优先级，不写死具体关卡。
    stages_found.sort(key=lambda s: (s[0].upper().startswith("H"), s[1]))
    log(f"  [地图] 最右边可见关卡: {[s[0] for s in stages_found]}")

    # 检查每个关卡的六芒星状态
    from PIL import Image
    img = Image.open(p)
    imperfect_stages = []  # 非完美通关
    uncleared_stages = []  # 未通关
    uncertain_stages = []  # OCR找到了名称，但没有定位到任何节点标志
    progress = load_progress()
    known_cleared = set(progress.get("cleared", []))

    marker_rows = []
    for stage_name, sx, sy in stages_found:
        cyan_ratio = _stage_marker_cyan_ratio(img, (sx, sy)) or 0.0
        dark_fill_ratio = _stage_marker_dark_cube_ratio(img, (sx, sy)) or 0.0
        orange_boss_ratio = _stage_marker_orange_boss_ratio(img, (sx, sy)) or 0.0
        marker_rows.append(
            (stage_name, sx, sy, cyan_ratio, dark_fill_ratio, orange_boss_ratio)
        )
    reference_ratio = max((row[3] for row in marker_rows if row[3] >= 0.08), default=0.186)

    # OCR可能同时读到终局节点标签和右侧详情标题，产生两个同名关卡坐标。
    # 若其中任一坐标已有可信终局/青蓝节点证据且进度也已确认，则整组同名项
    # 都必须跳过，不能让另一个落在白色标题卡上的伪ROI重新进入待办。
    grouped_rows = {}
    for row in marker_rows:
        grouped_rows.setdefault(row[0], []).append(row)
    duplicate_confirmed = set()
    for stage_name, rows in grouped_rows.items():
        if len(rows) < 2 or stage_name not in known_cleared:
            continue
        if any(row[3] >= 0.08 or row[5] >= 0.08 for row in rows):
            duplicate_confirmed.add(stage_name)
    duplicate_reported = set()

    for stage_name, sx, sy, cyan_ratio, dark_fill_ratio, orange_boss_ratio in marker_rows:
        try:
            if stage_name in duplicate_confirmed:
                if stage_name not in duplicate_reported:
                    log(
                        f"  [地图] {stage_name} 同名OCR项已合并；"
                        "存在可信通关节点且进度已确认，整组禁止重复选择"
                    )
                    duplicate_reported.add(stage_name)
                continue
            run_state = _MAINLINE_STAGE_ATTEMPTS.get(stage_name) or {}
            if run_state.get("status") in ("completed", "already_cleared"):
                log(f"  [地图] {stage_name} ✅本轮已完成，禁止重复选择")
                continue

            if ch == 17 and _chapter17_stage_requires_sandbox(stage_name):
                final_status = _chapter17_node_completion_status(img, (sx, sy))
                if final_status and final_status["complete"]:
                    log(f"  [第17章地图] {stage_name} ✅红紫外环+亮色中心，险地+沙盘已闭环")
                elif final_status and final_status["state"] == "risk_or_regular_only":
                    log(
                        f"  [第17章地图] {stage_name}仍为灰色/青蓝未闭环节点，"
                        "必须继续险地/沙盘闭环"
                    )
                    uncleared_stages.append((stage_name, (sx, sy)))
                else:
                    log(f"  [第17章地图] {stage_name}节点颜色不确定，进入详情分阶段取证")
                    uncertain_stages.append((stage_name, (sx, sy)))
                continue

            if orange_boss_ratio >= 0.08:
                if stage_name in known_cleared:
                    log(
                        f"  [地图] {stage_name} 🟠章节终局图标仍可见；"
                        "已有通关记录，禁止重复选择"
                    )
                else:
                    log(
                        f"  [地图] {stage_name} 🟠已识别章节终局战斗节点"
                        f"(orange={orange_boss_ratio:.3f})，判定为待通关"
                    )
                    uncleared_stages.append((stage_name, (sx, sy)))
                continue

            # cyan=0且dark=0不代表空六芒星，只说明OCR文字坐标没有覆盖到
            # 节点标志（H关排版和右侧详情抽屉尤其常见）。没有图形证据时
            # 不得把权威通关记录降级，更不能据此再次消耗理智。
            no_marker_evidence = cyan_ratio < 0.02 and dark_fill_ratio < 0.02
            if no_marker_evidence:
                if stage_name in known_cleared:
                    log(
                        f"  [地图] {stage_name} ⚪节点标志未定位；"
                        "已有通关记录，禁止重复选择"
                    )
                else:
                    log(
                        f"  [地图] {stage_name} ⚪节点标志未定位"
                        f"(cyan={cyan_ratio:.3f}, dark_fill_diag={dark_fill_ratio:.3f})，"
                        "仅判不确定"
                    )
                    uncertain_stages.append((stage_name, (sx, sy)))
                continue

            marker = _stage_marker_status(img, (sx, sy), reference_ratio)
            if marker and marker["perfect"]:
                log(f"  [地图] {stage_name} ✅已完美通关(cyan={cyan_ratio:.3f})")
                if hard_only and stage_name not in known_cleared:
                    log(
                        f"  [H关地图验证] {stage_name}虽呈完成色，但账本无记录；"
                        "必须打开精确详情读取三徽记后才能补账"
                    )
                    uncertain_stages.append((stage_name, (sx, sy)))
            elif marker and marker["cleared"]:
                log(f"  [地图] {stage_name} ⚠️已通关但非完美(cyan={cyan_ratio:.3f})")
                if retry_imperfect:
                    imperfect_stages.append((stage_name, (sx, sy)))
                elif hard_only and stage_name not in known_cleared:
                    uncertain_stages.append((stage_name, (sx, sy)))
            else:
                log(f"  [地图] {stage_name} ❌未通关(cyan={cyan_ratio:.3f}, dark_fill_diag={dark_fill_ratio:.3f})")
                uncleared_stages.append((stage_name, (sx, sy)))
        except Exception as e:
            log(f"  [地图] {stage_name} 检测异常: {e}", "WARN")

    # 非完美关属于已通关；只有专门补打流程才允许它抢占新关卡。
    if imperfect_stages:
        s = imperfect_stages[0]
        log(f"  [地图] 优先重打非完美: {s[0]}")
        return s[0], s[1], "imperfect"

    # 优先级2: 未通关
    if uncleared_stages:
        s = uncleared_stages[0]
        log(f"  [地图] 下一个目标: {s[0]}")
        return s[0], s[1], "uncleared"

    if uncertain_stages:
        if hard_only or ch in (15, 16, 17):
            s = uncertain_stages[0]
            log(
                f"  [地图] 推演章节{s[0]}节点ROI不确定；"
                "改为打开详情读取三枚蓝色徽记，不直接推断通关或开战"
            )
            return s[0], s[1], "uncertain_probe"
        log(
            f"  [地图] 存在无法定位节点标志的关卡: "
            f"{[s[0] for s in uncertain_stages]}；拒绝推断本章完成",
            "WARN",
        )
        return None, None, "uncertain"

    # 🔴 2026-07-10: 最右边的关卡都通关了 = 本章全部通关, 直接下一章
    # 不往左滑找更多 — 左边的肯定也通关了(关卡按顺序解锁)
    log(f"  [地图] 最右边关卡全部通关, 第{ch}章完成")
    return None, None, None

def _is_battle_stage_detail(text, state):
    """Only formation state or actionable battle controls prove a battle node."""
    normalized = str(text or "").upper()
    return state == "formation" or any(
        marker in normalized
        for marker in ("开始行动", "开始突袭", "代理指挥")
    )


def _mainline_stage_detail_confirmed(detail_text, display_name):
    """确认详情抽屉属于精确主线/H目标，而不是相邻节点或地图背景。"""
    text = str(detail_text or "")
    target = re.sub(r"\([^)]*\)", "", str(display_name or "")).strip()
    if not target:
        return False
    exact_target = re.search(
        rf"(?<![A-Z0-9]){re.escape(target)}(?!\d)",
        text,
        re.I,
    )
    detail_semantics = any(
        marker in text
        for marker in (
            "开始行动", "代理指挥", "演习", "开始剧情", "观看序曲",
            "通关", "解锁", "推荐平均等级",
        )
    )
    return bool(exact_target and detail_semantics)


def _story_node_map_marker_cleared(image_path, display_name, items=None):
    """Return whether a story node has the cyan completed badge on the map.

    Story nodes do not own the three battle-result badges shown in a stage
    detail panel.  In late chapters their direct completion evidence is the
    filled cyan hexagon immediately to the left of the node label.  Keep this
    detector local to the OCR-confirmed node so unrelated cyan decorations do
    not become completion evidence.
    """
    items = items if items is not None else ocr(image_path)
    pos = find_text(items, display_name)
    if not pos:
        return False
    try:
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        cx, cy = pos
        box = (
            max(0, cx - 150),
            max(0, cy - 70),
            min(image.width, cx - 40),
            min(image.height, cy + 50),
        )
        crop = image.crop(box)
        total = max(1, crop.width * crop.height)
        cyan = 0
        for r, g, b in crop.getdata():
            if r <= 45 and g >= 105 and b >= 175 and b >= g + 35:
                cyan += 1
        return (cyan / total) >= 0.04
    except Exception as exc:
        log(f"  [剧情节点标记] {display_name}读取失败: {exc}", "WARN")
        return False


def _wait_story_stage_completion(ch, display_name, timeout=600):
    """Close a story node by visual state; MAA has no task chain to monitor here."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = get_state()
        if state == "story":
            skip_story()
        elif state in ("reward", "victory"):
            dismiss_reward()
        elif state == "chapter_map":
            map_path = shot(f"story_map_verify_{display_name}")
            marker_cleared = _story_node_map_marker_cleared(map_path, display_name)
            cleared, _is_perfect = (True, True) if marker_cleared else verify_stage_cleared(ch, display_name)
            if cleared:
                source = "剧情关(地图蓝色完成标记)" if marker_cleared else "剧情关(地图节点验证)"
                update_progress(display_name, "cleared", source)
                return True
        wait(3)
    log(f"  ❌ {display_name}剧情结束后未在地图节点形成通关证据", "ERROR")
    return False


def _chapter17_switch_to_risk(display_name, image_path, text):
    """在17章关卡详情内切到险地作战；只接受OCR确认后的状态。

    左下角模式键显示的是“可切换到的目标模式”，不是当前模式：
    显示“险地作战”代表当前仍在常规，显示“常规作战”才代表当前已在险地。
    """
    compact = re.sub(r"\s+", "", str(text or ""))
    if "常规作战" in compact:
        return image_path, text, True
    if "险地作战" not in compact:
        log(f"  ⛔ {display_name}详情未识别到常规/险地切换标签", "ERROR")
        return image_path, text, False
    items = ocr(image_path)
    pos = find_text(items, "险地作战")
    if not pos:
        log(f"  ⛔ {display_name}虽识别险地作战切换键但无法定位", "ERROR")
        return image_path, text, False
    tap(*pos)
    wait(3)
    next_path = shot(f"chapter17_{display_name}_risk")
    next_text = ocr_text(next_path)
    confirmed = "常规作战" in re.sub(r"\s+", "", next_text)
    log(f"  [第17章阶段] {display_name}切换险地作战: {'已确认' if confirmed else '失败'}")
    return next_path, next_text, confirmed


def _chapter17_sandbox_option_point(items, level, side):
    """在独立的沙盘假设页按等级行和左右半屏定位选项。"""
    level_patterns = (f"LV.{level}", f"LV{level}", f"Lv.{level}", f"Lv{level}")
    level_rows = [
        (int(y), int(x))
        for text, x, y in (items or [])
        if any(pattern in re.sub(r"\s+", "", str(text)) for pattern in level_patterns)
    ]
    if not level_rows:
        return None
    row_y = sorted(level_rows)[0][0]
    candidates = []
    excluded = ("LV", "沙盘", "推演", "开始行动", "确认", "返回")
    for text, x, y in items or []:
        compact = re.sub(r"\s+", "", str(text))
        if not compact or any(marker in compact.upper() for marker in excluded):
            continue
        # 选择页中选项正文位于等级标题下方约80~220像素。旧实现允许
        # 标题同一行的“未得分”等文字进入候选，可能把点击点抬到卡片外。
        if not 80 <= int(y) - row_y <= 220 or not 140 <= int(x) <= 1780:
            continue
        if side == "left" and int(x) < 960:
            candidates.append((int(x), int(y)))
        elif side == "right" and int(x) > 960:
            candidates.append((int(x), int(y)))
    if not candidates:
        return None
    # 同一卡片可能被OCR拆成数段；以该半屏候选的包围中心作为点击点。
    return (
        int((min(x for x, _ in candidates) + max(x for x, _ in candidates)) / 2),
        int((min(y for _, y in candidates) + max(y for _, y in candidates)) / 2),
    )


def _chapter17_sandbox_choice_highlighted(image_path, level, side):
    """用红色高亮验证沙盘假设真的被选中，不能只相信点击成功。"""
    try:
        from PIL import Image

        im = Image.open(image_path).convert("RGB")
        w, h = im.size
        if level == 1:
            y1, y2 = int(h * 0.363), int(h * 0.548)
        elif level == 2:
            y1, y2 = int(h * 0.641), int(h * 0.826)
        else:
            return False
        if side == "left":
            x1, x2 = int(w * 0.047), int(w * 0.500)
        elif side == "right":
            x1, x2 = int(w * 0.500), int(w * 0.956)
        else:
            return False
        crop = im.crop((x1, y1, x2, y2))
        red_pixels = sum(
            1
            for r, g, b in crop.getdata()
            if r > 80 and r > g * 1.35 and r > b * 1.20
        )
        return red_pixels / max(1, crop.width * crop.height) >= 0.15
    except Exception as e:
        log(f"  [第17章沙盘] 选项高亮验证异常: {e}", "WARN")
        return False


def _chapter17_sandbox_level_point(items, level):
    """定位LV下方的“未选择假设”；点标题本身不会展开选项。"""
    expected = f"LV.{level}"
    level_pos = None
    for text, x, y in items or []:
        compact = re.sub(r"\s+", "", str(text)).upper()
        if expected in compact and int(x) >= 1300 and 300 <= int(y) <= 700:
            level_pos = (int(x), int(y))
            break
    if not level_pos:
        return None
    candidates = []
    for text, x, y in items or []:
        compact = re.sub(r"\s+", "", str(text))
        if (
            "未选择假设" in compact
            and int(x) >= 1300
            and 15 <= int(y) - level_pos[1] <= 100
        ):
            candidates.append((int(x), int(y)))
    if candidates:
        return min(candidates, key=lambda point: abs(point[1] - level_pos[1]))
    return None


def _chapter17_sandbox_reselect_point(detail_path):
    """返回已有沙盘假设右侧的圆形重选按钮位置。

    已保存组合时LV文本和说明本身不会稳定打开选择页；实机入口位于沙盘标题
    行最右侧。坐标按截图尺寸换算，点击后仍须由调用方OCR确认选择页，不能
    仅凭点击动作认定成功。
    """
    try:
        from PIL import Image
        with Image.open(detail_path) as image:
            width, height = image.size
        return (int(width * 0.957), int(height * 0.274))
    except Exception as exc:
        log(f"  [第17章沙盘] 无法读取配置页尺寸: {exc}", "WARN")
        return None


def _chapter17_enter_sandbox(
    display_name, job_path, detail_path, detail_text, sandbox_choices=None,
):
    """由关卡详情进入沙盘；优先作业说明，稀缺时允许受控组合兜底。"""
    choices = sandbox_choices or _chapter17_sandbox_choices_from_job(job_path)
    if not choices:
        log(f"  ⛔ {display_name}当前MAA作业没有明确沙盘两级选项", "ERROR")
        return False
    if sandbox_choices:
        readable = tuple("左" if value == "left" else "右" for value in choices)
        log(
            f"  [第17章沙盘兜底] 复用险地作业，随机未试组合: "
            f"LV.1={readable[0]}, LV.2={readable[1]}"
        )

    # 沙盘入口属于险地详情。左下角若显示“险地作战”，说明当前仍在常规，
    # 必须先切到险地；若显示“常规作战”，说明当前已在险地，禁止再点回常规。
    compact = re.sub(r"\s+", "", str(detail_text or ""))
    if "险地作战" in compact:
        detail_path, detail_text, risk_confirmed = _chapter17_switch_to_risk(
            display_name, detail_path, detail_text,
        )
        if not risk_confirmed:
            return False
        compact = re.sub(r"\s+", "", str(detail_text or ""))

    if "沙盘推演" not in compact:
        log(f"  ⛔ {display_name}险地尚未解锁沙盘入口，拒绝盲点", "ERROR")
        return False

    config_compact = re.sub(r"\s+", "", str(detail_text or "")).upper()
    if not all(marker in config_compact for marker in ("LV.1", "LV.2")):
        sandbox_pos = find_text(ocr(detail_path), "沙盘推演")
        if not sandbox_pos or sandbox_pos[0] < 1300:
            log(f"  ⛔ {display_name}无法定位右侧沙盘推演模式栏，拒绝盲点", "ERROR")
            return False
        tap(*sandbox_pos)
        log(f"  [第17章沙盘] {display_name}切换到沙盘配置页 @{sandbox_pos}")
        wait(2)
        detail_path = shot(f"chapter17_{display_name}_sandbox_config")
        detail_text = ocr_text(detail_path)
        config_compact = re.sub(r"\s+", "", detail_text).upper()
    else:
        log(f"  [第17章沙盘] {display_name}已在沙盘配置状态，不重复点击模式栏")
    if not all(marker in config_compact for marker in ("LV.1", "LV.2")):
        log(f"  ⛔ {display_name}点击沙盘模式栏后未出现LV.1/LV.2配置，停止", "ERROR")
        return False

    config_items = ocr(detail_path)
    if "未选择假设" in config_compact:
        # 首次配置时状态文字不可点击；“开始推演”才会打开独立选择页。
        open_choices_pos = find_text(config_items, "开始推演")
        open_source = "开始推演"
    else:
        # 游戏记住上一次假设后，“开始推演”会直接进入编队，导致随机兜底
        # 根本没有应用却被误记成新组合。实机应点击标题最右侧圆形重选按钮。
        open_choices_pos = _chapter17_sandbox_reselect_point(detail_path)
        open_source = "已选假设右侧重选按钮"
    if not open_choices_pos:
        log(f"  ⛔ {display_name}沙盘配置页无法定位假设选择入口，停止", "ERROR")
        return False
    tap(*open_choices_pos)
    log(f"  [第17章沙盘] {display_name}通过{open_source}打开假设选择页 @{open_choices_pos}")
    wait(4)
    choices_path = shot(f"chapter17_{display_name}_sandbox_choices")
    choices_text = re.sub(r"\s+", "", ocr_text(choices_path))
    # 任何指定组合都必须真实打开选择页并逐项高亮确认。若仍直接进编队，
    # 说明入口策略失效；此时不能把保存组合冒充成本轮随机/作业组合。
    if _is_formation_page_text(choices_text):
        log(
            f"  ⛔ {display_name}未能重开假设选择页，游戏沿用旧组合直接进入编队；"
            "停止且不记录本轮组合",
            "ERROR",
        )
        back()
        wait(2)
        return False
    if "选择沙盘推演假设" not in choices_text or not all(
        marker in choices_text.upper() for marker in ("LV.1", "LV.2")
    ):
        log(f"  ⛔ {display_name}未进入独立假设选择页，停止且不盲点", "ERROR")
        return False

    for level, side in enumerate(choices, start=1):
        option_items = ocr(choices_path)
        option_pos = _chapter17_sandbox_option_point(option_items, level, side)
        if not option_pos:
            log(
                f"  ⛔ {display_name}沙盘LV.{level}无法按OCR定位{'左' if side == 'left' else '右'}项，"
                "停止且不盲点",
                "ERROR",
            )
            return False
        tap(*option_pos)
        log(f"  [第17章沙盘] {display_name} LV.{level}选择{'左' if side == 'left' else '右'} @{option_pos}")
        wait(2)
        choices_path = shot(f"chapter17_{display_name}_sandbox_lv{level}_selected")
        if not _chapter17_sandbox_choice_highlighted(choices_path, level, side):
            log(f"  ⛔ {display_name} LV.{level}目标选项未出现红色高亮，停止", "ERROR")
            return False

    confirm_pos = find_text(ocr(choices_path), "确定")
    if not confirm_pos:
        log(f"  ⛔ {display_name}两级假设已选但未定位到确定按钮，停止", "ERROR")
        return False
    tap(*confirm_pos)
    log(f"  [第17章沙盘] {display_name}确认两级假设 @{confirm_pos}")
    wait(4)

    ready_path = shot(f"chapter17_{display_name}_sandbox_ready")
    ready_text = re.sub(r"\s+", "", ocr_text(ready_path))
    ready_items = ocr(ready_path)
    if "沙盘推演" not in ready_text or "未选择假设" in ready_text:
        log(f"  ⛔ {display_name}确认后未回到已选假设的沙盘详情，停止", "ERROR")
        return False
    start_sim_pos = find_text(ready_items, "开始推演")
    if not start_sim_pos:
        log(f"  ⛔ {display_name}沙盘两级选择后未出现开始推演，拒绝启动MAA", "ERROR")
        return False
    tap(*start_sim_pos)
    log(f"  [第17章沙盘] {display_name}点击开始推演 @{start_sim_pos}")
    wait(4)
    if get_state() == "formation":
        return True
    return _enter_formation(17, display_name, allow_expiring_potion=False) is True


def _find_and_enter_stage(
    ch,
    display_name,
    force_replay=False,
    chapter17_phase="risk",
    chapter17_job_path=None,
    chapter17_sandbox_choices=None,
):
    """从章节地图: 找关卡→选难度→进编队 (完整流程, 每次attempt都调用)"""
    handle_popups()
    is_training_stage = str(display_name or "").strip().upper().startswith("TR-")
    is_hard_stage = str(display_name or "").strip().upper().startswith("H")
    detail_badge_required = ch in DETAIL_BADGE_CHAPTERS or is_hard_stage
    
    # 🔴 2026-07-01 修复: 章节地图左下角有难度选择器("标准实战环境"),
    # 必须先切换为"困难"/"磨难", 再点击关卡. 否则点击的是标准难度的关卡.
    p_map = shot("map_difficulty")
    txt_map = ocr_text(p_map)
    if not is_training_stage and ("标准实战环境" in txt_map or "实战环境" in txt_map):
        log("  [难度] 检测到标准实战环境, 切换为困难/磨难")
        # 点击左下角难度选择器 (大约在(200, 950)附近)
        # 先尝试OCR定位
        items_map = ocr(p_map)
        diff_pos = find_text(items_map, "标准实战环境") or find_text(items_map, "实战环境")
        if diff_pos:
            tap(*diff_pos)
            log(f"  [难度] 点击难度选择器 @{diff_pos}")
        else:
            # 兜底: 左下角固定坐标
            tap(200, 950)
            log("  [难度] 点击难度选择器 (固定坐标 200,950)")
        wait(2)
        # 截图确认弹出难度选项
        p_diff = shot("difficulty_options")
        txt_diff = ocr_text(p_diff)
        # 点击"困难"或"磨难"
        hardest = DIFFICULTY.get(ch, {}).get("hardest", "困难")
        diff_opt_pos = find_text(ocr(p_diff), hardest)
        if diff_opt_pos:
            tap(*diff_opt_pos)
            log(f"  [难度] 选择 {hardest} @{diff_opt_pos}")
        else:
            # 兜底: 点选项区域中间
            tap(200, 850)
            log(f"  [难度] 选择 {hardest} (固定坐标)")
        wait(2)
    
    # 找关卡 (只在当前视图找, 不乱滑)
    # 🔴 2026-07-02 修复: exact=True要求OCR文本完全等于关卡名, 但OCR可能返回"10-18 OPERATION"
    # 改为exact=False(包含匹配), 这样"10-18"能匹配到"10-18 OPERATION"
    # 🔴 2026-07-08 修复: display_name含难度后缀如"12-4(磨难)", 但地图OCR只有"12-4"
    # 剥离难度后缀用于地图搜索
    map_search = re.sub(r'\([^)]*\)', '', display_name).strip()  # "12-4(磨难)" → "12-4"
    p = shot("map")
    items = ocr(p)
    pos = _find_stage_node_text(items, map_search)
    if not pos:
        # 🔴 2026-07-03 修复: 关卡可能在右侧很远(如11-7在11-6右侧), 需要多次滑动
        # 之前只滑动一次, 11-6通关后地图视口在左侧(11-1~11-5), 11-7需要多次向右滑
        # 策略: 先多次向右滑(最常见), 再向下滑, 最后向左滑
        found = False
        # 向右滑动最多5次 (章节地图可能很宽, 11-7离左侧很远)
        for i in range(5):
            swipe(1500, 500, 300, 500, 1200)  # 加大滑动距离: 1200px
            wait(2)
            p = shot(f"map_right_{i}")
            pos = _find_stage_node_text(ocr(p), map_search)
            if pos:
                log(f"  [找关卡] 向右滑动{i+1}次后找到{display_name}")
                found = True
                break
        # 向右没找到, 尝试向下滑
        if not found:
            for i in range(3):
                swipe(960, 800, 960, 300, 1200)
                wait(2)
                p = shot(f"map_down_{i}")
                pos = _find_stage_node_text(ocr(p), map_search)
                if pos:
                    log(f"  [找关卡] 向下滑动{i+1}次后找到{display_name}")
                    found = True
                    break
        # 向下没找到, 尝试向左滑 (可能之前滑过头了)。单次横跨1200px
        # 会从12-13~18直接跳到12-6~11，恰好漏掉12-12；改用有重叠的
        # 800px步长并增加采样次数，保证每个中间节点至少进入一个视野。
        if not found:
            for i in range(6):
                swipe(350, 500, 1150, 500, 900)
                wait(2)
                p = shot(f"map_left_{i}")
                pos = _find_stage_node_text(ocr(p), map_search)
                if pos:
                    log(f"  [找关卡] 向左滑动{i+1}次后找到{display_name}")
                    found = True
                    break
    
    # 🔴 2026-07-02 修复: 新章节第一关可能显示为"11-1"而非"11-2"
    # 进度文件中current=11-2, 但游戏地图上第一关是11-1
    # 如果找不到11-2, 尝试找11-1 (章节第一关编号从1开始)
    if not pos and display_name.endswith("-2"):
        first_stage = display_name[:-1] + "1"  # 11-2 → 11-1
        pos = _find_stage_node_text(items, first_stage)
        if not pos:
            swipe(960, 800, 960, 300, 1500)
            wait(2)
            p = shot("map_scroll2")
            pos = _find_stage_node_text(ocr(p), first_stage)
        if pos:
            log(f"  ℹ️ 未找到{display_name}, 改找{first_stage} (章节第一关)")
            display_name = first_stage  # 更新display_name用于后续逻辑
    
    if not pos:
        log(f"  ❌ 地图无{display_name}", "ERROR")
        debug_p = shot("map_debug")
        debug_t = ocr_text(debug_p)
        log(f"  [调试] 地图OCR: {debug_t[:100]}")
        if "TR-" in debug_t and not is_training_stage:
            # 17章地图会长期显示已经完成的TR节点。目标节点未找到时，仅凭
            # 同一视野里出现任意TR文本，既不能证明它是目标的直接前置，也
            # 不能证明它尚未完成。此前因此把三徽记已亮的TR-28误当成17-15
            # 的未完成前置并重复进入。教学关不再由主线调度器自动执行；
            # 目标缺失仍按导航/前沿不确定处理，等待用户手动完成或地图直接
            # 证明目标已经解锁。
            visible_tr = re.findall(r'TR-\d+', debug_t)
            log(
                f"  ℹ️ 当前视野含教学节点{sorted(set(visible_tr))}，"
                "但这不是目标前置未完成证据；不自动进入教学关",
                "WARN",
            )
        return False
    
    # 点击关卡前复用与战后完全相同的节点ROI算法，杜绝两套标准。
    try:
        if is_training_stage:
            raise LookupError("TR教学关跳过普通主线节点徽记预检查")
        from PIL import Image
        img = Image.open(p).convert('RGB')
        target_ratio = _stage_marker_cyan_ratio(img, pos)
        references = []
        for item in items:
            if not isinstance(item, tuple) or len(item) < 3:
                continue
            text, sx, sy = str(item[0]).strip(), item[1], item[2]
            if re.search(r'(?<!\d)(?:H)?\d{1,2}-\d{1,2}(?!\d)', text, re.I):
                ratio = _stage_marker_cyan_ratio(img, (sx, sy))
                if ratio is not None and ratio >= 0.08:
                    references.append(ratio)
        reference = max(references) if references else 0.186
        marker = _stage_marker_status(img, pos, reference)
        if ch == 17 and _chapter17_stage_requires_sandbox(display_name):
            final_status = _chapter17_node_completion_status(img, pos)
            phase_progress = load_progress()
            phase_record = (
                phase_progress.get("chapter17_phases", {}).get(display_name, {})
            )
            phase_pending = not (
                _chapter17_phase_has_direct_evidence(
                    phase_progress, display_name, "risk"
                )
                and _chapter17_phase_has_direct_evidence(
                    phase_progress, display_name, "sandbox"
                )
            )
            if (
                final_status
                and final_status["complete"]
                and chapter17_phase != "sandbox"
                and not phase_pending
            ):
                log(
                    f"  [第17章战前闭环] {display_name}为红紫外环+亮色中心，险地+沙盘均已完成"
                )
                return ("already_cleared", True)
            if final_status:
                if (
                    phase_record.get("risk") == "cleared"
                    and phase_record.get("sandbox") != "cleared"
                ):
                    pending_message = "阶段账本仍为沙盘待补，继续打开详情复核"
                elif phase_pending:
                    pending_message = "阶段账本仍有险地/沙盘待办，继续打开详情复核"
                else:
                    pending_message = "不得用青蓝节点或详情三徽记冒充最终完成"
                log(
                    f"  [第17章战前闭环] {display_name}节点={final_status['state']}，"
                    + pending_message
                )
        elif marker and marker["cleared"] and not detail_badge_required:
            is_perfect = marker["perfect"]
            log(
                f"  [战前节点ROI] cyan={marker['cyan_ratio']:.3f}, "
                f"dark_fill_diag={marker['dark_fill_ratio']:.3f}, "
                f"threshold={marker['perfect_threshold']:.3f}, perfect={is_perfect}"
            )
            if is_perfect:
                return ("already_cleared", True)
            if not force_replay:
                return ("already_cleared", False)
            log(f"  ↻ {display_name} 为青蓝填充但未达完美阈值，继续补打")
        elif marker and marker["cleared"] and detail_badge_required:
            log(
                f"  [战前节点ROI] {display_name}地图像素仅作定位参考；"
                "后期章节必须打开详情读取三枚徽记"
            )
    except LookupError:
        pass
    except Exception as e:
        log(f"  [预检查] 六芒星检测异常: {e}", "WARN")
    
    if ch in DETAIL_BADGE_CHAPTERS:
        p, t, detail_confirmed = _open_late_chapter_stage_detail(
            pos, display_name, screenshot_prefix="detail",
        )
    else:
        tap(*pos)
        wait(3)
        p = shot("detail")
        t = ocr_text(p)
        detail_confirmed = _mainline_stage_detail_confirmed(t, display_name)

    if str(display_name or "").upper().startswith("H") and not detail_confirmed:
        log(
            f"  ⛔ 点击H节点后未在详情页确认精确关卡名{display_name}及关卡控件；"
            "拒绝读取作业或启动MAA",
            "ERROR",
        )
        return False

    if ch == 17 and _chapter17_stage_requires_sandbox(display_name):
        if not detail_confirmed:
            log(f"  ⛔ 未确认详情页属于{display_name}，拒绝进入第17章阶段", "ERROR")
            return False
        if chapter17_phase == "sandbox":
            if not chapter17_job_path:
                log(f"  ⛔ {display_name}沙盘阶段缺少已选MAA作业", "ERROR")
                return False
            if _chapter17_enter_sandbox(
                display_name, chapter17_job_path, p, t,
                sandbox_choices=chapter17_sandbox_choices,
            ):
                return (True, display_name)
            return False

        # 阶段账本中的 risk=cleared 来自此前真实险地结算/详情徽记闭环，
        # 它比本次详情页受动画、缩放影响的瞬时徽记采样更可靠。旧流程仍重新
        # 读取三徽记，一旦误读为0/3就会再次进入险地编队，导致所谓“补沙盘”
        # 实际重复打险地。这里明确把已确认的险地阶段交还给上层，随后只走
        # _run_chapter17_sandbox_phase；不得再次点开始行动。
        phase_progress = load_progress()
        phase_record = (
            (phase_progress.get("chapter17_phases") or {}).get(display_name) or {}
        )
        if (
            _chapter17_phase_has_direct_evidence(
                phase_progress, display_name, "risk"
            )
            and not _chapter17_phase_has_direct_evidence(
                phase_progress, display_name, "sandbox"
            )
        ):
            log(
                f"  [第17章阶段账本] {display_name}险地已有直接完成证据；"
                "跳过瞬时徽记复判，转入沙盘专用入口"
            )
            return ("chapter17_risk_cleared", True)

        p, t, risk_confirmed = _chapter17_switch_to_risk(display_name, p, t)
        if not risk_confirmed:
            return False
        detail_status = _scored_chapter_detail_star_status(p)
        log(
            f"  [第17章险地战前] {display_name}: lit={detail_status['lit']}/3, "
            f"ratios={[round(v, 3) for v in detail_status['ratios']]}"
        )
        if detail_status["perfect"]:
            return ("chapter17_risk_cleared", True)

    # 后期章节必须在详情页读取三枚蓝色徽记。地图节点像素只能帮助定位，
    # 不得再直接推进进度（17-14曾因此被误写为已完美）。第17章沙盘关已在
    # 上面按两阶段处理，不能再次落入此分支。
    if detail_badge_required and not (
        ch == 17 and _chapter17_stage_requires_sandbox(display_name)
    ):
        if not detail_confirmed:
            log(f"  ⛔ 未确认详情页属于{display_name}，拒绝进入编队", "ERROR")
            return False
        detail_status = _scored_chapter_detail_star_status(p)
        log(
            f"  [推演章节战前详情徽记] {display_name}: lit={detail_status['lit']}/3, "
            f"ratios={[round(v, 3) for v in detail_status['ratios']]}"
        )
        if detail_status["perfect"]:
            return ("already_cleared", True)
        if detail_status["cleared"] and not force_replay:
            return ("already_cleared", False)
    
    # 🔴 2026-07-02 修复: 剧情关识别 (三角叶轮标识, 无战斗)
    # 🔴 2026-07-12: 先检查state, 已在formation页=战斗关, 不走剧情关逻辑
    # OCR可能漏检"开始行动"文字, 但state=formation是可靠的
    cur_state = get_state()
    # OPERATION is a generic node header and also appears on story nodes.  It is
    # not evidence that a battle formation page exists.
    is_battle_detail = _is_battle_stage_detail(t, cur_state)
    if not is_battle_detail and ("开始剧情" in t or "观看序曲" in t):
        log("  剧情关→开始剧情")
        story_pos = find_text(ocr(p), "开始剧情") or find_text(ocr(p), "观看序曲")
        if story_pos:
            tap(*story_pos)
        wait(5)
        skip_story()
        if _wait_story_stage_completion(ch, display_name):
            return "story_cleared"
        return False
    
    # 🔴 2026-07-02 新增: 无"开始行动"按钮的关卡 = 剧情关
    # 10-18等三角叶轮关卡点击后不显示"开始行动", 而是直接进入剧情或停留在地图
    if "开始行动" not in t and "开始剧情" not in t:
        # 检查是否直接进入了剧情播放
        state = get_state()
        if state == "story":
            log(f"  剧情关(无开始行动)→直接跳过剧情")
            skip_story()
            wait(5)
            if _wait_story_stage_completion(ch, display_name):
                return "story_cleared"
            return False
        # 还在章节地图 = 点击未成功打开关卡, 重新尝试
        if state == "chapter_map":
            log(f"  ⚠️ 点击{display_name}后仍在章节地图, 重新定位点击")
            # 🔴 2026-07-02 修复: 之前直接标记通关是错误的, 必须真正进入剧情
            for retry in range(3):
                p_retry = shot(f"story_retry_{retry}")
                items_retry = ocr(p_retry)
                pos_retry = _find_stage_node_text(items_retry, display_name)
                if pos_retry:
                    tap(*pos_retry)
                    log(f"  [剧情重试{retry+1}] 点击{display_name} @{pos_retry}")
                    wait(5)
                    state2 = get_state()
                    if state2 == "story":
                        log(f"  剧情关→跳过剧情")
                        skip_story()
                        wait(5)
                        if _wait_story_stage_completion(ch, display_name):
                            return "story_cleared"
                        break
                    elif state2 != "chapter_map":
                        # 进入其他状态, 可能是详情页
                        log(f"  [剧情重试{retry+1}] 状态={state2}, 非chapter_map")
                        break
                else:
                    log(f"  [剧情重试{retry+1}] 未找到{display_name}")
                wait(2)
            # 多次重试后仍在章节地图 = 点击确实失败
            final_state = get_state()
            if final_state == "chapter_map":
                log(f"  ❌ {display_name}点击3次后仍在章节地图, 无法进入剧情", "ERROR")
                return False
    
    # 锁定关
    if "通关" in t and "解锁" in t:
        log(f"  ❌ {display_name}未解锁", "ERROR")
        return False
    
    # 进编队
    formation_result = _enter_formation(ch, display_name)
    # 🔴 2026-07-02 修复: 返回实际进入的关卡名(可能是11-1而非11-2), 供clear_stage同步作业
    if formation_result is True:
        return display_name  # 返回关卡名(如"11-1")
    return formation_result  # False / "stamina"


def _has_red_expiring_potion(image_path):
    """图形确认恢复窗右侧红色药剂本体；到期语义另由同一张图的OCR确认。"""
    try:
        from PIL import Image
        im = Image.open(image_path).convert("RGB")
        w, h = im.size
        # 0720实机1920x1080：右侧红色药剂主体约在 x=0.635~0.755, y=0.27~0.51。
        # 旧ROI误看左下到期标签；新版界面用黄色/绿色天数条，红色来自药剂本体。
        crop = im.crop((int(w * 0.635), int(h * 0.27), int(w * 0.755), int(h * 0.51)))
        red_pixels = sum(
            1 for r, g, b in crop.getdata()
            if r > 100 and r > g * 1.15 and r > b * 1.05
        )
        return red_pixels >= max(1200, int(crop.width * crop.height * 0.10))
    except Exception as e:
        log(f"  [临期药剂] 红色药剂图形检测失败: {e}", "WARN")
        return False


def _red_expiring_potion_selected(image_path):
    """确认右侧红药上方出现减号选择标记，防止仍误用默认选中的蓝药。"""
    try:
        from PIL import Image
        im = Image.open(image_path).convert("RGB")
        w, h = im.size
        marker = im.crop((
            int(w * 0.714), int(h * 0.278),
            int(w * 0.755), int(h * 0.352),
        ))
        dark_pixels = sum(1 for r, g, b in marker.getdata() if r < 80 and g < 80 and b < 80)
        return dark_pixels >= max(900, int(marker.width * marker.height * 0.25))
    except Exception as e:
        log(f"  [临期药剂] 红药选择标记检测失败: {e}", "WARN")
        return False


def _consume_confirmed_red_expiring_potion(display_name, image_path=None):
    """只在理智恢复弹窗和红色临期标签双重确认后使用一份药剂。"""
    image_path = image_path or shot("sanity_restore_expiring")
    text = ocr_text(image_path)
    if not any(k in text for k in ("使用药剂", "使用至纯源石", "理智", "SANITY", "恢复")):
        log("  [临期药剂] 当前不是理智恢复弹窗，不执行用药")
        return False
    if "药剂到期" not in text or not re.search(r"\d+\s*天", text):
        log("  [临期药剂] 恢复弹窗未确认到期天数语义，不执行用药")
        return False
    if not _has_red_expiring_potion(image_path):
        log("  [临期药剂] 恢复弹窗中未确认右侧红色药剂，不执行用药")
        return False
    tap(1320, 400)
    wait(2)
    selected_path = shot("sanity_restore_red_selected")
    if not _red_expiring_potion_selected(selected_path):
        log("  [临期药剂] 点击后未确认红药选择标记，不执行确认", "ERROR")
        return False
    log("  [临期药剂] 红色药剂本体、到期天数及选择标记均已确认，使用1份")
    tap(1635, 865)  # 药剂页确认；不切换到右侧源石页签
    wait(3)
    restored = get_stamina()
    _RUN_SUMMARY.setdefault("sanity_potions", []).append({
        "stage": display_name,
        "kind": "red_expiring",
        "count": 1,
        "stamina_after": restored,
    })
    log(f"  [临期药剂] 已恢复，当前理智={restored}/210；关闭窗口后重新定位关卡")
    tap(1170, 865)  # 使用后窗口不会自动关闭
    wait(3)
    return True


def _open_restore_and_consume_expiring_potion_after_zero_fight(display_name, image_path):
    """零次Fight后只尝试红色临期药，并区分自然理智不足与技术失败。

    返回 ``retry_stage`` 表示已使用红色临期药，``stamina`` 表示已直接
    确认理智不足但没有获准药剂；False 才表示页面语义无法确认。
    """
    text = ocr_text(image_path)
    # 有些 MAA 版本会打开恢复窗；这种情况直接走双重确认。
    if any(k in text for k in ("使用药剂", "使用至纯源石", "SANITY", "恢复")):
        if _consume_confirmed_red_expiring_potion(display_name, image_path):
            return "retry_stage"
        return "stamina"

    # 当前 MAA 6.14.2 在理智不足时不点击开始行动，只停在关卡详情页。
    # 必须同时确认精确关卡名、代理和开始按钮，才允许由脚本打开恢复窗。
    if not (
        display_name in text
        and "代理指挥" in text
        and "开始行动" in text
    ):
        log(
            f"  [临期药剂] 零次Fight后未确认{display_name}详情页，拒绝点击开始行动",
            "WARN",
        )
        return False
    log(f"  [临期药剂] 已确认{display_name}详情页；点击开始行动打开理智恢复窗口")
    result = _enter_formation(0, display_name, allow_expiring_potion=True)
    return result if result in ("retry_stage", "stamina") else False


def _enter_formation(ch, display_name, allow_expiring_potion=True):
    """从关卡详情页进入编队界面
    
    返回: True=成功进编队, False=失败, "stamina"=理智不足,
    "retry_stage"=使用药剂后已回地图，调用者必须重新定位当前关卡
    """
    p_detail = shot("before_start")
    items_detail = ocr(p_detail)
    # “附加条件”说明可能含“敌人提前开始行动”，只能接受右下角操作按钮区域。
    start_label = ""
    start_pos = None
    for text, x, y in items_detail:
        compact = re.sub(r"\s+", "", str(text))
        label = next((name for name in ("开始行动", "开始突袭") if name in compact), "")
        if label and x >= 1350 and y >= 800:
            start_label, start_pos = label, (x, y)
            break
    if start_pos:
        tap(*start_pos)
        log(f"  [进编队] OCR定位'{start_label}' @{start_pos}")
    else:
        tap(*POS_START_BATTLE)
        log(f"  [进编队] 固定坐标 {POS_START_BATTLE}")
    wait(6)  # 等待编队界面加载
    
    state = get_state()
    log(f"  [进编队] 点击后状态={state}")
    
    # 🔴 检查理智不足弹窗 (弹出"使用药剂恢复/使用至纯源石恢复"对话框)
    if state != "formation":
        p_diag = shot("after_start_diag")
        diag_txt = ocr_text(p_diag)
        log(f"  ⚠️ 未进编队! OCR={diag_txt[:80]}", "ERROR")
        
        # 理智不足: 弹出药剂恢复对话框
        if any(k in diag_txt for k in ["使用药剂", "使用至纯源石", "理智", "SANITY", "恢复"]):
            if allow_expiring_potion and _consume_confirmed_red_expiring_potion(
                display_name, p_diag,
            ):
                # 关闭理智窗后实际回到章节地图，不能再沿用详情页的旧坐标。
                return "retry_stage"
            log("  ❌ 理智不足且未检测到可用红色临期药剂；禁止使用源石", "ERROR")
            tap(1170, 865)
            wait(2)
            return "stamina"
    
    if state == "story":
        skip_story()
        wait(5)

    if get_state() != "formation":
        log("  ❌ 未进编队", "ERROR")
        return False
    return True

# ============================================================
# 场景模式: 日常任务
# ============================================================

def _recover_daily_retry_page():
    """网络弹窗恢复后确认稳定页面，避免立即补跑同一失败链。"""
    state = get_state()
    if state != "network_error":
        return True
    log("→ 日常失败链补跑前检测到网络错误；先恢复游戏页面，再启动MAA")
    if not goto_main_menu():
        log("❌ 网络错误恢复后仍未确认主界面；本轮不做无效补跑", "ERROR")
        return False
    log("✅ 网络连接已恢复并确认主界面；允许定向补跑")
    return True


def mode_daily(enabled_tasks=None):
    """每日日常任务"""
    global _LAST_MAA_RUN_LOG
    requested_tasks = set(enabled_tasks or {"StartUp", "Infrast", "Recruit", "Mall", "Award"})
    _RUN_SUMMARY["daily_requested_chains"] = sorted(requested_tasks)
    log("=" * 60)
    log("  场景: 每日日常任务")
    log("=" * 60)
    if enabled_tasks:
        log(f"  定向恢复链: {', '.join(sorted(requested_tasks))}")

    # 二次检测实际端口。main() 已负责 daily 冷启动 MuMu；这里仍需覆盖
    # “MAA 队列正在运行、main 不触碰环境而直接接管”的恢复路径。
    detect_mumu_adb_port()

    # 上一脚本可能退出，但MAA仍在执行Infrast/Recruit/Mall/Award。此时必须
    # 只接管日志等待，禁止触碰游戏、重写配置或再次点击Link Start。
    if _maa_daily_queue_running():
        log("→ 检测到仍在运行的MAA日常队列，接管监控而不重启")
        result = wait_maa_complete(
            timeout=1200, continue_after_chain_error=True, resume_existing=True,
        )
        if result is not True:
            log(f"❌ 接管的MAA日常队列未完整结束: {result}", "ERROR")
            return False
        stamina = get_stamina()
        log(f"当前理智: {stamina}/210")
        return _confirm_daily_chains_complete()

    # 脚本曾在等待器误判后退出，而MAA仍把五条日常全部做完。恢复时先用
    # 同一游戏日(04:00刷新)的完整GUI日志闭环，避免重复跑基建/公招/商店/Award。
    force_daily_rerun = os.environ.get("ARKNIGHTS_FORCE_DAILY_RERUN", "0") == "1"
    if force_daily_rerun:
        log("→ 最终收尾要求刷新日常：忽略本游戏日较早的完成记录，重新执行五条任务链")
    elif _restore_completed_daily_from_gui_log(
        completed_not_before=_DAILY_COMPLETION_NOT_BEFORE,
    ) if enabled_tasks is None else False:
        return _confirm_daily_chains_complete()

    # 1. 检查MuMu是否已在运行
    r = subprocess.run([ADB, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if DEVICE in r.stdout:
        log("✅ ADB已连接(MuMu已在运行)")
    else:
        log("→ 启动MuMu模拟器")
        _run_mumu("control", "-v", MUMU_VM_INDEX, "launch", timeout=30)
        # 等待ADB (每5s轮询, 最多120s; 每次重新检测端口)
        for i in range(24):
            wait(5)
            # 🔴 每次重试前重新检测端口
            detect_mumu_adb_port()
            r = subprocess.run([ADB, "connect", DEVICE], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
            r = subprocess.run([ADB, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if DEVICE in r.stdout:
                log("✅ ADB已连接")
                break
        else:
            log("❌ ADB连接超时", "ERROR")
            return

    # 2. 检查游戏是否已在主界面, 没有则启动
    state = get_state()
    if state == "battle":
        if not _recover_terminal_long_term_battle_for_daily():
            _RUN_SUMMARY["daily_battle_recovery"] = {
                "status": "blocked",
                "reason": "旧战斗缺少安全接管三重证据",
            }
            return False
        # 冷启动已发出，下面沿用原登录/加载等待状态机；再次monkey只会
        # 将刚启动的应用带到前台，不会改变业务目标。
        state = get_state()
    if state == "base_exit_dialog":
        log("→ 日常恢复检测到基建离开确认框，先安全返回主界面")
        if not goto_main_menu():
            log("❌ 无法从基建离开确认框恢复", "ERROR")
            return False
        state = "main_menu"
    if state == "main_menu":
        log("✅ 游戏已在主界面")
    elif state == "base":
        log("✅ 游戏仍在基建内部，交由MAA Infrast直接接管")
    elif state == "story":
        state = _leave_story_before_daily()
        if state == "main_menu":
            log("✅ 最终日常启动前已跳过遗留剧情并返回主界面")
        elif state == "base":
            log("✅ 遗留剧情结束后已在基建内部，交由MAA Infrast接管")
        elif not goto_main_menu():
            log("⚠️ 遗留剧情已处理但未能快速返回主界面，立即交由MAA StartUp接管", "WARN")
    elif state in {
        "chapter_map", "stage_detail", "formation", "terminal_list",
        "act2_select", "chapter_overview", "victory", "reward",
        "operator_page", "annihilation_page", "annihilation_reward_overlay", "task_page",
        "routine_tasks", "depot",
    }:
        # Fight自然结束时通常停在活动地图/关卡详情。游戏已经在前台，不能再次
        # monkey启动后原地等240秒；先走真实图形返回主页，失败时也直接交给
        # MAA StartUp接管，而不是把“未到主页”等同于“游戏尚未启动”。
        log(f"→ 最终日常从现有游戏页面快速交接 (状态: {state})")
        if goto_main_menu():
            log("✅ 最终日常启动前已返回主界面")
        else:
            log("⚠️ 脚本未能快速返回主界面，立即交由MAA StartUp接管", "WARN")
    else:
        log(f"→ 启动游戏 (当前状态: {state})")

        # 🔴 游戏启动重试(捕获stderr, device offline时重试)
        for attempt in range(3):
            detect_mumu_adb_port()  # 重试前重新检测端口
            r = subprocess.run([ADB, "-s", DEVICE, "shell", "monkey", "-p", PKG, "-c",
                            "android.intent.category.LAUNCHER", "1"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            if "error" not in (r.stderr or "").lower() and "offline" not in (r.stderr or "").lower():
                break
            log(f"  ⚠️ 游戏启动失败(第{attempt+1}次): {r.stderr.strip()}")
            wait(3)

        # 等待主界面 (16×15s=240s, 冷启动+网络加载需要足够时间)
        _daily_popup_count = 0  # 配给弹窗处理次数限制(防死循环)
        for i in range(16):
            wait(15)
            try:
                state = get_state()
            except Exception:
                continue
            if state == "main_menu":
                log("✅ 已到主界面")
                break
            # 🔴 处理各种状态
            if state == "home_screen":
                # Android桌面 → 游戏没启动成功! 重新启动
                log(f"  [daily] 检测到桌面, 重新启动游戏...")
                detect_mumu_adb_port()
                subprocess.run([ADB, "-s", DEVICE, "shell", "monkey", "-p", PKG, "-c",
                                "android.intent.category.LAUNCHER", "1"],
                               capture_output=True, timeout=10)
                continue
            if state == "login":
                # 🔴 登录界面 → 点击中间下方黄色菱形(开始唤醒按钮)
                # POS_LOGIN_START=(961,1028), 用户2026-06-29明确要求, 之前误用屏幕中央(960,540)
                tap(*POS_LOGIN_START)
                continue
            if state == "base_exit_dialog":
                if not goto_main_menu():
                    return False
                continue
            if state in ("exit_dialog", "announcement", "network_error"):
                handle_popups()
                continue
            if state == "unknown":
                # 🔴 不确定时用截图确认 (用户2026-06-29要求: 检查核对用图像识别确认)
                # 🔴 优化: "RHODES"匹配"RHODESISLAND"(无空格), 加"服务器"/"泰拉"加载页特征词
                # 🔴 FIX 2026-07-04: 移除通用的"配给"/"龙门币"(主界面也有), 只保留"今日配给"
                # 🔴 FIX 2026-07-04: 添加配给弹窗处理次数限制(最多3次, 防死循环)
                matched, t = confirm_by_screenshot(
                    "daily_unknown",
                    expected_keywords=["RHODES", "罗德岛", "Pharmaceutical",
                                       "清除缓存", "网络检测", "登录", "START", "账号",
                                       "服务器", "泰拉", "鹰角",
                                       "今日配给"])
                if matched:
                    if "今日配给" in t:
                        _daily_popup_count += 1
                        if _daily_popup_count > 3:
                            log(f"  [daily] 配给弹窗已处理{_daily_popup_count}次, 可能是OCR误判, 跳过继续等待主界面...")
                            continue
                        log(f"  [daily] 截图确认: 每日配给弹窗(第{_daily_popup_count}次), 点击关闭...")
                        # 点击弹窗确认按钮关闭 (通常在屏幕中下方)
                        tap(960, 800)
                    elif "登录" in t or "START" in t or "账号" in t:
                        log(f"  [daily] 截图确认: 登录页, 点击黄色菱形进入...")
                        tap(*POS_LOGIN_START)
                    elif any(k in t for k in ["RHODES", "罗德岛", "Pharmaceutical",
                                            "清除缓存", "网络检测", "服务器", "泰拉", "鹰角"]):
                        # 这些词只能证明在加载/品牌画面，不能证明固定START坐标可点击。
                        # 误点会在主界面进入寻访等功能，因此这里只等待状态机变为login。
                        log("  [daily] 截图确认: 加载/品牌页，仅等待，不点击固定坐标")
                    continue
                # 仍未匹配, 保存截图供调试后继续等待
                log(f"  [daily] unknown状态未识别, 已保存截图, 继续等待...")
                continue
        else:
            log("⚠️ 未到主界面(等240s), 尝试继续执行...")
    
    handle_popups()
    
    # 3. MAA日常任务链
    log("→ 执行MAA日常任务链")
    if not run_maa_daily_tasks(enabled_tasks=requested_tasks):
        log("❌ MAA启动失败", "ERROR")
        return
    
    # 4. 等待完成 (严格判据: 必须AllTasksCompleted)
    result = wait_maa_complete(
        timeout=1200,
        continue_after_chain_error=True,
        prestarted_boundary=True,
    )
    if result is True:
        log(f"✅ 日常任务完成 (AllTasksConfirmed)")
    elif result == "maa_completed_with_errors":
        # MAA日常队列会在某个子任务失败后继续执行后续任务。等整队列结束后，
        # 只补跑最后仍为失败态的链，避免把已完成的商店/领奖误报成未执行。
        first_run_log = _get_current_maa_run_log()
        retryable = {"Infrast", "Recruit", "Mall", "Award"}
        failed = [c for c in _failed_taskchains(first_run_log) if c in retryable]
        if failed:
            log(f"→ 日常失败链定向补跑一次: {', '.join(failed)}")
            retry_page_ready = _recover_daily_retry_page()
            if retry_page_ready:
                reload_maa_after_config_switch("日常队列结束，定向补跑失败链")
            retry_log = ""
            try:
                if not retry_page_ready:
                    raise RuntimeError("网络错误页面未恢复")
                with temporary_maa_config(
                    lambda cfg: _set_enabled_tasks(cfg, set(failed)),
                    f"日常失败链补跑: {','.join(failed)}",
                ):
                    if run_maa_daily_tasks(enabled_tasks=set(failed)):
                        retry_result = wait_maa_complete(
                            timeout=900,
                            continue_after_chain_error=True,
                            prestarted_boundary=True,
                        )
                        retry_log = _get_current_maa_run_log()
                        if retry_result is True:
                            log("✅ 日常失败链补跑完成")
                        else:
                            log(f"⚠️ 日常失败链补跑未全部完成: {retry_result}", "WARN")
                    else:
                        log("⚠️ 日常失败链补跑未能启动", "WARN")
            except Exception as e:
                log(f"⚠️ 日常失败链补跑异常: {e}", "WARN")
            finally:
                # 报告必须同时看到首轮已完成项和补跑终态；解析时以每条链最后终态为准。
                _LAST_MAA_RUN_LOG = _join_bounded_indexed_lines(enumerate(
                    (first_run_log + "\n# DAILY RETRY\n" + retry_log).splitlines(
                        keepends=True
                    )
                ))
        else:
            log("⚠️ MAA队列结束但未解析出可补跑的日常失败链", "WARN")
    else:
        log(f"⚠️ 日常任务未确认完成: {result}", "WARN")
    
    stamina = get_stamina()
    log(f"当前理智: {stamina}/210")
    target_ok = _confirm_daily_chains_complete(required=tuple(sorted(requested_tasks)))
    if enabled_tasks is not None and target_ok:
        _LAST_MAA_RUN_LOG = _merge_prior_daily_chain_evidence(_LAST_MAA_RUN_LOG)
        # 能合并本游戏日五链证据时顺便确认；合并不到（例如刚才的 event
        # 报告已占用同名文件）也不能把“指定 Award 已完成”改判成失败。
        all_daily_ok = all(
            _taskchain_status(_LAST_MAA_RUN_LOG, chain)["ok"]
            for chain in ("StartUp", "Infrast", "Recruit", "Mall", "Award")
        )
        if all_daily_ok:
            _confirm_daily_chains_complete()
        _RUN_SUMMARY["daily_targeted_result"] = {
            "requested": sorted(requested_tasks),
            "requested_complete": True,
            "same_day_all_five_confirmed": bool(all_daily_ok),
        }
        return True
    return target_ok
    # 🔴 验证和报告由main()的finally块统一处理


def _confirm_daily_chains_complete(required=("StartUp", "Infrast", "Recruit", "Mall", "Award")):
    """最终日常硬判据：StartUp/Infrast/Recruit/Mall/Award缺一不可。"""
    final_log = _LAST_MAA_RUN_LOG or _get_current_maa_run_log()
    required = tuple(required)
    incomplete = [chain for chain in required if not _taskchain_status(final_log, chain)["ok"]]
    # MAA可能在长时间Infrast期间轮转asst.log，使前面的StartUp/Infrast
    # callback从本轮快照消失。只有GUI日志在最终理智作战边界之后完整记录
    # 五链开始/完成和整队列完成时才补证；缺任一链仍保持失败。
    if incomplete and _restore_completed_daily_from_gui_log(
        completed_not_before=_DAILY_COMPLETION_NOT_BEFORE,
    ):
        final_log = _LAST_MAA_RUN_LOG or _get_current_maa_run_log()
        incomplete = [
            chain for chain in required
            if not _taskchain_status(final_log, chain)["ok"]
        ]
    if incomplete:
        log(f"❌ 最终日常仍未闭环: {', '.join(incomplete)}", "ERROR")
        return False
    if set(required) == {"StartUp", "Infrast", "Recruit", "Mall", "Award"}:
        log("✅ 最终日常五条任务链（含Award）均已确认完成")
    else:
        log(f"✅ 定向日常链已确认完成: {', '.join(required)}")
    return True


def _merge_prior_daily_chain_evidence(current_log):
    """Merge only directly confirmed same-day chains for a targeted recovery.

    This is used after e.g. an Award-only retry.  It does not rerun or invent
    earlier chains: each imported chain must be ``ok`` in today's persisted
    full report, while the retried chain still comes from the current MAA log.
    """
    path = os.path.join(BASE, "outputs", f"daily_report_{datetime.now():%Y-%m-%d}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            prior = json.load(f)
    except (OSError, ValueError, TypeError):
        return current_log
    synthetic = []
    for chain in ("StartUp", "Infrast", "Recruit", "Mall", "Award"):
        state = (prior.get("chain_status") or {}).get(chain) or {}
        if state.get("ok"):
            synthetic.append(f'TaskChainStart {{"taskchain":"{chain}"}}\n')
            synthetic.append(f'TaskChainCompleted {{"taskchain":"{chain}"}}\n')
    if synthetic:
        log("✅ 定向恢复已合并本游戏日既有日常完成证据；未重复执行已完成链")
    return "".join(synthetic) + (current_log or "")

# ============================================================
# 场景模式: 剿灭 (每周状态闭环)
# ============================================================

def _annihilation_week_key(now=None):
    now = now or datetime.now()
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _load_annihilation_progress():
    if not os.path.exists(ANNIHILATION_PROGRESS_FILE):
        return {"weeks": {}}
    try:
        with open(ANNIHILATION_PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"weeks": {}}
        data.setdefault("weeks", {})
        return data
    except Exception:
        return {"weeks": {}}


def _save_annihilation_progress(status, earned=None, maximum=None, detail="", now=None):
    now = now or datetime.now()
    key = _annihilation_week_key(now)
    data = _load_annihilation_progress()
    record = {
        "status": status,
        "updated_at": now.isoformat(timespec="seconds"),
        "detail": detail,
    }
    if earned is not None:
        record["jade_earned"] = int(earned)
    if maximum is not None:
        record["jade_max"] = int(maximum)
    data.setdefault("weeks", {})[key] = record
    data["current_week"] = key
    _atomic_write_json(ANNIHILATION_PROGRESS_FILE, data)
    return record


def _parse_annihilation_weekly_progress(log_text):
    matches = re.findall(r'annihilation_weekly_process"\s*:\s*\[(\d+)\s*,\s*(\d+)\]', log_text or "")
    if not matches:
        return None
    earned, maximum = map(int, matches[-1])
    return earned, maximum


def _read_terminal_annihilation_weekly_progress():
    """按玩家查看周任务的方式读取合成玉进度。

    首页有卡片时先直接读取；卡片在达到周上限后会消失，因此必须继续
    点击终端底栏的剿灭入口，到剿灭页面读取“每周报酬/合成玉”数字。
    """
    if not goto_terminal_main():
        log("⚠️ 剿灭周进度预检无法进入终端，改由MAA执行链核对", "WARN")
        return None
    try:
        path = shot("annihilation_weekly_precheck")
        items = ocr(path)
        # 1920x1080终端实机：剿灭合成玉卡位于右侧TO-DO LIST上半区。
        # 限定ROI并同时要求“合成玉”语义，避免把其他任务计数误当周上限。
        roi_text = " ".join(
            str(text) for text, x, y in items
            if 1380 <= x <= 1910 and 100 <= y <= 360
        )
        if "合成玉" in roi_text:
            matches = re.findall(r"(?<!\d)(\d{1,4})\s*/\s*(1800)(?!\d)", roi_text)
            if matches:
                earned, maximum = map(int, matches[-1])
                log(f"✅ 终端剿灭卡直接读数: 合成玉{earned}/{maximum}")
                return earned, maximum
            log(f"⚠️ 终端剿灭卡未读到周进度数字: {roi_text[:120]}", "WARN")
        else:
            log(
                "ℹ️ 终端首页没有剿灭周任务卡，按玩家路径进入剿灭页面复核"
            )

        tap(*POS_TERMINAL_ROUTINE)
        wait(5)
        for attempt in range(3):
            page = shot(f"annihilation_weekly_page_{attempt + 1}")
            page_items = ocr(page)
            page_text = " ".join(str(text) for text, _, _ in page_items)
            # OCR偶尔把数字0识别为字母O；只在周上限固定为1800的局部表达中
            # 做窄范围兼容，避免污染其他页面数字。
            normalized = re.sub(r"(?<=\d)[oO](?=\d)", "0", page_text)
            normalized = re.sub(r"(?<=/)[oO](?=\d)", "0", normalized)
            matches = re.findall(
                r"(?<!\d)(\d{1,4})\s*/\s*(1800)(?!\d)", normalized
            )
            page_semantics = any(
                marker in page_text
                for marker in ("剿灭委托", "每周报酬", "作战进度", "委托剩余", "合成玉")
            )
            if page_semantics and matches:
                earned, maximum = map(int, matches[-1])
                log(f"✅ 常态事务直接读数: 合成玉{earned}/{maximum}")
                return earned, maximum
            if attempt < 2:
                wait(3)

        log(
            f"⚠️ 已进入常态事务但未读到剿灭周进度: {page_text[:160]}",
            "WARN",
        )
        return None
    finally:
        if not goto_main_menu():
            log("⚠️ 剿灭周进度预检后未能确认回到主界面", "WARN")


def annihilation_due(now=None):
    """新的一周或本周未被直接证据确认完成时，完整流程都优先尝试剿灭。"""
    key = _annihilation_week_key(now)
    record = _load_annihilation_progress().get("weeks", {}).get(key, {})
    return record.get("status") != "completed"


def mode_annihilation(force=False, times=None):
    """按本周进度优先完成剿灭，而不是只在周一机械执行。

    临时配置MAA: 仅启用FightTask剿灭模式, 禁用其他任务 → Link Start → 恢复配置
    """
    requested_times = max(1, int(times or ANNIHILATION_AUTO_MAX_RUNS))
    log("=" * 60)
    log("  场景: 每周剿灭闭环 (未确认完成则优先)")
    log("=" * 60)
    _RUN_SUMMARY["annihilation"] = {
        "week": _annihilation_week_key(),
        "requested_times": requested_times,
        "status": "running",
    }

    if not force and not annihilation_due():
        log("✅ 本周剿灭已有完成证据，跳过重复执行")
        _RUN_SUMMARY["annihilation"]["status"] = "skipped_weekly_complete"
        return True

    # 🔴 2026-06-29修复: mode_annihilation需要自己启动MuMu和游戏
    # (之前只调goto_main_menu, 但cleanup后MuMu已关)
    detect_mumu_adb_port()

    # 1. 启动MuMu
    r = subprocess.run([ADB, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if DEVICE in r.stdout:
        log("✅ ADB已连接(MuMu已在运行)")
    else:
        log("→ 启动MuMu模拟器")
        _run_mumu("control", "-v", MUMU_VM_INDEX, "launch", timeout=30)
        for i in range(24):
            wait(5)
            detect_mumu_adb_port()
            r = subprocess.run([ADB, "connect", DEVICE], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
            r = subprocess.run([ADB, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if DEVICE in r.stdout:
                log("✅ ADB已连接")
                break
        else:
            log("❌ ADB连接超时", "ERROR")
            _RUN_SUMMARY["annihilation"].update({
                "status": "failed",
                "detail": "ADB连接超时",
            })
            return False

    # 2. 启动游戏到主界面
    state = get_state()
    recoverable_pages = {
        "terminal_list", "act2_select", "chapter_overview", "chapter_map",
        "stage_detail", "formation", "task_page", "routine_tasks", "reward", "victory",
        "operator_page", "annihilation_page", "annihilation_reward_overlay",
        "quick_nav_overlay", "base", "base_exit_dialog",
    }
    if state in recoverable_pages:
        log(f"→ 剿灭从现有游戏页面快速交接 (状态: {state})")
        if not goto_main_menu():
            log(f"❌ 无法从{state}恢复到主界面，未开始剿灭", "ERROR")
            _RUN_SUMMARY["annihilation"].update({
                "status": "failed",
                "detail": f"无法从{state}恢复到主界面，未开始剿灭",
            })
            _save_annihilation_progress(
                "failed", detail=f"无法从{state}恢复到主界面，未开始剿灭"
            )
            return False
        state = "main_menu"

    if state == "main_menu":
        log("✅ 游戏已在主界面")
    else:
        log(f"→ 启动游戏 (当前状态: {state})")
        for attempt in range(3):
            detect_mumu_adb_port()
            r = subprocess.run([ADB, "-s", DEVICE, "shell", "monkey", "-p", PKG, "-c",
                            "android.intent.category.LAUNCHER", "1"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            if "error" not in (r.stderr or "").lower() and "offline" not in (r.stderr or "").lower():
                break
            log(f"  ⚠️ 游戏启动失败(第{attempt+1}次): {r.stderr.strip()}")
            wait(3)

        # 等待游戏到主界面 (最多180s, 用截图确认)
        for i in range(60):
            wait(3)
            state = get_state()
            if state == "main_menu":
                log("✅ 已到主界面")
                break
            if state == "announcement":
                # 公告是正常登录链的一部分，不是unknown，也不能点黄色登录菱形。
                if not _dismiss_announcement_overlay():
                    log("  ⚠️ 检测到公告但语义复核失败，等待下一帧", "WARN")
                continue
            if state == "login":
                tap(*POS_LOGIN_START)
            elif state == "unknown":
                # 截图确认加载页
                matched, t = confirm_by_screenshot(
                    "anni_unknown",
                    expected_keywords=["RHODES", "罗德岛", "Pharmaceutical",
                                       "清除缓存", "网络检测", "登录", "START", "账号",
                                       "服务器", "泰拉", "鹰角"])
                if matched and any(k in t for k in ["RHODES", "罗德岛", "Pharmaceutical",
                                                    "清除缓存", "网络检测", "服务器", "泰拉", "鹰角"]):
                    log("  [截图确认] 游戏加载页, 点击黄色菱形继续...")
                    tap(*POS_LOGIN_START)
                elif matched and ("登录" in t or "START" in t or "账号" in t):
                    log("  [截图确认] 登录页, 点击黄色菱形进入...")
                    tap(*POS_LOGIN_START)
        else:
            log("❌ 游戏启动超时", "ERROR")
            _RUN_SUMMARY["annihilation"].update({
                "status": "failed",
                "detail": "登录/公告启动链超时，未开始剿灭",
            })
            _save_annihilation_progress(
                "failed", detail="登录/公告启动链超时，未开始剿灭"
            )
            return False

    if not goto_main_menu():
        log("❌ 无法回主界面, 跳过剿灭", "ERROR")
        _RUN_SUMMARY["annihilation"].update({
            "status": "failed",
            "detail": "无法回到主界面，未开始剿灭",
        })
        _save_annihilation_progress("failed", detail="无法回到主界面，未开始剿灭")
        return False

    # 先按玩家真实查看路径读取终端右侧周奖励卡。已满时无需再让MAA
    # 启动一个空Fight队列；未满或OCR不确定时才交给MAA继续处理。
    visual_weekly = _read_terminal_annihilation_weekly_progress()
    if visual_weekly:
        earned, maximum = visual_weekly
        _RUN_SUMMARY["annihilation"].update({
            "jade_earned": earned,
            "jade_max": maximum,
            "evidence": "终端右侧剿灭合成玉卡图形OCR",
        })
        if maximum > 0 and earned >= maximum:
            _save_annihilation_progress(
                "completed", earned, maximum, "终端剿灭卡图形OCR确认达到周上限"
            )
            _RUN_SUMMARY["annihilation"]["status"] = "completed_weekly"
            log(f"✅ 剿灭本周闭环：合成玉{earned}/{maximum}（终端画面）")
            return True
        log(f"→ 本周剿灭尚未满: 合成玉{earned}/{maximum}；继续交给MAA补齐")

    # 任务边界重启空闲MAA，确保下面写入的剿灭配置会在冷启动时加载。
    reload_maa_after_config_switch("切换到剿灭Fight")

    # 🔴 临时配置MAA: 只启用Fight(剿灭模式), 禁用其他任务
    config_path = os.path.join(MAA_CONFIG, "gui.new.json")
    backup = None
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            backup = json.load(f)
        cfg = json.loads(json.dumps(backup))  # 深拷贝
        tasks = cfg["Configurations"]["Default"]["TaskQueue"]
        for t in tasks:
            tt = t.get("TaskType", "")
            if tt == "Fight":
                t["IsEnable"] = True
                # 🔴 剿灭配置 (2026-06-29修正):
                # StagePlan=[""]打的是"上一战"(普通关卡), 不是剿灭!
                # StagePlan=["Annihilation"]才是打当期剿灭 (GitHub issue #17208证实)
                # UseCustomAnnihilation=false让MAA自动选择当期剿灭关卡
                t["StagePlan"] = ["Annihilation"]
                t["UseCustomAnnihilation"] = False
                t["AnnihilationStage"] = "Annihilation"
                t["UseMedicine"] = False
                t["UseStone"] = False
                t["EnableTimesLimit"] = True
                t["TimesLimit"] = requested_times
            else:
                t["IsEnable"] = False
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log("→ MAA配置: 仅启用Fight剿灭模式")
    except Exception as e:
        log(f"❌ 配置MAA剿灭失败: {e}", "ERROR")
        _RUN_SUMMARY["annihilation"].update({
            "status": "failed",
            "detail": f"配置MAA剿灭失败: {e}",
        })
        _save_annihilation_progress("failed", detail=f"配置MAA剿灭失败: {e}")
        return False

    # 执行剿灭
    log("→ 执行剿灭任务 (Link Start)")
    annihilation_result = False
    if not run_maa_daily_tasks(enabled_tasks={"Fight"}):
        log("❌ MAA启动失败", "ERROR")
    else:
        annihilation_result = wait_maa_complete(
            timeout=max(900, requested_times * 600), prestarted_boundary=True,
        )

    # 🔴 恢复MAA配置 (Fight重新禁用, 日常任务恢复启用)
    if backup:
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(backup, f, ensure_ascii=False, indent=2)
            log("→ MAA配置已恢复")
        except Exception as e:
            log(f"⚠️ 恢复MAA配置失败: {e}", "WARN")

    maa_run_log = _get_current_maa_run_log()
    weekly = _parse_annihilation_weekly_progress(maa_run_log)
    maa_navigation_error = (
        ("TaskChainError" in maa_run_log or "SubTaskError" in maa_run_log)
        and '"taskchain":"Fight"' in maa_run_log
        and "Annihilation" in maa_run_log
    )
    if maa_navigation_error:
        _RUN_SUMMARY["annihilation"]["maa_navigation_error"] = True
        log(
            "⚠️ MAA剿灭链内部出现导航/子任务错误；后续的TaskChainCompleted"
            "仅表示队列收尾，不能当作剿灭完成证据",
            "WARN",
        )
    if weekly:
        earned, maximum = weekly
        _RUN_SUMMARY["annihilation"].update({"jade_earned": earned, "jade_max": maximum})
        if maximum > 0 and earned >= maximum:
            _save_annihilation_progress("completed", earned, maximum, "MAA本轮日志确认达到周上限")
            _RUN_SUMMARY["annihilation"]["status"] = "completed_weekly"
            log(f"✅ 剿灭本周闭环：合成玉{earned}/{maximum}")
            return True
        _save_annihilation_progress("incomplete", earned, maximum, "本轮结束但尚未达到周上限")
        _RUN_SUMMARY["annihilation"]["status"] = "incomplete_weekly"
        log(f"❌ 剿灭本周仍未完成：合成玉{earned}/{maximum}", "ERROR")
        return False

    # MAA日志并不保证回传周进度，而且“子任务失败→队列完成”会制造假成功。
    # 战斗链结束后重新按玩家路径进入剿灭页，以游戏画面的周报酬数字定案。
    visual_after = _read_terminal_annihilation_weekly_progress()
    if visual_after:
        earned, maximum = visual_after
        _RUN_SUMMARY["annihilation"].update({
            "jade_earned": earned,
            "jade_max": maximum,
            "evidence": "MAA结束后剿灭页面图形OCR",
        })
        if maximum > 0 and earned >= maximum:
            _save_annihilation_progress(
                "completed", earned, maximum, "MAA结束后剿灭页面确认达到周上限"
            )
            _RUN_SUMMARY["annihilation"]["status"] = "completed_weekly"
            log(f"✅ 剿灭本周闭环：合成玉{earned}/{maximum}（游戏页面复核）")
            return True
        _save_annihilation_progress(
            "incomplete", earned, maximum, "游戏页面复核仍未达到周上限"
        )
        _RUN_SUMMARY["annihilation"]["status"] = "incomplete_weekly"
        log(f"❌ 剿灭本周仍未完成：合成玉{earned}/{maximum}", "ERROR")
        return False

    if annihilation_result is True:
        detail = "MAA任务结束但日志和游戏页面均缺少本周合成玉进度"
        if maa_navigation_error:
            detail = "MAA剿灭导航/子任务失败，且游戏页面未能读取周进度"
        _save_annihilation_progress("unconfirmed", detail=detail)
        _RUN_SUMMARY["annihilation"]["status"] = "unconfirmed_weekly"
        _RUN_SUMMARY["annihilation"]["detail"] = detail
        log(f"⚠️ {detail}；保留为待办，不允许用队列完成冒充周目标完成", "WARN")
        return False
    _RUN_SUMMARY["annihilation"]["status"] = "failed"
    _RUN_SUMMARY["annihilation"]["detail"] = str(annihilation_result)
    _save_annihilation_progress("failed", detail=str(annihilation_result))
    log(f"❌ 剿灭未确认完成: {annihilation_result}", "ERROR")
    return False

# ============================================================
# 场景模式: 资源关刷取
# ============================================================

def mode_resource(stage_code="AP-5", times=5):
    """资源关刷取"""
    log("=" * 60)
    log(f"  场景: 资源关 {stage_code} x{times}")
    log("=" * 60)
    
    stage_info = RESOURCE_STAGES.get(stage_code)
    if not stage_info:
        log(f"❌ 未知资源关: {stage_code}", "ERROR")
        return
    
    cost = stage_info["cost"]
    
    if not goto_main_menu():
        return

    reload_maa_after_config_switch(f"切换到资源关{stage_code}")
    
    try:
        with temporary_maa_config(
            lambda cfg: _configure_fight(cfg, stage_code, times),
            f"仅Fight {stage_code}，最多{times}次",
        ):
            if not run_maa_daily_tasks(enabled_tasks={"Fight"}):
                log("❌ MAA战斗任务启动失败", "ERROR")
                return False
            result = wait_maa_complete(timeout=times * 120 + 300, prestarted_boundary=True)
            if result is not True:
                log(f"❌ 资源关任务未确认完成: {result}", "ERROR")
                return False
            _save_fight_handoff(stage_code)
    except Exception as e:
        log(f"❌ 配置或执行资源关失败: {e}", "ERROR")
        return False

    log(f"✅ 资源关{stage_code}已按上限{times}次执行完成")
    return True


def mode_orundum_rock_fallback():
    """无活动且主线/隐藏关全闭环后，用1-7为搓玉补充固源岩。"""
    if not _plan_allows("orundum_rock_farm"):
        _record_decision_request(
            "1-7固源岩搓玉兜底",
            "本轮执行契约未授权搓玉固源岩兜底",
            ["G-AUTH-001", "G-MAINLINE-001", "G-DAILY-001"],
        )
        return False
    summary = _RUN_SUMMARY.setdefault("remaining_sanity_use", {})
    summary.update({
        "status": "running",
        "stage": "1-7",
        "purpose": "搓合成玉所需固源岩",
        "medicine": False,
        "originium": False,
    })
    if not goto_main_menu():
        summary.update({"status": "failed", "detail": "无法确认主界面"})
        return False
    reload_maa_after_config_switch("切换到1-7固源岩搓玉兜底")
    try:
        with temporary_maa_config(
            lambda cfg: _configure_fight(cfg, "1-7", 99),
            "仅Fight 1-7，连续代理至理智不足",
        ):
            if not run_maa_daily_tasks(enabled_tasks={"Fight"}):
                summary.update({"status": "failed", "detail": "MAA 1-7启动失败"})
                return False
            result = wait_maa_complete(
                timeout=7200, prestarted_boundary=True, active_battle_extension=3600
            )
            if result is not True:
                summary.update({
                    "status": "failed",
                    "detail": f"MAA 1-7未确认完成: {result}",
                })
                return False
            maa_text = _get_current_maa_run_log()
            _save_fight_handoff("1-7", maa_text=maa_text)
            evidence = _parse_fight_times_evidence(maa_text) or {}
    except Exception as exc:
        summary.update({"status": "failed", "detail": str(exc)})
        log(f"❌ 1-7固源岩兜底失败: {exc}", "ERROR")
        return False
    summary.update({
        "status": "completed",
        "detail": "MAA已在1-7连续代理至当前理智不足",
        "actual_runs": int(evidence.get("runs", 0) or 0),
        "sanity_consumed": int(evidence.get("sanity_cost", 0) or 0),
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    })
    log(
        "✅ 1-7固源岩兜底结束: "
        f"真实完成{summary['actual_runs']}次，日志消耗{summary['sanity_consumed']}理智"
    )
    return True


def mode_depot_resource_fallback():
    """主线全闭环且无活动时，交给MAA库存保持耗尽剩余理智。"""
    if not _plan_allows("depot_maintain"):
        _record_decision_request(
            "芯片/采购凭证库存保持",
            "本轮执行契约未授权库存保持资源兜底",
            ["G-AUTH-001", "G-MAINLINE-001"],
        )
        return False
    summary = _RUN_SUMMARY.setdefault("remaining_sanity_use", {})
    summary.update({
        "status": "running",
        "stage": "芯片不足20优先，否则AP-5采购凭证",
        "inventory_refresh": "MAA Depot",
        "medicine": False,
        "originium": False,
    })
    if not goto_main_menu():
        summary.update({"status": "failed", "detail": "无法确认主界面"})
        return False

    reload_maa_after_config_switch("切换到库存保持资源兜底")
    try:
        with temporary_maa_config(
            _configure_depot_resource_fallback,
            "仅库存保持：芯片/芯片组各20→AP-5采购凭证",
        ):
            if not run_maa_daily_tasks(enabled_tasks={"DepotMaintain"}):
                summary.update({"status": "failed", "detail": "MAA库存保持启动失败"})
                return False
            result = wait_maa_complete(timeout=3600, prestarted_boundary=True)
            if result is not True:
                summary.update({
                    "status": "failed",
                    "detail": f"MAA库存保持未确认完成: {result}",
                })
                return False
            maa_text = _get_current_maa_run_log()
            _save_fight_handoff("库存保持：芯片<20→AP-5", maa_text=maa_text)
    except Exception as exc:
        summary.update({"status": "failed", "detail": str(exc)})
        log(f"❌ 库存保持资源兜底失败: {exc}", "ERROR")
        return False

    summary.update({
        "status": "completed",
        "detail": "MAA已刷新仓库并按计划执行到理智不足或目标满足",
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    })
    log("✅ 库存保持已结束：芯片不足20优先，剩余理智用于AP-5采购凭证")
    return True
    return True

# ============================================================
# 场景模式: 活动刷取
# ============================================================

def _load_event_progress():
    if not os.path.exists(EVENT_PROGRESS_FILE):
        return {"events": {}}
    try:
        with open(EVENT_PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"events": {}}


def _event_attempted_jobs(event_name, stage, mode):
    """Return only jobs which actually entered the stage's battle retry chain."""
    event_state = (_load_event_progress().get("events", {}).get(event_name, {}) or {})
    stage_state = (event_state.get("stages", {}).get(stage, {}) or {})
    mode_state = ((stage_state.get("modes") or {}).get(mode) or {})
    jobs = [str(value) for value in (mode_state.get("attempted_jobs") or []) if value]
    # Backfill only records written before attempted_jobs became a structured
    # field.  A modern failure detail may mention a downloaded job that never
    # reached MAA/formation and therefore must not consume the retry budget.
    if "attempted_jobs" not in mode_state:
        jobs.extend(re.findall(r"[A-Za-z0-9_-]+\.json", str(mode_state.get("detail") or "")))
    # 兼容旧版错误落账：自动编队缺人发生在进入战斗之前，不能占用用户授权
    # 的真实作业战败预算。该文件仍由 _event_incompatible_jobs 保留为排除项。
    if mode_state.get("status") == "job_incompatible":
        rejected = {
            os.path.basename(value)
            for value in re.findall(
                r"[A-Za-z0-9_-]+\.json", str(mode_state.get("detail") or "")
            )
        }
        jobs = [value for value in jobs if os.path.basename(value) not in rejected]
    return list(dict.fromkeys(jobs))


def _event_incompatible_jobs(event_name, stage, mode):
    """Return jobs rejected before battle because the account cannot form them.

    作业的干员、技能、模组等账号前置条件不随普通/突袭模式变化。旧逻辑
    只读取当前模式，导致普通模式已经明确不兼容的作业在突袭中又被加载
    一次。这里合并同一关卡全部模式的前置排除记录，避免重复空等与重复
    点击；真实进入过战斗的作业仍由 ``_event_attempted_jobs`` 分模式记录。
    """
    event_state = (_load_event_progress().get("events", {}).get(event_name, {}) or {})
    stage_state = (event_state.get("stages", {}).get(stage, {}) or {})
    jobs = []
    modes = stage_state.get("modes") or {}
    for mode_name, mode_state in modes.items():
        if mode_name not in {"normal", "challenge", mode}:
            continue
        jobs.extend(
            str(value) for value in (mode_state.get("incompatible_jobs") or []) if value
        )
        if mode_state.get("status") == "job_incompatible":
            jobs.extend(
                re.findall(
                    r"[A-Za-z0-9_-]+\.json",
                    str(mode_state.get("detail") or ""),
                )
            )
    return list(dict.fromkeys(jobs))


def _event_successful_normal_job(event_name, stage):
    """Resolve the Copilot job that last proved the normal mode clear.

    Event challenge mode normally shares the same map and timeline with normal
    mode.  A job that has already completed normal mode is therefore the first
    challenge candidate; a missing separately-labelled challenge job is not a
    valid reason to defer the stage.
    """
    event_state = (_load_event_progress().get("events", {}).get(event_name, {}) or {})
    stage_state = (event_state.get("stages", {}).get(stage, {}) or {})
    normal_state = ((stage_state.get("modes") or {}).get("normal") or {})
    if normal_state.get("status") != "cleared":
        return None
    candidate = str(normal_state.get("successful_job") or "").strip()
    if not candidate:
        attempted = [
            str(value) for value in (normal_state.get("attempted_jobs") or []) if value
        ]
        # Attempts are appended in execution order and the loop exits on the
        # first verified clear, so the last attempted job is the successful one.
        candidate = attempted[-1] if attempted else ""
    return _resolve_copilot_job_basename(candidate) if candidate else None


def _expire_closed_event_progress(now=None, persist=True):
    """把已结束活动与历史刷取明确标为过期，避免旧Fight污染今日报告。"""
    now = now or datetime.now()
    data = _load_event_progress()
    changed = False
    configured = {event["name"]: event for event in ACTIVE_EVENTS}
    for event_name, event_state in (data.get("events", {}) or {}).items():
        config = configured.get(event_name)
        if not config or now < datetime.fromisoformat(config["end"]):
            continue
        if event_state.get("lifecycle_status") != "expired":
            event_state["lifecycle_status"] = "expired"
            event_state["expired_at"] = config["end"]
            changed = True
        farm = event_state.get("farm") or {}
        if farm and farm.get("status") != "expired":
            farm["historical_status"] = farm.get("status")
            farm["status"] = "expired"
            farm["expired_at"] = config["end"]
            changed = True
    if changed:
        data["last_update"] = now.isoformat(timespec="seconds")
        if persist:
            _atomic_write_json(EVENT_PROGRESS_FILE, data)
    return data


def _update_event_progress(
    event_name,
    stage,
    status,
    detail="",
    mode=None,
    *,
    record_attempt=True,
    reset_attempted_jobs=False,
    discard_attempt="",
    record_incompatible_job="",
):
    data = _load_event_progress()
    event = data.setdefault("events", {}).setdefault(event_name, {"stages": {}})
    stages = event.setdefault("stages", {})
    now = datetime.now().isoformat(timespec="seconds")
    if mode:
        stage_state = stages.setdefault(stage, {"modes": {}})
        modes = stage_state.setdefault("modes", {})
        previous = modes.get(mode) or {}
        attempted_jobs = [] if reset_attempted_jobs else list(previous.get("attempted_jobs") or [])
        incompatible_jobs = list(previous.get("incompatible_jobs") or [])
        # 旧版曾把“自动编队缺少干员”误写进真实战斗作业列表。迁移必须
        # 发生在统一写入口，而不能只在读取辅助函数里临时过滤；否则下一次
        # 成功/失败落账时会把旧污染列表原样写回，继续错误占用重试额度。
        if previous.get("status") == "job_incompatible":
            legacy_incompatible = re.findall(
                r"[A-Za-z0-9_-]+\.json", str(previous.get("detail") or "")
            )
            incompatible_jobs.extend(legacy_incompatible)
            rejected_basenames = {
                os.path.basename(value) for value in legacy_incompatible
            }
            attempted_jobs = [
                value for value in attempted_jobs
                if os.path.basename(str(value)) not in rejected_basenames
            ]
        if discard_attempt:
            discarded = os.path.basename(str(discard_attempt))
            attempted_jobs = [
                value for value in attempted_jobs
                if os.path.basename(str(value)) != discarded
            ]
        if record_incompatible_job:
            incompatible_jobs.append(os.path.basename(str(record_incompatible_job)))
        if record_attempt:
            attempted_jobs.extend(re.findall(r"[A-Za-z0-9_-]+\.json", str(detail or "")))
        successful_job = str(previous.get("successful_job") or "").strip()
        detail_jobs = re.findall(r"[A-Za-z0-9_-]+\.json", str(detail or ""))
        if status == "cleared" and detail_jobs:
            successful_job = detail_jobs[-1]
        modes[mode] = {
            "status": status,
            "detail": detail,
            "updated_at": now,
            "attempted_jobs": list(dict.fromkeys(attempted_jobs)),
        }
        if incompatible_jobs:
            modes[mode]["incompatible_jobs"] = list(dict.fromkeys(incompatible_jobs))
        if successful_job:
            modes[mode]["successful_job"] = successful_job
        configured_event = _configured_event_from_name(event_name)
        stage_config = next(
            (
                item for item in (configured_event or {}).get("stages", [])
                if item.get("display") == stage
            ),
            {},
        )
        required_modes = _event_stage_modes(configured_event, stage_config)
        all_required_cleared = all(
            (modes.get(name) or {}).get("status") == "cleared"
            for name in required_modes
        )
        stage_state.update({
            "status": "cleared" if all_required_cleared else (
                status if status not in ("cleared", "already_cleared") else "partial"
            ),
            "detail": (
                "、".join("普通" if name == "normal" else "突袭" for name in required_modes)
                + "均完成"
            ) if all_required_cleared else detail,
            "updated_at": now,
        })
    else:
        stages[stage] = {"status": status, "detail": detail, "updated_at": now}
    data["last_update"] = datetime.now().isoformat(timespec="seconds")
    _atomic_write_json(EVENT_PROGRESS_FILE, data)
    run_event = _RUN_SUMMARY.setdefault("event", {"name": event_name, "stages": {}})
    run_stages = run_event.setdefault("stages", {})
    if mode:
        persisted = stages[stage]
        run_stages[stage] = deepcopy(persisted)
    else:
        run_stages[stage] = {"status": status, "detail": detail}


def _load_event_checkpoint_hint(event):
    """加载历史活动记录供报告参考；是否完成仍由本轮详情页决定。"""
    event_state = (_load_event_progress().get("events", {}).get(event["name"], {}) or {})
    stages = event_state.get("stages", {}) or {}
    all_historically_cleared = True
    for stage in event.get("stages", []):
        state = stages.get(stage["display"], {}) or {}
        modes = state.get("modes", {}) or {}
        if state.get("status") != "cleared" or any(
            (modes.get(mode) or {}).get("status") != "cleared"
            for mode in _event_stage_modes(event, stage)
        ):
            all_historically_cleared = False
    run_event = _RUN_SUMMARY.setdefault("event", {"name": event["name"], "stages": {}})
    run_event["checkpoint_hint"] = {
        "status": (
            "historically_complete" if all_historically_cleared else "historically_partial"
        ),
        "detail": "历史记录仅作待办线索；本轮仍必须逐关打开详情页实机复核",
        "historical_stages": deepcopy(stages),
    }
    return all_historically_cleared


def _event_mode_has_trusted_clear_evidence(event_name, stage_name, mode):
    """仅信任已由真实图形/战斗闭环写入的活动完成记录。

    旧版只有 ``status=cleared`` 的进度仍会进入详情页复核；带有战前徽记、
    战后结算+地图徽记或预算耗尽后的当前徽记证据，才允许在同一活动后续
    运行中直接跳过。这样既避免进度文件误报，也不再每天全量打开已验证
    关卡。
    """
    event_state = (_load_event_progress().get("events", {}).get(event_name, {}) or {})
    stage_state = (event_state.get("stages", {}).get(stage_name, {}) or {})
    mode_state = ((stage_state.get("modes") or {}).get(mode) or {})
    if mode_state.get("status") != "cleared":
        return False
    detail = str(mode_state.get("detail") or "")
    evidence_markers = (
        "战前详情前三枚青色徽记确认普通三星",
        "战前详情第四枚白色徽记确认突袭完成",
        "MAA/结算 + 地图三星",
        "当前详情徽记修订为已完成",
    )
    return any(marker in detail for marker in evidence_markers)


def _save_event_farm_checkpoint(
    event, runs, sanity_remaining=None, detail="", sanity_consumed=None,
    series_batches=None,
):
    data = _load_event_progress()
    event_state = data.setdefault("events", {}).setdefault(event["name"], {"stages": {}})
    if sanity_consumed is None and runs:
        sanity_consumed = int(runs) * int(event.get("farm_cost", 0) or 0)
    farm = {
        "stage": event["farm_stage"],
        "status": "completed",
        "runs": int(runs or 0),
        "sanity_remaining": sanity_remaining,
        "sanity_consumed": sanity_consumed,
        "series_batches": list(series_batches or []),
        "detail": detail,
        "game_day": _game_day_key(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    event_state["farm"] = farm
    data["last_update"] = datetime.now().isoformat(timespec="seconds")
    _atomic_write_json(EVENT_PROGRESS_FILE, data)
    _RUN_SUMMARY.setdefault("event", {"name": event["name"], "stages": {}})["farm"] = {
        "stage": event["farm_stage"],
        "requested_runs": 99,
        "series": "AUTO",
        "status": "completed",
        "actual_runs": farm["runs"],
        "sanity_remaining": sanity_remaining,
        "sanity_consumed": sanity_consumed,
        "series_batches": list(series_batches or []),
        "detail": detail,
    }
    return farm


def _validate_stamina_ocr_against_event_checkpoint(value, now=None):
    """Reject or repair an impossible leading digit in the final sanity OCR.

    After the completed event Fight checkpoint, the full workflow performs no
    more stamina-consuming or stamina-restoring action.  The balance can only
    rise slowly through passive regeneration.  Some home-screen themes make
    OCR join the nearby decoration to ``14/210`` and return ``114``; preserve
    the screenshot read only when it is compatible with that direct Fight
    checkpoint.
    """
    now = now or datetime.now()
    try:
        event = get_active_event(now)
        farm = (
            (_load_event_progress().get("events", {}).get(event["name"], {}) or {})
            .get("farm", {}) or {}
        ) if event else {}
        anchor = farm.get("sanity_remaining")
        updated_at = datetime.fromisoformat(str(farm.get("updated_at") or ""))
        if (
            not isinstance(anchor, int)
            or farm.get("game_day") != _game_day_key(now)
            or _game_day_key(updated_at) != _game_day_key(now)
        ):
            return value
        elapsed = max(0.0, (now - updated_at).total_seconds())
        # One sanity normally regenerates every six minutes.  Two points of
        # tolerance cover checkpoint/screenshot timing at interval boundaries.
        plausible_max = min(210, anchor + int(elapsed // 360) + 2)
        if anchor <= value <= plausible_max:
            return value
        digits = str(value)
        for index in range(1, len(digits)):
            candidate = int(digits[index:])
            if anchor <= candidate <= plausible_max:
                log(
                    f"  [理智] OCR读数{value}/210与Fight结算{anchor}/210冲突，"
                    f"按同屏比例去除误识别前导位后采用{candidate}/210",
                    "WARN",
                )
                return candidate
        log(
            f"  [理智] OCR读数{value}/210与Fight结算{anchor}/210及自然恢复上限"
            f"{plausible_max}/210冲突，拒绝写入",
            "WARN",
        )
        return None
    except Exception:
        return value


def _parse_completed_event_farm_gui_log(text, event, now=None):
    """从当天MAA GUI日志恢复被脚本中断前已完成的活动连续代理证据。"""
    now = now or datetime.now()
    starts = [m.start() for m in re.finditer(r"开始任务: 理智作战", text or "")]
    if not starts:
        return None
    line_start = (text or "").rfind("\n", 0, starts[-1]) + 1
    segment = (text or "")[line_start:]
    queue_end = segment.find("任务已全部完成")
    if queue_end >= 0:
        line_end = segment.find("\n", queue_end)
        segment = segment if line_end < 0 else segment[:line_end + 1]
    stamp = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", segment)
    if not stamp or "Completed Task Chain: Fight" not in segment:
        return None
    try:
        started_at = datetime.fromisoformat(stamp.group(1))
        age_seconds = (now - started_at).total_seconds()
        if age_seconds < 0 or age_seconds > 12 * 3600 or _game_day_key(started_at) != _game_day_key(now):
            return None
    except ValueError:
        return None
    internal = next(
        (s.get("internal") for s in event.get("stages", []) if s.get("display") == event["farm_stage"]),
        "",
    )
    if internal and f'"stageId":"{internal}"' not in segment:
        return None
    sanity_matches = re.findall(r"理智:\s*(\d+)\s*/\s*210", segment)
    if not sanity_matches:
        return None
    sanity = int(sanity_matches[-1])
    if sanity >= int(event["farm_cost"]):
        return None
    # GUI中的“当前次数”是每一批连续代理的批次数，不是整条Fight任务累计值。
    # 例如6连后剩84理智，再执行4连时日志依次写6、4，真实总数应为10。
    run_matches = re.findall(r"当前次数\s*:\s*(\d+)", segment)
    return {"runs": sum(int(value) for value in run_matches), "sanity_remaining": sanity}


def _game_day_activity_summary(now=None):
    """汇总同一游戏日的直接体力用途证据，供跨进程最终弹窗使用。"""
    now = now or datetime.now()
    event = get_active_event(now)
    if not event:
        return None
    try:
        with open(MAA_GUI_LOG, "r", encoding="utf-8") as f:
            recovered = _parse_completed_event_farm_gui_log(f.read(), event, now=now)
    except Exception:
        recovered = None
    # GUI日志的连续代理提示可能只保留首批（例如10连后再补1次时只解析到
    # 10），而活动断点是在整条Fight完成并解析累计FightTimes后才写入。
    # 两者同日同关时取完成次数更大的直接证据，避免最终弹窗少报后续批次。
    farm = (
        (_load_event_progress().get("events", {}).get(event["name"], {}) or {})
        .get("farm", {}) or {}
    )
    checkpoint_valid = bool(
        farm.get("status") == "completed"
        and farm.get("stage") == event.get("farm_stage")
        and farm.get("game_day") == _game_day_key(now)
        and int(farm.get("runs", 0) or 0) > 0
    )
    if checkpoint_valid and int(farm.get("runs", 0)) > int((recovered or {}).get("runs", 0) or 0):
        recovered = {
            "runs": int(farm["runs"]),
            "sanity_remaining": farm.get("sanity_remaining"),
            "sanity_consumed": farm.get("sanity_consumed"),
            "evidence": "同游戏日FightTimes累计完成断点（覆盖GUI残缺批次）",
        }
    elif not recovered or recovered.get("runs", 0) <= 0:
        # MAA GUI的中文消息在部分Windows区域设置下会写成乱码；本脚本只在
        # FightTimes真实完成后才写活动断点，因此同游戏日断点也是直接证据。
        if not checkpoint_valid:
            return None
        recovered = {
            "runs": int(farm["runs"]),
            "sanity_remaining": farm.get("sanity_remaining"),
            "sanity_consumed": farm.get("sanity_consumed"),
            "evidence": "同游戏日FightTimes完成后写入的活动速刷断点",
        }
    runs = int(recovered["runs"])
    cost_each = int(event["farm_cost"])
    return {
        "game_day": _game_day_key(now),
        "type": "event_farm",
        "event": event["name"],
        "stage": event["farm_stage"],
        "runs": runs,
        "sanity_cost_each": cost_each,
        "sanity_consumed": int(recovered.get("sanity_consumed") or runs * cost_each),
        "sanity_after_farm": recovered.get("sanity_remaining"),
        "evidence": recovered.get("evidence") or "同游戏日MAA Fight完成日志、当前次数与理智不足终态",
    }


def _game_day_event_replay_summary(event=None, now=None):
    """汇总今天逐关复刻与指定突袭的真实完成断点及固定理智消耗。"""
    now = now or datetime.now()
    event = event or get_active_event(now)
    if not event or event.get("kind") != "rerun":
        return None
    replay = (
        (_load_event_progress().get("events", {}).get(event["name"], {}) or {})
        .get("task_replay", {}) or {}
    )
    if replay.get("event_start") != event.get("start"):
        return None
    stages = []
    total = 0
    total_failed_runs = 0
    for key, record in (replay.get("stages") or {}).items():
        if (record or {}).get("status") != "completed":
            continue
        try:
            updated_at = datetime.fromisoformat(str(record.get("updated_at") or ""))
        except ValueError:
            continue
        if _game_day_key(updated_at) != _game_day_key(now):
            continue
        base_stage = str(key).split(":", 1)[0]
        cost = int(
            record.get("total_sanity_consumed")
            or record.get("sanity_consumed")
            or (event.get("sanity_costs") or {}).get(base_stage, 0)
            or 0
        )
        failed_runs = int(record.get("failed_runs", 0) or 0)
        stages.append({
            "stage": key,
            "runs": int(record.get("total_runs", 1) or 1),
            "successful_runs": 1,
            "failed_runs": failed_runs,
            "sanity_consumed": cost,
        })
        total += cost
        total_failed_runs += failed_runs
    if not stages:
        return None
    return {
        "game_day": _game_day_key(now),
        "event": event["name"],
        "stages": stages,
        "completed_count": len(stages),
        "failed_runs": total_failed_runs,
        "sanity_consumed": total,
        "evidence": "本次复刻逐关MAA FightTimes完成断点、失败作业记录与关卡固定消耗",
    }


def _game_day_annihilation_summary(now=None):
    """从同一游戏日MAA GUI日志恢复剿灭次数、理智与周合成玉闭环。"""
    now = now or datetime.now()
    try:
        with open(MAA_GUI_LOG, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return None
    starts = [m.start() for m in re.finditer(r'GetFightStage: from \["Annihilation"\]', text)]
    if not starts:
        return None
    segment = text[starts[-1]:]
    end = segment.find("任务已全部完成")
    if end < 0:
        return None
    segment = segment[:end + len("任务已全部完成")]
    stamp = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", segment)
    if not stamp:
        return None
    try:
        started_at = datetime.fromisoformat(stamp.group(1))
    except ValueError:
        return None
    if _game_day_key(started_at) != _game_day_key(now):
        return None
    run_numbers = [int(value) for value in re.findall(r"开始行动\s*(\d+)\s*次\s*,\s*-25理智", segment)]
    progress = re.findall(r"剿灭模式\s*:\s*(\d+)\s*/\s*(\d+)", segment)
    if not run_numbers or not progress:
        return None
    earned, maximum = map(int, progress[-1])
    if earned < maximum:
        return None
    runs = max(run_numbers)
    return {
        "game_day": _game_day_key(now),
        "runs": runs,
        "sanity_consumed": runs * 25,
        "jade_earned": earned,
        "jade_max": maximum,
        "evidence": "同游戏日MAA剿灭Fight链、逐次理智与周上限日志",
    }


def _game_day_security_summary(now=None):
    """读取同一游戏日已经由实时奖励页闭环的保全派驻奖励上限。"""
    now = now or datetime.now()
    progress = load_sss_progress()
    try:
        last_run = datetime.fromisoformat(str(progress.get("last_run") or ""))
    except ValueError:
        return None
    counts = progress.get("reward_counts") or {}
    strip = counts.get("strip")
    device = counts.get("device")
    if (
        _game_day_key(last_run) != _game_day_key(now)
        or progress.get("reward_capped") is not True
        or strip != 60
        or device != 24
    ):
        return None
    return {
        "status": "completed",
        "reward_cycle": progress.get("reward_cycle"),
        "reward_counts": {"strip": 60, "device": 24},
        "reward_capped": True,
        "successful_clears": 0,
        "evidence": "同一游戏日保全奖励页实时读取60/60、24/24并写入进度断点",
    }


def _game_day_chapter17_summary(now=None):
    """列出同一游戏日由阶段账本闭环的17章险地/沙盘目标。"""
    now = now or datetime.now()
    progress = load_progress()
    completed = []
    sanity_consumed = 0
    battles = []
    for stage, phase in (progress.get("chapter17_phases") or {}).items():
        if not isinstance(phase, dict):
            continue
        try:
            updated_at = datetime.fromisoformat(str(phase.get("last_update") or ""))
        except ValueError:
            continue
        if (
            _game_day_key(updated_at) == _game_day_key(now)
            and phase.get("risk") == "cleared"
            and phase.get("sandbox") == "cleared"
        ):
            completed.append(str(stage))
            for phase_name, label in (("risk", "险地"), ("sandbox", "沙盘")):
                cost = phase.get(f"{phase_name}_sanity_cost")
                if isinstance(cost, int) and cost > 0:
                    sanity_consumed += cost
                    battles.append(f"{stage}{label}")
    if not completed:
        return None
    result = {
        "status": "completed",
        "stages": sorted(completed, key=_mainline_target_sort_key),
        "evidence": "同一游戏日险地作战与沙盘推演阶段账本均为cleared",
    }
    if sanity_consumed:
        result.update({
            "sanity_consumed": sanity_consumed,
            "fights": len(battles),
            "battle_labels": battles,
        })
    return result


def _save_mainline_handoff(status, detail, run_state=None, now=None):
    """保存同一游戏日主线实跑总账，供后续日常/收尾进程生成完整弹窗。"""
    now = now or datetime.now()
    payload = {
        "game_day": _game_day_key(now),
        "recorded_at": now.isoformat(timespec="seconds"),
        "status": status,
        "detail": detail,
        "run": deepcopy(run_state or {}),
        "stages": deepcopy(_MAINLINE_STAGE_ATTEMPTS),
        "evidence": "主线实跑作业记录、战斗监督结果与权威进度更新",
    }
    try:
        _atomic_write_json(MAINLINE_HANDOFF_FILE, payload)
        return True
    except Exception as exc:
        log(f"  [主线交接] 写入失败: {exc}", "WARN")
        return False


def _mainline_progress_fallback(now=None):
    """旧进程没有交接文件时，只从本游戏日权威进度恢复可证明的主线事实。"""
    now = now or datetime.now()
    try:
        progress = load_progress()
        updated_at = datetime.fromisoformat(str(progress.get("last_update") or ""))
        stage = str(progress.get("current") or "").strip()
    except Exception:
        return None
    if (
        not stage
        or stage not in set(progress.get("failed") or [])
        or _game_day_key(updated_at) != _game_day_key(now)
    ):
        return None
    detail = str((progress.get("notes") or {}).get(stage) or "本游戏日实战未通关")
    jobs = re.findall(r"(?:auto|alt|hard|main|tough)_[^,\]\s'\"]+\.json", detail)
    attempt_count = len(dict.fromkeys(jobs))
    if not attempt_count:
        count_match = re.search(r"(\d+)\s*(?:份不同作业|份作业|次)", detail)
        if count_match:
            attempt_count = int(count_match.group(1))
        elif "五份" in detail or "5份" in detail or "5次" in detail:
            attempt_count = 5
    outcomes = {}
    if "漏怪" in detail and attempt_count:
        outcomes["leaked"] = attempt_count
    blocked_match = re.search(r"阻塞\s*([A-Z]?\d+-\d+)\s*解锁", detail, re.I)
    return {
        "game_day": _game_day_key(now),
        "recorded_at": updated_at.isoformat(timespec="seconds"),
        "status": "blocked",
        "detail": detail,
        "run": {"status": "blocked", "starting_target": stage, "next_target": stage},
        "stages": {
            stage: {
                "status": "failed",
                "detail": detail,
                "attempt_count": attempt_count,
                "attempted_jobs": list(dict.fromkeys(jobs)),
                "outcome_counts": outcomes,
                "blocked_next_stage": blocked_match.group(1) if blocked_match else None,
            }
        },
        "evidence": "同游戏日权威主线进度与节点复核记录",
    }


def _load_mainline_handoff(now=None):
    """读取同一游戏日主线总账；日期不符或损坏时拒绝沿用旧结果。"""
    now = now or datetime.now()
    try:
        with open(MAINLINE_HANDOFF_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("game_day") == _game_day_key(now):
            return payload
    except Exception:
        pass
    return _mainline_progress_fallback(now)


def _restore_completed_event_farm(event):
    event_state = (_load_event_progress().get("events", {}).get(event["name"], {}) or {})
    farm = event_state.get("farm", {}) or {}
    # 先用原始MAA日志修正持久断点。旧版曾把安全上限99误写为真实次数，
    # 若先信JSON，错误会跨运行永久保留。
    try:
        with open(MAA_GUI_LOG, "r", encoding="utf-8") as f:
            recovered = _parse_completed_event_farm_gui_log(f.read(), event)
    except Exception:
        recovered = None
    if recovered:
        _save_event_farm_checkpoint(
            event, recovered["runs"], recovered["sanity_remaining"],
            "从当日MAA日志恢复：Fight完成、BD-8掉落、理智不足一次",
        )
        log(
            f"✅ 已从当日MAA日志恢复BD-8连续代理："
            f"{recovered['runs']}次，剩余理智{recovered['sanity_remaining']}/210"
        )
        return True
    if (
        farm.get("status") == "completed"
        and farm.get("stage") == event["farm_stage"]
        and farm.get("game_day") == _game_day_key()
    ):
        _save_event_farm_checkpoint(
            event, farm.get("runs", 0), farm.get("sanity_remaining"),
            farm.get("detail", "活动刷取持久断点"),
        )
        return True
    return False


def _parse_completed_daily_gui_log(text, now=None, completed_not_before=None):
    """只接受同一游戏日内五条日常均完成且队列明确结束的MAA GUI日志。"""
    now = now or datetime.now()
    starts = [m.start() for m in re.finditer(r"开始任务:\s*开始唤醒", text or "")]
    if not starts:
        return None
    line_start = (text or "").rfind("\n", 0, starts[-1]) + 1
    segment = (text or "")[line_start:]
    # 一次日常队列必须在它自己的“任务已全部完成”处闭合。不能继续向后
    # 扫描，否则凌晨刷新前的五条完成标记会和刷新后的 Fight 终态拼成
    # 一个并不存在的“今日日常已完成”证据。
    queue_end = segment.find("任务已全部完成")
    if queue_end < 0:
        return None
    queue_end = segment.find("\n", queue_end)
    segment = segment if queue_end < 0 else segment[:queue_end + 1]
    required = {
        "StartUp": "完成任务: 开始唤醒",
        "Infrast": "完成任务: 基建换班",
        "Recruit": "完成任务: 自动公招",
        "Mall": "完成任务: 信用收支",
        "Award": "完成任务: 领取奖励",
    }
    if any(marker not in segment for marker in required.values()) or "任务已全部完成" not in segment:
        return None
    done_lines = [line for line in segment.splitlines() if "任务已全部完成" in line]
    stamp = re.search(
        r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
        done_lines[-1] if done_lines else "",
    )
    if not stamp:
        return None
    try:
        completed_at = datetime.fromisoformat(stamp.group(1))
        age_seconds = (now - completed_at).total_seconds()
    except ValueError:
        return None
    if age_seconds < 0 or age_seconds > 12 * 3600 or _game_day_key(completed_at) != _game_day_key(now):
        return None
    if completed_not_before is not None:
        try:
            boundary = (
                completed_not_before
                if isinstance(completed_not_before, datetime)
                else datetime.fromisoformat(str(completed_not_before))
            )
        except (TypeError, ValueError):
            return None
        if completed_at <= boundary:
            return None
    return {"completed_at": completed_at.isoformat(timespec="seconds"), "chains": tuple(required)}


def _latest_completed_fight_at_from_gui_log(text, now=None):
    """返回本游戏日最近一次真实消耗理智的 Fight 闭环时间。

    MAA 在理智不足时也会产生完整的 Fight 开始/结束日志，但不会出现
    ``开始行动 N 次, -M理智``。这种零次 Fight 不能刷新最终日常边界，
    否则恢复运行会重复执行基建、公招、商店和 Award。
    """
    now = now or datetime.now()
    latest = None
    in_fight = False
    spent_sanity = False
    for line in (text or "").splitlines():
        if "开始任务: 理智作战" in line or "Start Task Chain: Fight" in line:
            if not in_fight:
                in_fight = True
                spent_sanity = False
            continue
        if in_fight and re.search(r"开始行动\s*\d+\s*次\s*,\s*-\d+理智", line):
            spent_sanity = True
            continue
        if not in_fight or not (
            "完成任务: 理智作战" in line or "Completed Task Chain: Fight" in line
        ):
            continue
        in_fight = False
        if not spent_sanity:
            continue
        stamp = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if not stamp:
            continue
        try:
            completed_at = datetime.fromisoformat(stamp.group(1))
        except ValueError:
            continue
        if completed_at <= now and _game_day_key(completed_at) == _game_day_key(now):
            latest = max(latest, completed_at) if latest else completed_at
    return latest


def _parse_fight_times_evidence(text):
    """Extract completed runs and the actually scheduled series batches.

    ``sanity_cost``/``series`` describe the *next* batch at the current
    cumulative ``times_finished`` value.  The final ``finished=true`` callback
    has the final count but no cost.  Count one plan per cumulative boundary
    (including zero), and only plans whose boundary is below the final count.
    """
    plans = []
    seen_plans = set()
    max_finished = 0
    for line in (text or "").splitlines():
        if '"what":"FightTimes"' not in line:
            continue
        runs = re.search(r'"times_finished":(\d+)', line)
        cost = re.search(r'"sanity_cost":(\d+)', line)
        series = re.search(r'"series":(\d+)', line)
        if not runs:
            continue
        finished = int(runs.group(1))
        max_finished = max(max_finished, finished)
        if cost and series:
            plan_key = (finished, int(cost.group(1)), int(series.group(1)))
            if plan_key in seen_plans:
                continue
            plans.append({
                "at_finished": finished,
                "sanity_cost": int(cost.group(1)),
                "series": int(series.group(1)),
            })
            seen_plans.add(plan_key)
    if max_finished <= 0:
        return None

    if any(item["at_finished"] == 0 for item in plans):
        # Current MAA protocol: each record schedules the next batch at the
        # current cumulative boundary.  MAA can first echo the previous batch
        # after opening the insufficient-sanity dialog, then emit the reduced
        # batch at the same boundary.  Only the last plan at each boundary was
        # actually scheduled; the final count has no next batch.
        latest_plan_by_boundary = {}
        for item in plans:
            latest_plan_by_boundary[item["at_finished"]] = item
        completed_plans = [
            latest_plan_by_boundary[boundary]
            for boundary in sorted(latest_plan_by_boundary)
            if boundary < max_finished
        ]
    else:
        # Compatibility with older logs whose first FightTimes record was
        # emitted only after the first batch.  A second record at the same
        # cumulative value is the pending next batch; a later increase confirms it.
        completed_plans = []
        current_finished = None
        pending = None
        for item in plans:
            finished = item["at_finished"]
            if current_finished is None:
                completed_plans.append(item)
                current_finished = finished
                continue
            if finished == current_finished:
                pending = item
                continue
            if finished < current_finished:
                continue
            delta = finished - current_finished
            if pending and pending["series"] == delta:
                completed_plans.append(pending)
            elif item["series"] == delta:
                completed_plans.append(item)
            current_finished = finished
            pending = None
    return {
        "runs": max_finished,
        "sanity_cost": sum(item["sanity_cost"] for item in completed_plans),
        "series_batches": [item["series"] for item in completed_plans],
    }


def _save_fight_handoff(stage, maa_text=None):
    """Persist a completed Fight so a following daily process can report it."""
    if maa_text is None:
        maa_text = _get_current_maa_run_log()
    evidence = _parse_fight_times_evidence(maa_text)
    if not evidence:
        log("  [Fight交接] 未找到已完成次数，拒绝写入", "WARN")
        return False
    sanity_matches = re.findall(r"Current Sanity: (\d+) , Max Sanity: (\d+)", maa_text or "")
    resource = RESOURCE_STAGES.get(stage) or {}
    cost_each = int(resource.get("cost", 0) or 0)
    payload = {
        "game_day": _game_day_key(),
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "stage": stage,
        "runs": int(evidence["runs"]),
        "sanity_cost_each": cost_each or None,
        "sanity_consumed": (
            int(evidence["runs"]) * cost_each if cost_each else int(evidence["sanity_cost"])
        ),
        "series_batches": evidence["series_batches"],
        "sanity_first": int(sanity_matches[0][0]) if sanity_matches else None,
        "sanity_last": int(sanity_matches[-1][0]) if sanity_matches else None,
        "evidence": "MAA FightTimes累计完成、连续代理批次与理智读数",
    }
    _atomic_write_json(FIGHT_HANDOFF_FILE, payload)
    log(
        f"  [Fight交接] {stage}真实完成{payload['runs']}次，"
        f"计划消耗{payload['sanity_consumed']}理智，收尾{payload['sanity_last']}"
    )
    return True


def _load_fight_handoff(now=None):
    now = now or datetime.now()
    try:
        with open(FIGHT_HANDOFF_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    if payload.get("game_day") != _game_day_key(now):
        return None
    return payload


def _parse_stage_drops_evidence(text):
    """只汇总StageDrops回调的addQuantity，避免累计drops/stats被重复相加。"""
    totals = {}
    for line in (text or "").splitlines():
        if '"what":"StageDrops"' not in line or "Assistant::append_callback" not in line:
            continue
        payload_start = line.find("{")
        if payload_start < 0:
            continue
        try:
            payload = json.loads(line[payload_start:])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        details = payload.get("details") or {}
        for item in details.get("stats") or []:
            name = item.get("itemName") or item.get("itemId")
            added = item.get("addQuantity")
            if not name or not isinstance(added, int) or added <= 0:
                continue
            totals[name] = totals.get(name, 0) + added
    return [{"item": name, "qty": qty} for name, qty in sorted(totals.items(), key=lambda pair: -pair[1])]


def _parse_stage_drops_run_count(text, stage_code):
    """Return the largest directly reported completion count for one stage.

    In the game's native multi-proxy screen MAA can report ``FightTimes`` as
    one UI action even though the settlement contains several completed runs.
    ``StageDrops.details.cur_times`` is tied to the exact stage and records the
    real number of settlements, so use it as a second independent counter.
    """
    maximum = 0
    for line in (text or "").splitlines():
        if '"what":"StageDrops"' not in line or '"cur_times"' not in line:
            continue
        payload_start = line.find("{")
        if payload_start < 0:
            continue
        try:
            payload = json.loads(line[payload_start:])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        details = payload.get("details") or {}
        stage = details.get("stage") or {}
        if str(stage.get("stageCode") or "").upper() != str(stage_code or "").upper():
            continue
        try:
            maximum = max(maximum, int(details.get("cur_times") or 0))
        except (TypeError, ValueError):
            continue
    return maximum


def _restore_completed_daily_from_gui_log(completed_not_before=None):
    """把MAA已完成但脚本未收尾的本游戏日日常恢复为本轮可报告证据。"""
    global _LAST_MAA_RUN_LOG
    try:
        with open(MAA_GUI_LOG, "r", encoding="utf-8") as f:
            recovered = _parse_completed_daily_gui_log(
                f.read(), completed_not_before=completed_not_before,
            )
    except Exception:
        recovered = None
    if not recovered:
        return False
    lines = []
    for chain in recovered["chains"]:
        lines.append(f'TaskChainStart {{"taskchain":"{chain}"}}\n')
        lines.append(f'TaskChainCompleted {{"taskchain":"{chain}"}}\n')
    lines.append('AllTasksCompleted {"taskchain":"Award"}\n')
    _LAST_MAA_RUN_LOG = "".join(lines)
    log(f"✅ 已从MAA GUI日志恢复本游戏日最终日常：五条任务链均完成（{recovered['completed_at']}）")
    return True


def _event_stage_position(items, display_name):
    """只接受活动地图主体区域内的精确关卡标签，避免标题/说明文字误命中。"""
    def normalize(value):
        value = str(value).upper().replace(" ", "")
        return re.sub(r"[‐‑‒–—―－]", "-", value)

    target = normalize(display_name)
    for text, x, y in items:
        normalized = normalize(text)
        exact = normalized == target
        # 实机 OCR 偶尔会把节点左侧六边形或右侧连线黏成一个 ASCII 字符，
        # 例如把清晰可见的 TO-EX-5 读成 JTO-EX-5。仅允许首尾多一个
        # 非数字、非连字符的孤立字符；这样仍会拒绝 TO-EX-50、前往TO-EX-5
        # 和地图主体 ROI 外的文字，不把容错扩大成模糊关卡匹配。
        one_char_prefix = (
            len(normalized) == len(target) + 1
            and normalized.endswith(target)
            and normalized[0] not in "0123456789-"
        )
        one_char_suffix = (
            len(normalized) == len(target) + 1
            and normalized.startswith(target)
            and normalized[-1] not in "0123456789-"
        )
        if (exact or one_char_prefix or one_char_suffix) and 100 <= x <= 1820 and 180 <= y <= 930:
            return x, y
    return None


def _event_stage_names(event):
    return [stage["display"] for stage in (event or {}).get("stages", [])]


def _event_first_clear_modes(event):
    """返回该活动当前阶段真实存在的首通模式。"""
    modes = list((event or {}).get("first_clear_modes") or ("normal", "challenge"))
    allowed = {"normal", "challenge"}
    if not modes or any(mode not in allowed for mode in modes):
        raise ValueError(f"活动首通模式配置无效: {modes}")
    return modes


def _event_stage_modes(event, stage):
    """返回单个活动关真实存在的模式，允许普通段与EX段采用不同规则。"""
    modes = list((stage or {}).get("modes") or _event_first_clear_modes(event))
    allowed = {"normal", "challenge"}
    if not modes or any(mode not in allowed for mode in modes):
        raise ValueError(f"活动关模式配置无效: {(stage or {}).get('display')}: {modes}")
    return modes


def _event_story_stage_names(event):
    return list((event or {}).get("story_stages") or [])


def _visible_event_stages(items, event=None):
    visible = {}
    events = [event] if event else list(ACTIVE_EVENTS)
    names = []
    for candidate in events:
        names.extend(_event_stage_names(candidate))
    for name in dict.fromkeys(names):
        pos = _event_stage_position(items, name)
        if pos:
            visible[name] = pos
    return visible


def _visible_event_story_stages(items, event):
    visible = {}
    for name in _event_story_stage_names(event):
        pos = _event_stage_position(items, name)
        if pos:
            visible[name] = pos
    return visible


def _visible_event_manual_prerequisites(items, event, target_stage):
    """返回当前目标关的已配置人工前置；只接受地图主体内精确节点文本。"""
    visible = {}
    for prerequisite in (event or {}).get("manual_prerequisites") or []:
        if prerequisite.get("before") != target_stage:
            continue
        name = str(prerequisite.get("display") or "").strip()
        pos = _event_stage_position(items, name)
        if pos:
            visible[name] = {
                "position": pos,
                "kind": prerequisite.get("kind") or "manual",
            }
    return visible


def _record_event_manual_prerequisite(event, target_stage, prerequisite, evidence_path=None):
    event_run = _RUN_SUMMARY.setdefault(
        "event", {"name": (event or {}).get("name"), "stages": {}}
    )
    entry = {
        "target_stage": target_stage,
        "prerequisite": prerequisite,
        "reason": f"{prerequisite}教学关阻挡，需要手动完成后再继续{target_stage}",
        "status": "manual_required",
    }
    if evidence_path:
        entry["evidence"] = evidence_path
    event_run["manual_prerequisite"] = entry
    event_run.setdefault("stages", {}).setdefault(target_stage, {}).update({
        "status": "manual_required",
        "detail": entry["reason"],
    })
    return entry


def _terminal_last_battle_event_stage(items, event):
    """识别终端右下“前往上一次作战”是否属于当前配置活动。

    玩家在活动标题美术字难以辨认时，会先看右下角清晰的关卡编号。只有该
    编号精确属于当前活动配置，且位于真实快捷卡ROI，才允许把它作为入口；
    同前缀猜测或固定坐标都不算证据。
    """
    configured = {
        re.sub(r"[‐‑‒–—―－\s]", "-", str(stage.get("display") or "").upper()):
        str(stage.get("display") or "")
        for stage in (event or {}).get("stages", [])
        if stage.get("display")
    }
    page_text = " ".join(str(text) for text, _x, _y in (items or []))
    if "前往上一次作战" not in page_text:
        return None
    for text, x, y in items or []:
        normalized = re.sub(r"[‐‑‒–—―－\s]", "-", str(text).upper())
        display = configured.get(normalized)
        if display and 1430 <= x <= 1910 and 790 <= y <= 1015:
            return display, (x, y)
    return None


def _enter_event_map_from_terminal_last_battle(event, items):
    """用已确认属于当前活动的上次作战卡进入，并回到完整活动地图。"""
    matched = _terminal_last_battle_event_stage(items, event)
    if not matched:
        return None
    display_name, pos = matched
    tap(*pos)
    log(f"  [活动导航] 右下快捷卡确认{display_name}属于当前活动，点击 @{pos}")
    wait(5)

    p = shot(f"event_last_battle_{display_name}")
    detail_items = ocr(p)
    detail_text = " ".join(str(text) for text, _x, _y in detail_items)
    detail_open = _event_stage_detail_confirmed(detail_text, display_name)
    if not detail_open and _visible_event_stages(detail_items, event):
        log(f"✅ 已由{display_name}快捷卡进入{event['name']}地图")
        return True
    if not detail_open:
        log(
            f"❌ 点击{display_name}快捷卡后未确认关卡详情或活动地图: "
            f"OCR={detail_text[:160]}",
            "ERROR",
        )
        return False

    # 快捷入口会展开该关详情，而且背景里仍可能同时露出多个关卡标签。
    # 玩家会先退一层关闭抽屉，再扫描页签和节点；不能因背景节点可见就跳过。
    back()
    wait(3)
    map_path = shot(f"event_last_battle_map_{display_name}")
    map_items = ocr(map_path)
    visible = _visible_event_stages(map_items, event)
    if visible:
        log(
            f"✅ {display_name}详情关闭后确认{event['name']}地图节点: "
            f"{', '.join(visible)}"
        )
        return True
    log(f"❌ {display_name}快捷入口后未确认活动地图节点", "ERROR")
    return False


def _clear_event_story_node(event, display_name, pos):
    """闭环活动前置剧情；不消耗理智，也不把剧情节点当战斗交给MAA。"""
    tap(*pos)
    wait(3)
    detail = shot(f"event_story_detail_{display_name}")
    items = ocr(detail)
    start = find_text(items, "开始剧情", exact=False) or find_text(items, "观看序曲", exact=False)
    if not start:
        log(f"❌ {display_name}未确认剧情开始按钮", "ERROR")
        return False
    tap(*start)
    wait(4)
    if get_state() != "story":
        log(f"❌ {display_name}点击后未进入剧情页", "ERROR")
        return False
    skip_story()
    if not _wait_event_story_completion(event, display_name, timeout=75):
        log(f"❌ {display_name}剧情未确认结束", "ERROR")
        return False
    dismiss_reward()
    wait(3)
    log(f"✅ {display_name}前置剧情已闭环")
    return True


def _wait_event_story_completion(event, display_name, timeout=75):
    """以活动地图节点而非主线章节状态闭环零理智剧情。"""
    deadline = time.time() + timeout
    map_reentry_attempted = False
    while time.time() < deadline:
        state = get_state()
        if state == "story":
            skip_story()
            wait(2)
            continue
        if state in ("reward", "victory"):
            dismiss_reward()
            wait(2)
            continue
        probe = shot(f"event_story_complete_{display_name}")
        items = ocr(probe)
        if _visible_event_stages(items, event) or _visible_event_story_stages(items, event):
            return True
        # 剧情结束后可能先回活动总页而不是关卡地图；只在已明确离开剧情后
        # 做一次真实活动导航，再用节点标签确认，避免把主页当成完成。
        if not map_reentry_attempted:
            map_reentry_attempted = True
            if goto_event_map(event):
                probe = shot(f"event_story_map_{display_name}")
                items = ocr(probe)
                if _visible_event_stages(items, event) or _visible_event_story_stages(items, event):
                    return True
        wait(3)
    log(f"  ❌ {display_name}剧情结束后未在活动地图形成节点证据", "ERROR")
    return False


def goto_event_map(event=None):
    """只在OCR确认活动名称/战斗页签后点击，进入活动关卡地图。"""
    event = event or get_active_event()
    if not event:
        log("❌ 当前没有配置为开放状态的活动", "ERROR")
        return False

    # 已在活动地图时直接复用，避免反复退主页。
    p = shot("event_map_probe")
    items = ocr(p)
    if _visible_event_stages(items, event):
        log(f"✅ 已在{event['name']}关卡地图（节点标签图形确认）")
        return True
    story_nodes = _visible_event_story_stages(items, event)
    if story_nodes:
        name, pos = next(iter(story_nodes.items()))
        log(f"  [活动导航] 检测到前置剧情{name}，先完成零理智剧情")
        if not _clear_event_story_node(event, name, pos):
            return False
        p = shot("event_map_after_story")
        items = ocr(p)
        if _visible_event_stages(items, event):
            log(f"✅ {name}结束后已解锁{event['stages'][0]['display']}")
            return True

    if not goto_terminal_main():
        return False

    # 终端里优先用活动中文名定位。若美术字OCR失败，则使用玩家真正会看的
    # 右下“前往上一次作战”关卡编号；该编号必须精确属于当前活动配置。
    for attempt in range(4):
        p = shot(f"event_entry_{attempt}")
        items = ocr(p)
        text = " ".join(t for t, _, _ in items)
        if attempt == 0:
            shortcut_result = _enter_event_map_from_terminal_last_battle(event, items)
            if shortcut_result is not None:
                navigation = _RUN_SUMMARY.setdefault("event", {}).setdefault("navigation", {})
                navigation.update({
                    "method": "terminal_last_battle_stage_code",
                    "status": "verified" if shortcut_result else "failed",
                })
                return shortcut_result
        entry = None
        for keyword in event.get("entry_keywords", [event["name"]]):
            entry = find_text(items, keyword, exact=False)
            if entry:
                break
        if entry:
            tap(*entry)
            log(f"  [活动导航] OCR确认并点击{event['name']}入口 @{entry}")
            wait(5)
            break
        if attempt < 3:
            log(f"  [活动导航] 终端未找到{event['name']}，等待界面加载 {attempt+1}/4")
            wait(3)
    else:
        log(f"❌ 终端未识别到活动入口: {event['name']}", "ERROR")
        return False

    # 活动首页可能还要点一次战斗篇章“生长痛”。每一步都先OCR确认。
    for attempt in range(8):
        p = shot(f"event_lobby_{attempt}")
        items = ocr(p)
        text = " ".join(t for t, _, _ in items)
        visible = _visible_event_stages(items, event)
        if visible:
            log(f"✅ 已进入{event['name']}关卡地图（可见节点: {', '.join(visible)}）")
            return True
        story_nodes = _visible_event_story_stages(items, event)
        if story_nodes:
            name, pos = next(iter(story_nodes.items()))
            log(f"  [活动导航] 战斗篇章内检测到前置剧情{name}")
            if not _clear_event_story_node(event, name, pos):
                return False
            continue
        if get_state() == "story":
            skip_story()
            wait(5)
            continue
        combat = None
        for keyword in event.get("combat_keywords", []):
            combat = find_text(items, keyword, exact=False)
            if combat:
                break
        combat = combat or find_text(items, "活动关卡", exact=False) or find_text(items, "进入活动", exact=False)
        if combat:
            tap(*combat)
            log(f"  [活动导航] OCR确认战斗入口 @{combat}")
            wait(5)
            continue
        if "公告" in text or "更新日志" in text:
            handle_popups()
        wait(3)

    log(f"❌ 已进入{event['name']}但未确认关卡地图", "ERROR")
    return False


def _event_stage_marker_reliable(pos, image_width=1920):
    """节点标签太靠屏幕边缘时，左侧六边形ROI可能落在装饰背景上。"""
    if not pos:
        return False
    x, _y = pos
    return 230 <= x <= image_width - 270


def _dismiss_known_event_map_overlay(items):
    """只关闭已由实机证据确认的活动地图覆盖页，不执行旅行小记。"""
    text = " ".join(str(item[0]) for item in items if item)
    if (
        "获得蚀刻章" in text
        or ("首次获得" in text and any(k in text for k in ("高级凭证", "资质凭证")))
    ):
        tap(*POS_DISMISS)
        wait(2)
        log("  [活动地图] 已关闭首次干员/蚀刻章展示，重新执行左端复位")
        return "operator_reward"
    if (
        any(k in text for k in ("愿望清单", "Wishlist"))
        and any(k in text for k in ("安洁莉娜", "旅行小记"))
    ):
        tap(*POS_BACK)
        wait(2)
        log("  [活动地图] 已退出旅行小记愿望清单（未执行小游戏/领奖），重新执行左端复位")
        return "travel_wishlist"
    return None


def _event_stage_section_key(display_name):
    """把关卡代码映射到本期活动配置声明的地图分段。"""
    upper = str(display_name or "").upper()
    if "-EX-" in upper:
        return "ex"
    if "-S-" in upper or "-MO-" in upper:
        return "s"
    return "normal"


def _select_event_stage_section(display_name, event=None):
    """按目标关卡族选择活动分段，且必须在任何前置节点判断之前执行。"""
    event = event or get_active_event()
    # 普通与EX是两个独立页签。页签名称属于每期活动配置，不能把上期活动
    # 的标题硬编码到当前活动，也不能在普通地图横扫后把“找不到EX”当节点
    # 缺失。
    section_probe = shot(f"event_section_{display_name}")
    section_items = ocr(section_probe)
    section_text = " ".join(str(item[0]) for item in section_items if item)
    # 战斗结束后 MAA 会停在上一关详情页；详情层仍能透出背景节点，旧逻辑
    # 因此把它误认成纯地图层，却又看不到被详情面板遮住的底部分区页签，
    # 从 S 区切回 EX 时只会原地重试。先用详情语义闭环退回地图，再进行
    # 页签识别；不能只凭背景里出现任一 AT 节点就宣称已在地图层。
    if (
        "开始行动" in section_text
        or "开始突袭" in section_text
        or (
            "代理指挥" in section_text
            and any(marker in section_text for marker in ("推荐平均等级", "敌方情报", "地图"))
        )
    ):
        back()
        wait(3)
        section_probe = shot(f"event_section_map_{display_name}")
        section_items = ocr(section_probe)
        section_text = " ".join(str(item[0]) for item in section_items if item)
        if "开始行动" in section_text or "开始突袭" in section_text:
            log(f"❌ {display_name}分段切换前无法退出上一关详情层", "ERROR")
            return False
        log(f"  [活动页签] 已退出上一关详情层，回到纯地图后切换{_event_stage_section_key(display_name)}")
    visible = _visible_event_stages(section_items)
    target_section = _event_stage_section_key(display_name)
    visible_sections = {_event_stage_section_key(name) for name in visible}
    configured_sections = (event or {}).get("section_keywords") or {}
    default_keywords = {
        "normal": ["演出开始"],
        "ex": ["为戏剧，为永恒"],
        "s": ["特殊关卡"],
    }
    section_keywords = list(
        configured_sections.get(target_section)
        or default_keywords[target_section]
    )
    if target_section in visible_sections:
        return True
    section_pos = next(
        (find_text(section_items, keyword, exact=False) for keyword in section_keywords
         if find_text(section_items, keyword, exact=False)),
        None,
    )
    if not section_pos:
        fallback = ((event or {}).get("section_positions") or {}).get(target_section)
        if fallback and visible:
            section_pos = tuple(fallback)
            log(
                f"  [活动页签] 美术字OCR漏读；已确认本期节点{sorted(visible)}，"
                f"使用{target_section}配置坐标 @{section_pos}",
                "WARN",
            )
    if not section_pos:
        log(
            f"❌ 活动地图未确认{target_section}分段页签{section_keywords}",
            "ERROR",
        )
        return False
    tap(*section_pos)
    log(f"  [活动页签] 切换{target_section}‘{section_keywords[0]}’ @{section_pos}")
    wait(5)
    verify_path = shot(f"event_section_verify_{display_name}")
    verify_items = ocr(verify_path)
    verify_visible = _visible_event_stages(verify_items, event)
    verify_sections = {_event_stage_section_key(name) for name in verify_visible}
    if target_section not in verify_sections:
        log(
            f"❌ 点击{target_section}页签后未看到目标关卡族；"
            f"可见节点={sorted(verify_visible)}",
            "ERROR",
        )
        return False
    log(f"✅ 已切换{target_section}页签，可见节点={sorted(verify_visible)}")
    return True


def _locate_event_stage(display_name, event=None):
    """在活动地图上定位关卡；先选普通/EX页签，再小步滚动并逐步OCR确认。"""
    event = event or get_active_event()
    swipe_y = int((event or {}).get("navigation_swipe_y", 700))
    reset_swipe = tuple((event or {}).get(
        "navigation_reset_swipe", (950, swipe_y, 1600, swipe_y, 700)
    ))
    forward_swipe = tuple((event or {}).get(
        "navigation_forward_swipe", (1500, swipe_y, 950, swipe_y, 700)
    ))
    if not _select_event_stage_section(display_name, event=event):
        return None, [], None

    # 新活动首次进入地图时，干员/蚀刻章展示与旅行小记愿望清单可能延迟
    # 覆盖地图。旧逻辑先盲复位，再把覆盖页上的失败手势忽略，覆盖页退出后
    # 只向后扫描，因此永远停在 TO-7~TO-9。每关闭一层已知覆盖页后必须从
    # 左端复位重新开始；未知覆盖页仍保持失败闭锁。
    for overlay_round in range(4):
        reset_failed = False
        for _ in range(5):
            # Swipe on the empty lower map background.  The old y=520 path crossed
            # stage nodes/links on 红丝绒 and the game consumed it as a node gesture,
            # leaving AD-7/AD-8 fixed on screen forever.
            if swipe(*reset_swipe) is False:
                reset_failed = True
            wait(1)
        if reset_failed:
            log("  [活动地图] 左端复位期间有滑动被拒绝，将以截图识别决定是否重置", "WARN")

        restart_after_overlay = False
        # 0720实机：一次1200px大滑动会从AD-2直接越过AD-3跳到AD-4/AD-5，
        # 所以定位阶段固定用450px小步，宁可多截几次也不跨过目标。
        for attempt in range(24):
            p = shot(f"event_stage_{display_name}_{overlay_round}_{attempt}")
            items = ocr(p)
            overlay = _dismiss_known_event_map_overlay(items)
            if overlay:
                restart_after_overlay = True
                break
            pos = _event_stage_position(items, display_name)
            # 只在节点及其左侧图标均远离屏幕边缘时返回。TO-5曾仅有文字
            # 贴在右边缘，旧逻辑把蓝色云层当成已通关六边形，进而跳过该关。
            if pos and _event_stage_marker_reliable(pos):
                return p, items, pos
            if attempt < 23:
                if swipe(*forward_swipe) is False:
                    log("  [活动地图] 前向扫描滑动失败，拒绝继续假扫描", "ERROR")
                    return None, [], None
                wait(1.5)
        if restart_after_overlay:
            continue
        return None, [], None
    return None, [], None


def verify_event_navigation_ready(event=None):
    """战斗前真实验证：游戏→终端活动入口→战斗页→BD地图→BD-1节点。"""
    event = event or get_active_event()
    run_event = _RUN_SUMMARY.setdefault("event", {"name": (event or {}).get("name"), "stages": {}})
    nav = run_event.setdefault("navigation", {})
    nav["status"] = "checking"
    if not event:
        nav.update({"status": "failed", "detail": "当前无开放活动"})
        return False
    if not goto_event_map(event):
        nav.update({"status": "failed", "detail": "未确认进入活动地图"})
        return False
    first_stage = event["stages"][0]["display"]
    p, items, pos = _locate_event_stage(first_stage, event=event)
    if not p or not pos:
        nav.update({"status": "failed", "detail": f"活动地图未定位{first_stage}"})
        log(f"❌ 活动首战前置验证失败：地图内未定位{first_stage}", "ERROR")
        return False
    nav.update({"status": "verified", "detail": f"{first_stage}@{pos[0]},{pos[1]}"})
    log(f"✅ 活动首战前置验证通过：入口、地图、{first_stage}节点均已图形确认 @{pos}")
    return True


def _event_stage_detail_confirmed(detail_text, display_name):
    """确认当前画面确为目标活动关卡详情，而不是相邻节点或地图背景。"""
    text = str(detail_text or "")
    return display_name.upper() in text.upper() and any(
        marker in text
        for marker in ("开始行动", "代理指挥", "普通难度", "突袭模式", "演习")
    )


def _open_event_stage_detail(event, display_name, *, tag="event_detail", ensure_map=True):
    """打开并确认目标活动关详情页，统一供战前判断和战后验收使用。"""
    if ensure_map and not goto_event_map(event):
        return None
    _path, _items, pos = _locate_event_stage(display_name, event=event)
    if not pos:
        log(f"❌ 活动地图未找到{display_name}", "ERROR")
        return None
    tap(*pos)
    wait(4)
    detail_path = shot(f"{tag}_{display_name}")
    detail_items = ocr(detail_path)
    detail_text = " ".join(str(text) for text, _, _ in detail_items)
    if not _event_stage_detail_confirmed(detail_text, display_name):
        log(
            f"❌ 点击后未确认进入{display_name}详情页，拒绝读取完成徽记: "
            f"OCR={detail_text[:180]}",
            "ERROR",
        )
        back()
        wait(2)
        return None
    return detail_path, detail_items, detail_text


def verify_event_stage_cleared(event, display_name):
    """战后进入关卡详情，以前三枚徽记确认普通三星通关。

    活动地图背景会包含大面积青蓝装饰，不能再把关卡文字左侧的颜色占比
    当作完成证据。只有真实点进目标关卡详情并看到前三枚青色徽记点亮，
    才能更新活动进度。
    """
    opened = _open_event_stage_detail(
        event, display_name, tag="event_verify_detail", ensure_map=True,
    )
    if not opened:
        return False, False
    detail, _detail_items, _detail_text = opened
    ratio = _event_normal_badges_ratio(detail)
    back()
    wait(2)
    cleared = ratio >= 0.08
    perfect = cleared
    if not cleared:
        log(f"  [活动详情徽记] {display_name}: cyan={ratio:.3f} → 未通关")
        return False, False
    log(f"  [活动详情徽记] {display_name}: cyan={ratio:.3f} → 普通三星")
    return cleared, perfect


def _event_challenge_badge_ratio(image_path):
    """活动详情右上第四枚白色徽记比例；暗色=未完成，白色=突袭已完成。"""
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    # 0714实机1920x1080：第四枚徽记位于最右上，按比例缩放以兼容截图尺寸。
    roi = img.crop((
        int(width * 0.922), int(height * 0.102),
        int(width * 0.977), int(height * 0.223),
    ))
    pixel_reader = getattr(roi, "get_flattened_data", roi.getdata)
    pixels = list(pixel_reader())
    if not pixels:
        return 0.0
    white = sum(1 for r, g, b in pixels if r > 180 and g > 180 and b > 180)
    return white / len(pixels)


def _event_normal_badges_ratio(image_path):
    """活动详情前三枚青色徽记比例；三枚点亮表示普通三星已完成。"""
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    roi = img.crop((
        int(width * 0.750), int(height * 0.102),
        int(width * 0.915), int(height * 0.223),
    ))
    pixel_reader = getattr(roi, "get_flattened_data", roi.getdata)
    pixels = list(pixel_reader())
    if not pixels:
        return 0.0
    cyan = sum(1 for r, g, b in pixels if b > 150 and g > 100 and b > r * 1.3)
    return cyan / len(pixels)


def _event_proxy_command_selected(image_path):
    """Return whether the detail-page proxy checkbox is visibly selected.

    Challenge mode is disabled while proxy command remains checked.  The checkbox
    itself is much more stable than its greyed-out label: on the verified 1920x1080
    screenshots the selected box has a white-pixel ratio around 0.46, while the
    unselected box is around 0.05.
    """
    if not image_path:
        return False
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    roi = img.crop((
        int(width * 0.815), int(height * 0.795),
        int(width * 0.855), int(height * 0.860),
    ))
    pixel_reader = getattr(roi, "get_flattened_data", roi.getdata)
    pixels = list(pixel_reader())
    if not pixels:
        return False
    white = sum(1 for r, g, b in pixels if r > 180 and g > 180 and b > 180)
    return white / len(pixels) >= 0.20


def _event_challenge_button_active(image_path):
    """Graphical fallback for the bright-red challenge button."""
    if not image_path:
        return False
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    roi = img.crop((
        int(width * 0.490), int(height * 0.870),
        int(width * 0.650), int(height * 0.960),
    ))
    pixel_reader = getattr(roi, "get_flattened_data", roi.getdata)
    pixels = list(pixel_reader())
    if not pixels:
        return False
    red = sum(
        1 for r, g, b in pixels
        if r > 80 and r > g * 1.8 and r > b * 1.5
    )
    return red / len(pixels) >= 0.12


def verify_event_challenge_cleared(event, display_name):
    """突袭战后进入详情页，以第四枚高亮白色徽记直接确认完成。"""
    if not goto_event_map(event):
        return False
    _p, _items, pos = _locate_event_stage(display_name, event=event)
    if not pos:
        log(f"  ❌ 活动地图找不到{display_name}，无法验证突袭", "ERROR")
        return False
    tap(*pos)
    wait(4)
    detail = shot(f"event_challenge_verify_{display_name}")
    detail_text = ocr_text(detail)
    # 关卡详情默认显示普通模式。已完成突袭后，左下“突袭模式”按钮可能因
    # 字体/暗色遮罩而漏 OCR；不能因此否定右上第四枚白色徽记。这里用
    # 精确关卡名 + 详情页稳定控件确认页面语义，第四徽记再单独确认结果。
    detail_markers = ("开始行动", "代理指挥", "推荐平均等级", "敌方情报", "地图")
    if display_name not in detail_text or not any(
        marker in detail_text for marker in detail_markers
    ):
        log(f"  ❌ {display_name}突袭验证未确认关卡详情页", "ERROR")
        return False
    ratio = _event_challenge_badge_ratio(detail)
    completed = ratio >= 0.08
    log(f"  [活动突袭徽记] {display_name}: white={ratio:.3f} → {'已完成' if completed else '未完成'}")
    back()
    wait(3)
    return completed


def mode_event_verify(stage_code):
    """用户明确声明手动完成后，只读复核指定活动突袭并同步断点。

    徽记只能证明关卡已完成，不能独自证明是本次复刻重打。因此该入口
    必须由显式 ``--mode event_verify --stage ...`` 调用，不能由 full 模式
    或当天已耗尽的自动重试分支自行触发。
    """
    summary = _RUN_SUMMARY.setdefault("event", {}).setdefault(
        "manual_challenge_verification", {}
    )
    summary.update({"stage": stage_code, "status": "checking"})
    event = get_active_event()
    if not event:
        summary.update({"status": "failed", "detail": "未检测到当前开放活动"})
        log("❌ 未检测到当前开放活动，无法复核手动突袭结果", "ERROR")
        return False

    required = set(event.get("required_challenge_replays") or [])
    configured = set(_event_stage_names(event))
    if stage_code not in required or stage_code not in configured:
        detail = f"{stage_code}不是当前活动契约中的指定突袭重打目标"
        summary.update({"status": "rejected", "detail": detail})
        log(f"❌ {detail}", "ERROR")
        return False

    if not verify_event_challenge_cleared(event, stage_code):
        detail = "用户声明手动完成，但第四枚白色突袭徽记未通过图形复核"
        summary.update({"status": "unverified", "detail": detail})
        log(f"❌ {stage_code}{detail}；未修改完成记录", "ERROR")
        return False

    detail = "用户明确声明本次手动重打；关卡名、突袭页面及第四枚白色徽记图形复核通过"
    _update_event_task_replay(
        event, f"{stage_code}:challenge", "completed", detail,
    )
    summary.update({"status": "completed", "detail": detail})
    log(f"✅ {stage_code}手动突袭结果已图形复核，并同步本次复刻任务断点")
    return True


def _select_event_stage_mode(
        display_name, mode, detail_items, detail_text, detail_path=None):
    """在关卡详情页选择普通/突袭；突袭必须由页面变化直接确认。"""
    if mode == "normal":
        return True
    if mode != "challenge":
        raise ValueError(f"未知活动关模式: {mode}")

    challenge_markers = ("突袭附加条件", "突袭条件", "挑战条件", "附加条件")
    if any(marker in detail_text for marker in challenge_markers):
        log(f"  [活动模式] {display_name}已在突袭模式")
        return True

    # 普通代理结束后游戏会保留“代理指挥”勾选；此时突袭按钮会变暗，OCR
    # 看不到“突袭模式”。必须先由复选框亮度确认确实勾选，再取消代理。
    if _event_proxy_command_selected(detail_path):
        proxy_pos = find_text(detail_items, "代理指挥", exact=False)
        if not proxy_pos:
            from PIL import Image
            with Image.open(detail_path) as image:
                width, height = image.size
            proxy_pos = (int(width * 0.895), int(height * 0.824))
        tap(*proxy_pos)
        log(f"  [活动模式] 代理指挥仍勾选，先取消以解锁突袭入口 @{proxy_pos}")
        wait(2)
        detail_path = shot(f"event_challenge_proxy_off_{display_name}")
        detail_items = ocr(detail_path)
        detail_text = " ".join(str(text) for text, _x, _y in detail_items)
        if _event_proxy_command_selected(detail_path):
            log(f"❌ {display_name}代理指挥未能取消，拒绝盲点突袭", "ERROR")
            return "challenge_unavailable"

    challenge_pos = find_text(detail_items, "突袭模式", exact=False)
    if not challenge_pos and _event_challenge_button_active(detail_path):
        from PIL import Image
        with Image.open(detail_path) as image:
            width, height = image.size
        challenge_pos = (int(width * 0.570), int(height * 0.915))
        log(f"  [活动模式] OCR未读到亮红按钮，使用已验证图形ROI @{challenge_pos}")
    if not challenge_pos:
        log(f"❌ {display_name}详情页未找到突袭模式入口", "ERROR")
        return "challenge_unavailable"
    tap(*challenge_pos)
    log(f"  [活动模式] 点击突袭模式 @{challenge_pos}")
    wait(3)
    selected_path = shot(f"event_challenge_selected_{display_name}")
    selected_text = ocr_text(selected_path)
    if not any(marker in selected_text for marker in challenge_markers):
        log(
            f"❌ {display_name}突袭模式未被页面变化确认，可能仍未解锁，OCR={selected_text[:120]}",
            "ERROR",
        )
        return "challenge_locked"
    log(f"✅ {display_name}突袭模式已由页面文字确认")
    return True


def _prepare_event_farm_stage(event, display_name):
    """图形导航到活动普通关详情页，为 MAA 当前关卡连续代理建立硬前置。"""
    # 恢复运行时可能停在BD-2等已完成关的详情页；先退回地图一次，避免在
    # 详情遮罩上反复打开旧关卡。这里只按页面语义返回，不使用固定坐标。
    probe = shot("event_farm_resume_probe")
    probe_text = ocr_text(probe)
    if any(marker in probe_text for marker in ("代理指挥", "开始行动", "开始突袭", "普通难度")):
        back()
        wait(3)
    if not goto_event_map(event):
        return False
    _path, _items, pos = _locate_event_stage(display_name, event=event)
    if not pos:
        log(f"❌ 活动刷取前未定位到{display_name}", "ERROR")
        return False
    tap(*pos)
    wait(4)

    detail = shot(f"event_farm_detail_{display_name}")
    items = ocr(detail)
    text = " ".join(t for t, _, _ in items)
    if display_name not in text:
        log(f"❌ 活动刷取前未确认{display_name}详情页", "ERROR")
        return False

    # 突袭通关后页面会保留突袭模式；必须显式点“普通难度”切回普通关。
    normal_pos = find_text(items, "普通难度", exact=False)
    if normal_pos:
        tap(*normal_pos)
        log(f"  [活动刷取] {display_name}由突袭切回普通难度 @{normal_pos}")
        wait(3)
        detail = shot(f"event_farm_normal_{display_name}")
        items = ocr(detail)
        text = " ".join(t for t, _, _ in items)

    required = (display_name, "代理指挥", "开始行动")
    if any(marker not in text for marker in required) or "开始突袭" in text or "附加条件" in text:
        log(
            f"❌ {display_name}普通代理前置未闭环，拒绝交给MAA: OCR={text[:180]}",
            "ERROR",
        )
        return False
    log(f"✅ {display_name}普通难度、代理指挥、开始行动均已图形确认")
    return True


def _enter_event_stage(event, display_name, mode="normal", force_replay=False):
    if not goto_event_map(event):
        return False
    # EX关与普通关属于独立页签。旧流程在普通页签先判断目标缺失，误把
    # 普通剧情TO-ST-1当成TO-EX-7前置；目标是EX时必须先切EX，再扫描目标
    # 或该页签自己的前置节点。普通关保留中途剧情TO-ST-2的原有闭环流程。
    if _event_stage_section_key(display_name) != "normal":
        if not _select_event_stage_section(display_name, event=event):
            return False
    prerequisite_probe = shot(f"event_prerequisite_{display_name}")
    prerequisite_items = ocr(prerequisite_probe)
    if not _event_stage_position(prerequisite_items, display_name):
        manual_nodes = _visible_event_manual_prerequisites(
            prerequisite_items, event, display_name,
        )
        if manual_nodes:
            prerequisite = next(iter(manual_nodes))
            _record_event_manual_prerequisite(
                event, display_name, prerequisite, evidence_path=prerequisite_probe,
            )
            log(
                f"⛔ {display_name}尚未解锁：地图已明确识别到前置教学关"
                f"{prerequisite}。请手动完成该教学关后重新运行；本轮未启动MAA、"
                "未消耗理智，也不计作业重试次数。",
                "ERROR",
            )
            return ("manual_required", prerequisite)

        # 活动普通关之间可能插入零理智剧情（实机：TO-6 -> TO-ST-2 ->
        # TO-7）。入口导航只要看到任一已解锁战斗关就会判定“已在地图”，
        # 因而中途剧情必须在目标关缺失时单独闭环。剧情不属于作业或实战
        # 重试，完成后重新扫描目标关。
        story_nodes = _visible_event_story_stages(prerequisite_items, event)
        if story_nodes:
            def _story_order(item):
                name, (_x, _y) = item
                match = re.search(r"-ST-(\d+)$", str(name).upper())
                return (int(match.group(1)) if match else -1, _x)

            story_name, story_pos = max(story_nodes.items(), key=_story_order)
            log(
                f"  [活动前置] {display_name}尚未出现，先闭环零理智剧情"
                f"{story_name}（不计作业/实战重试）"
            )
            if not _clear_event_story_node(event, story_name, story_pos):
                return "story_prerequisite_failed"
            if not goto_event_map(event):
                return False
            refreshed = shot(f"event_prerequisite_after_{story_name}_{display_name}")
            refreshed_items = ocr(refreshed)
            if not _event_stage_position(refreshed_items, display_name):
                log(
                    f"❌ {story_name}已结束但{display_name}仍未在地图出现",
                    "ERROR",
                )
                return False
    # 地图节点周围可能有青蓝云层/装饰。地图ROI只能用于定位，不能作为
    # “已通关”证据；必须点进详情页读取完成徽记后才能跳过战斗。
    opened = _open_event_stage_detail(
        event, display_name, tag="event_detail", ensure_map=False,
    )
    if not opened:
        return False
    detail, detail_items, detail_text = opened
    if "通关" in detail_text and "解锁" in detail_text:
        log(f"❌ {display_name}尚未解锁", "ERROR")
        back()
        wait(2)
        return "locked"
    if mode == "normal" and not force_replay:
        ratio = _event_normal_badges_ratio(detail)
        if ratio >= 0.08:
            log(f"  [活动战前] {display_name}前三枚青色徽记已亮，普通三星无需重打")
            back()
            wait(2)
            return ("already_cleared", True)
    if mode == "challenge" and not force_replay:
        ratio = _event_challenge_badge_ratio(detail)
        if ratio >= 0.08:
            log(f"  [活动战前] {display_name}第四枚白色徽记已亮，突袭无需重打")
            back()
            wait(2)
            return ("already_cleared", True)
    selected = _select_event_stage_mode(
        display_name, mode, detail_items, detail_text, detail_path=detail,
    )
    if selected is not True:
        return selected
    formation = _enter_formation(0, display_name)
    if formation is True:
        return display_name
    return formation


def _event_copilot_attempt_limit():
    """读取当前用户授权的活动单关不同作业总预算。"""
    contract = load_project_contract() or {}
    constraints = contract.get("hard_constraints") or {}
    goal = next(
        (
            item for item in (contract.get("active_goals") or [])
            if isinstance(item, dict) and item.get("id") == "G-EVENT-001"
        ),
        {},
    )
    constraint_limit = int(constraints.get("max_event_attempts", 0) or 0)
    goal_limit = int(goal.get("max_distinct_jobs_per_stage", 0) or 0)
    if constraint_limit != goal_limit or constraint_limit <= 0:
        log(
            "⛔ 活动作业重试预算在项目契约中不一致，拒绝进入战斗: "
            f"hard={constraint_limit}, goal={goal_limit}",
            "ERROR",
        )
        return 0
    return constraint_limit


def _event_preflight_rejection_limit(max_attempts):
    """给未进入战斗的作业前置拒绝设置独立安全上限。

    用户约定的五份作业预算只统计真正进入战斗的不同作业。缺干员、模组、
    技能或编队页静默都不消耗理智，因此使用更宽的独立保护阈值；仍保留
    有限上限，防止在线结果异常时形成无限下载/拒绝循环。
    """
    return max(20, int(max_attempts) * 4)


def clear_event_stage(event, stage, mode="normal", max_attempts=None, force_replay=False):
    """活动普通/突袭：详情模式→真实编队→MAA结束→结算/地图闭环。"""
    global _CURRENT_RUN_LAST_STAMINA_BATTLE_AT
    if max_attempts is None:
        max_attempts = _event_copilot_attempt_limit()
    max_attempts = int(max_attempts or 0)
    if max_attempts <= 0:
        return "invalid_retry_budget"
    display_name = stage["display"]
    internal_name = (
        stage.get("challenge_internal", stage["internal"])
        if mode == "challenge"
        else stage["internal"]
    )
    mode_name = "普通" if mode == "normal" else "突袭"
    used_jobs = _event_attempted_jobs(event["name"], display_name, mode)
    incompatible_jobs = _event_incompatible_jobs(event["name"], display_name, mode)
    # 重试预算按同一关卡/模式已经实际选过的不同作业累计，而不是每次启动
    # 脚本都重新获得 max_attempts 次。这样既能在确认战败后继续切换作业，
    # 也不会因为重启脚本而突破用户设定的总预算。
    used_jobs = list(dict.fromkeys(used_jobs))
    remaining_attempts = max(0, max_attempts - len(used_jobs))
    if remaining_attempts <= 0:
        # 重试预算只能限制“再次开战”，不能阻止只读复核。恢复运行时，关卡
        # 可能已在上一轮最后一份作业中通关，但进度文件来不及落账；必须先
        # 读取当前地图详情徽记，再决定是否真的属于预算耗尽。
        if not force_replay:
            if mode == "challenge":
                live_cleared = verify_event_challenge_cleared(event, display_name)
            else:
                live_cleared, _live_perfect = verify_event_stage_cleared(
                    event, display_name,
                )
            if live_cleared:
                _update_event_progress(
                    event["name"], display_name, "cleared",
                    "历史作业预算已满；开战前由当前详情徽记修订为已完成",
                    mode=mode,
                )
                log(
                    f"✅ {display_name}{mode_name}虽已用满历史作业预算，"
                    "但当前详情徽记确认已完成，无需重打"
                )
                return True
        log(
            f"⛔ {display_name}{mode_name}不同作业预算已耗尽: "
            f"{len(used_jobs)}/{max_attempts}",
            "ERROR",
        )
        return "retry_exhausted"

    last_retry_status = "battle_failed"
    navigation_failures = 0
    incompatible_this_run = 0
    while len(used_jobs) < max_attempts:
        attempt = len(used_jobs)
        log(f"\n--- 活动{display_name} {mode_name} 作业 {attempt+1}/{max_attempts} ---")
        entered = _enter_event_stage(
            event, display_name, mode=mode, force_replay=force_replay,
        )
        if (
            isinstance(entered, tuple)
            and len(entered) >= 2
            and entered[0] == "manual_required"
        ):
            return entered
        if isinstance(entered, tuple) and entered[0] == "already_cleared":
            _update_event_progress(
                event["name"], display_name, "cleared",
                "战前详情前三枚青色徽记确认普通三星" if mode == "normal" else "战前详情第四枚白色徽记确认突袭完成",
                mode=mode,
            )
            return True
        if entered in ("locked", "stamina", "challenge_locked", "challenge_unavailable"):
            _update_event_progress(
                event["name"], display_name, str(entered), "未启动战斗", mode=mode,
            )
            return entered
        if not entered:
            navigation_failures += 1
            log(
                f"⚠️ {display_name}{mode_name}地图导航恢复 "
                f"{navigation_failures}/{remaining_attempts}；尚未进入战斗，"
                "不计作业失败或理智战败",
                "WARN",
            )
            if navigation_failures >= remaining_attempts:
                break
            continue
        job = None
        if mode == "challenge":
            normal_job = _event_successful_normal_job(event["name"], display_name)
            used_basenames = {
                os.path.basename(value) for value in used_jobs + incompatible_jobs
            }
            if normal_job and os.path.basename(normal_job) not in used_basenames:
                job = normal_job
                log(
                    f"  [突袭作业] 先复用普通模式已验证作业: "
                    f"{os.path.basename(normal_job)}"
                )
        if not job:
            # 突袭与普通模式共用地图和部署时间线；即使第一次复用失败，
            # 后续也应按普通关卡编号寻找下一份不同作业，而不是要求网站
            # 额外提供一个“突袭专用”标签。
            search_name = stage["internal"] if mode == "challenge" else internal_name
            candidate_rank = len(used_jobs) + len(incompatible_jobs)
            job = get_copilot_json(
                search_name,
                display_name,
                attempt=candidate_rank,
                excluded_paths=list(used_jobs + incompatible_jobs),
            )
        if not job:
            _update_event_progress(
                event["name"], display_name, "no_job", "无精确匹配作业", mode=mode,
            )
            return "no_job"
        if os.path.basename(job) in {
            os.path.basename(value) for value in used_jobs + incompatible_jobs
        }:
            log(f"⛔ 作业去重失效，拒绝重复执行: {os.path.basename(job)}", "ERROR")
            return "duplicate_job"
        if not run_maa_copilot(job):
            if _maa_task_queue_running():
                _stop_maa_task_queue(timeout=30)
            _update_event_progress(
                event["name"], display_name, "maa_control_failed",
                f"真实编队页已要求，但MAA未启动; 作业={os.path.basename(job)}", mode=mode,
                record_attempt=False,
                discard_attempt=job,
            )
            return "maa_control_failed"
        checkpoint()
        result = verify_battle(timeout=300)
        if _LAST_VERIFY_ENTERED_BATTLE:
            # 不论本作业最后成功或失败，后续最终日常都只能接受本次真实
            # 理智战斗之后的新完成证据，不能复用同日早先五链。
            _CURRENT_RUN_LAST_STAMINA_BATTLE_AT = datetime.now()
        if result == "maa_unsupported_level":
            _update_event_progress(
                event["name"],
                display_name,
                "automation_unavailable",
                f"{mode_name}; MAA最新资源仍不支持内部关卡={internal_name}; 不计作战失败",
                mode=mode,
                record_attempt=False,
                reset_attempted_jobs=True,
            )
            if _maa_task_queue_running() and not _stop_maa_task_queue(timeout=30):
                log("⛔ MAA资源错误后未能确认停止", "ERROR")
                return "maa_stop_failed"
            return "automation_unavailable"

        if result in {"maa_formation_unavailable", "maa_formation_stall"}:
            # 自动编队缺人或编队页控制停滞都发生在真正进入关卡之前。它们
            # 只证明当前作业与账号/当前控制链不兼容：加入独立排除清单后
            # 继续找下一份作业，不消耗五次真实作战预算，也不能被报告成
            # 关卡战败。
            rejection_reason = (
                "自动编队缺少干员或练度条件"
                if result == "maa_formation_unavailable"
                else "自动编队页停滞且MAA日志无推进"
            )
            if _maa_task_queue_running() and not _stop_maa_task_queue(timeout=30):
                log("⛔ 编队不兼容后未能确认停止，拒绝加载下一份作业", "ERROR")
                return "maa_stop_failed"
            dismiss_reward()
            wait(3)
            if mode == "challenge":
                cleared, perfect = verify_event_challenge_cleared(event, display_name), True
            else:
                cleared, perfect = verify_event_stage_cleared(event, display_name)
            if cleared and perfect:
                _update_event_progress(
                    event["name"], display_name, "cleared",
                    f"编队不兼容后只读复核确认此前已完成; {os.path.basename(job)}",
                    mode=mode, record_attempt=False, discard_attempt=job,
                    record_incompatible_job=job,
                )
                return True
            _update_event_progress(
                event["name"], display_name, "job_incompatible",
                f"{mode_name}; {rejection_reason}; 作业={os.path.basename(job)}",
                mode=mode, record_attempt=False, discard_attempt=job,
                record_incompatible_job=job,
            )
            incompatible_jobs.append(job)
            incompatible_jobs = list(dict.fromkeys(incompatible_jobs))
            incompatible_this_run += 1
            log(
                f"⚠️ {display_name}{mode_name}作业{os.path.basename(job)}"
                f"前置不兼容（{rejection_reason}）；"
                f"不计真实战斗预算，继续搜索替代作业（本轮排除{incompatible_this_run}份）",
                "WARN",
            )
            preflight_limit = _event_preflight_rejection_limit(max_attempts)
            if incompatible_this_run >= preflight_limit:
                log(
                    f"⏭ {display_name}{mode_name}本轮已排除{incompatible_this_run}份"
                    f"编队不兼容作业（安全上限{preflight_limit}）；"
                    "未发生战败，留待后续补充兼容作业",
                    "WARN",
                )
                return "no_job"
            continue

        # 只有已进入或产生可归因战斗结果的作业才占用真实战斗预算。
        # 未知技术终态仍会在下方冻结，避免重复扣理智。
        if result in {"perfect", "failed", "leaked", "maa_control_stall"}:
            used_jobs.append(job)

        # 这两类结果能够明确归因到当前作业，而不是总控本身：
        # - 自动编队不满足该作业要求：换一份账号可用的作业；
        # - 已进入战斗但当前作业控制死锁：停止本作业后换不同策略。
        # 它们仍占用“不同作业”预算，但编队前置失败不记作关卡战败。
        retryable_maa_job_error = result == "maa_control_stall"
        if isinstance(result, str) and result.startswith("maa_") and not retryable_maa_job_error:
            _update_event_progress(
                event["name"], display_name, "technical_error",
                f"{mode_name}; MAA错误={result}; 作业={os.path.basename(job)}", mode=mode,
                record_attempt=False,
                discard_attempt=job,
            )
            if _maa_task_queue_running() and not _stop_maa_task_queue(timeout=30):
                log("⛔ MAA错误后未能确认停止，拒绝加载下一份作业", "ERROR")
                return "maa_stop_failed"
            log("⛔ MAA技术控制链出错，状态不可安全归因到作业；冻结后续理智消耗", "ERROR")
            return result

        # 结算同步失败或长时间处于未知页面，不等于可确认的游戏内战败。
        # 此时若自动换作业可能重复扣理智，必须交给总控冻结。
        if result in {"completed_sync_blocked", "timeout"}:
            _update_event_progress(
                event["name"], display_name, "failed",
                f"{mode_name}; 结果状态未知={result}; 作业={os.path.basename(job)}", mode=mode,
            )
            if _maa_task_queue_running() and not _stop_maa_task_queue(timeout=30):
                return "maa_stop_failed"
            log("⛔ 战斗结果无法闭环，拒绝盲目重打并冻结后续理智消耗", "ERROR")
            return result

        retryable_battle_outcome = result in {"failed", "leaked"}
        if (retryable_maa_job_error or retryable_battle_outcome) and _maa_task_queue_running():
            if not _stop_maa_task_queue(timeout=30):
                log("⛔ 当前作业未能确认停止，拒绝加载下一份作业", "ERROR")
                return "maa_stop_failed"
        dismiss_reward()
        wait(3)
        # 复刻强制重打不能让“历史已亮徽记”覆盖本次战斗失败。徽记只证明
        # 账号过去通关过；本次任务必须同时取得当前作业的成功终态。否则
        # 会出现游戏明确失败，却因白色突袭徽记早已点亮而把复刻任务写成
        # completed。先记录本次失败并切换不同作业，绝不读取历史徽记晋级。
        if force_replay and result not in {"perfect", "cleared"}:
            _update_event_progress(
                event["name"], display_name, "failed",
                f"{mode_name}; 本次强制重打结果={result}; 作业={os.path.basename(job)}; 历史徽记不作本次成功证据",
                mode=mode,
            )
            last_retry_status = "battle_failed" if result in {"failed", "leaked"} else str(result)
            if len(used_jobs) < max_attempts:
                log(
                    f"⚠️ {display_name}{mode_name}本次作业结果={result}；"
                    "历史徽记不计本次成功，切换不同作业",
                    "WARN",
                )
                continue
            return last_retry_status
        if mode == "challenge":
            cleared, perfect = verify_event_challenge_cleared(event, display_name), True
        else:
            cleared, perfect = verify_event_stage_cleared(event, display_name)
        if cleared and perfect:
            detail = f"{mode_name}模式战前确认 + MAA/结算 + 地图三星; {os.path.basename(job)}"
            _update_event_progress(event["name"], display_name, "cleared", detail, mode=mode)
            log(f"✅ {display_name}{mode_name}通关并完成图形闭环")
            return True
        _update_event_progress(
            event["name"], display_name,
            "imperfect" if cleared else "failed",
            f"{mode_name}; 战斗结果={result}; 作业={os.path.basename(job)}", mode=mode,
        )
        last_retry_status = "imperfect" if cleared else "battle_failed"
        if len(used_jobs) < max_attempts:
            log(
                f"⚠️ {display_name}{mode_name}当前作业未闭环；"
                f"排除 {os.path.basename(job)}，下一轮必须切换不同策略 "
                f"({len(used_jobs)}/{max_attempts})",
                "WARN",
            )
            continue
        log(
            f"⛔ {display_name}{mode_name}已耗尽{max_attempts}份不同作业仍未完美通关；"
            "交由总控冻结后续理智消耗",
            "ERROR",
        )
        return last_retry_status
    if navigation_failures:
        log(
            f"⛔ {display_name}{mode_name}地图导航未闭环；本轮没有把它归为战败",
            "ERROR",
        )
        return "navigation_failed"
    return last_retry_status


def _record_deferred_event_job(event, stage, mode):
    """记录单关无兼容作业；不得把它改写成战败或整条活动完成。"""
    display_name = stage["display"]
    event_run = _RUN_SUMMARY.setdefault(
        "event", {"name": event["name"], "stages": {}}
    )
    deferred = event_run.setdefault("deferred_jobs", [])
    item = {
        "stage": display_name,
        "mode": mode,
        "reason": "已无普通模式成功作业或其他兼容作业可用",
        "retry": "next_daily_run",
    }
    if item not in deferred:
        deferred.append(item)
    # 兼容旧报告字段；历史上仅 EX 关允许延后。
    if "-EX-" in display_name.upper():
        legacy = event_run.setdefault("deferred_ex_jobs", [])
        if item not in legacy:
            legacy.append(item)
    event_run["status"] = "deferred_event_job"
    event_run["detail"] = (
        f"{display_name}{'普通' if mode == 'normal' else '突袭'}无兼容作业；"
        "保留为未完成待办，不计战败，不改写后续关卡的真实执行结果"
    )
    return item


def mode_event_first_clear(event=None):
    """按活动配置逐关首通；突袭无作业可暂挂，普通阻塞不得盲目跳关。"""
    event = event or get_active_event()
    if not event:
        log("ℹ️ 当前无开放活动，跳过活动首通")
        return True
    log(f"{'='*60}\n  活动首通: {event['name']}\n{'='*60}")
    if _load_event_checkpoint_hint(event):
        log("ℹ️ 活动历史断点完整；仅复核缺少可信图形证据的关卡")
    if not verify_event_navigation_ready(event):
        log("⛔ 活动导航尚未完成真实图形验证，拒绝启动活动战斗", "ERROR")
        _RUN_SUMMARY["flow_control"] = {
            "status": "paused",
            "reason": "活动导航未通过真实图形验证",
        }
        return False
    completed_modes = []
    deferred_jobs = []
    for stage in event["stages"]:
        display_name = stage["display"]
        for mode in _event_stage_modes(event, stage):
            if mode not in completed_modes:
                completed_modes.append(mode)
            mode_name = "普通" if mode == "normal" else "突袭"
            if _event_mode_has_trusted_clear_evidence(
                event["name"], display_name, mode,
            ):
                log(
                    f"  [活动断点] {display_name}{mode_name}已有真实徽记/战后闭环证据，"
                    "直接跳过"
                )
                continue
            result = clear_event_stage(event, stage, mode=mode)
            if (
                isinstance(result, tuple)
                and len(result) >= 2
                and result[0] == "manual_required"
            ):
                prerequisite = result[1]
                log(
                    f"⏸ 活动首通暂停：{stage['display']}被前置教学关"
                    f"{prerequisite}阻挡；请手动完成后继续。",
                    "WARN",
                )
                return result
            if result == "automation_unavailable":
                log(
                    f"⏭ {stage['display']}{mode_name}已有作业，但MAA资源尚未支持；"
                    "本轮活动自动化不可执行",
                    "WARN",
                )
                return "automation_unavailable"
            if result == "no_job":
                deferred_jobs.append(
                    _record_deferred_event_job(event, stage, mode)
                )
                if mode == "challenge":
                    log(
                        f"⏭ {display_name}{mode_name}已无兼容作业；保留为未完成待办，"
                        "继续检查后续已解锁关卡，不冻结整条活动链",
                        "WARN",
                    )
                    continue
                log(
                    f"⏸ {display_name}{mode_name}尚未首通且已无兼容作业；"
                    "后续节点可能未解锁，本轮停止盲目跳关",
                    "WARN",
                )
                return "deferred_event_job"
            if result is not True:
                log(f"⛔ 活动首通在{stage['display']}{mode_name}停止: {result}", "ERROR")
                _RUN_SUMMARY["flow_control"] = {
                    "status": "paused",
                    "reason": f"活动首通在{stage['display']}{mode_name}停止: {result}",
                }
                return False
    readable_modes = "、".join(
        "普通" if mode == "normal" else "突袭" for mode in completed_modes
    )
    if deferred_jobs:
        pending = "、".join(
            f"{item['stage']}{'普通' if item['mode'] == 'normal' else '突袭'}"
            for item in deferred_jobs
        )
        log(
            f"⚠️ {event['name']}其余可执行关卡已检查；仍有无兼容作业待办: {pending}",
            "WARN",
        )
        return "deferred_event_job"
    log(f"✅ {event['name']}当前配置关卡的{readable_modes}首通均已完成")
    return True


def mode_event_today():
    """活动日闭环：断点首通→配置收益关耗尽理智→日常/基建收尾。"""
    event = get_active_event()
    if not event:
        log("❌ 当前没有开放活动", "ERROR")
        return False
    _RUN_SUMMARY["flow_target"] = {
        "type": "event",
        "name": event["name"],
        "decided_at": datetime.now().isoformat(timespec="seconds"),
    }
    _RUN_SUMMARY.setdefault(
        "event",
        {"name": event["name"], "stages": {}, "navigation": {"status": "pending"}},
    )
    log(f"{'='*60}\n  今日活动恢复: {event['name']}首通→剩余理智刷取\n{'='*60}")
    write_status("活动真实导航与首通", event["name"])
    if not mode_event_first_clear(event):
        _RUN_SUMMARY["flow_control"] = {
            "status": "paused",
            "reason": "活动普通/突袭未全部闭环（可能理智不足或页面验证失败）",
        }
        log("⏸ 活动断点模式暂停：保留已完成进度，不执行后续刷取或日常链", "WARN")
        return False

    # 不再为了估算次数退出活动地图。主页理智OCR既不稳定，也会增加误入其他页的
    # 状态转换；99只是安全上限，MAA禁用药剂/源石并会在理智不足时自然结束。
    runs = 99
    if _restore_completed_event_farm(event):
        log(f"→ {event['farm_stage']}连续代理已有当日完成断点，直接恢复最终日常/Award")
    else:
        log(f"→ 从当前活动地图刷{event['farm_stage']}，直至理智不足（Series=AUTO）")
        write_status("活动剩余理智刷取", f"{event['farm_stage']} 至理智不足")
        if mode_event(stage_code=event["farm_stage"], times=runs) is False:
            _RUN_SUMMARY["flow_control"] = {"status": "paused", "reason": f"活动{event['farm_stage']}多次代理未确认完成"}
            log("⏸ 活动刷取未闭环，暂停在日常收尾前", "ERROR")
            return False

    # 消耗理智后每日任务/基建会产生新内容，必须在最终报告和关闭窗口前再清一次。
    log("→ 活动理智消耗完成，执行一次最终日常/基建清理")
    write_status("活动后日常收尾", "基建/招募/商店/任务奖励")
    _set_final_daily_completion_boundary()
    _prepare_daily_maa_boundary(f"活动{event['farm_stage']}刷取结束，切回日常TaskQueue")
    if mode_daily() is not True:
        _RUN_SUMMARY["flow_control"] = {
            "status": "paused",
            "reason": "活动后最终日常未确认全部完成（含Award）",
        }
        log("⏸ 最终日常/Award未闭环；停止后续操作，进入默认清理并如实弹窗", "ERROR")
        return False
    return True


def mode_event(stage_code=None, times=10, _expiring_potion_retries=0):
    """活动刷取"""
    global _CURRENT_RUN_LAST_STAMINA_BATTLE_AT
    log("=" * 60)
    log(f"  场景: 活动刷取 {stage_code or '自动检测'} x{times}")
    log("=" * 60)
    
    # 如果未指定关卡，按日期配置选择当前活动最高关；不再依赖过时的活动名硬编码。
    event = get_active_event()
    if not stage_code:
        if not event:
            log("❌ 未检测到当前活动", "ERROR")
            return False
        stage_code = event["farm_stage"]
        log(f"  当前活动={event['name']}, 刷取关卡={stage_code}")

    # 新活动关不依赖 MAA 的关卡列表：先在游戏中图形确认普通代理详情页，
    # 再使用空 StagePlan 让 MAA 接管当前关卡和 Series=AUTO。
    # A CLI ``event --stage`` is an explicit user target.  It must not be
    # rebound to the date-selected event merely because an old/overlapping
    # event config happens to contain the same stage code: the terminal card
    # may already have switched to a newer event while MAA can still navigate
    # the requested stage from its Fight list.  Internal full/event_today runs
    # keep the graphical current-stage route because they intentionally follow
    # the event selected by ``get_active_event``.
    active_plan = _ACTIVE_EXECUTION_PLAN or {}
    explicit_cli_stage = bool(
        active_plan.get("mode") == "event"
        and active_plan.get("requested_stage")
        and str(active_plan.get("requested_stage")) == str(stage_code)
    )
    use_current_stage = bool(
        event
        and stage_code in set(_event_stage_names(event))
        and not explicit_cli_stage
    )
    if explicit_cli_stage:
        log(f"  [显式关卡] {stage_code}按MAA关卡列表执行，不受活动卡片识别结果改写")
    if use_current_stage:
        if not _prepare_event_farm_stage(event, stage_code):
            return False
    elif not goto_main_menu():
        return False

    reload_maa_after_config_switch(f"切换到活动刷取{stage_code or 'AUTO'}")
    
    farm_summary = _RUN_SUMMARY.setdefault("event", {}).setdefault("farm", {})
    farm_summary.update({"stage": stage_code, "requested_runs": times, "series": "AUTO", "status": "running"})
    try:
        with temporary_maa_config(
            lambda cfg: _configure_fight(
                cfg, stage_code, times, current_stage=use_current_stage,
            ),
            f"仅Fight {stage_code}，最多{times}次，"
            f"{'当前普通关' if use_current_stage else '关卡列表'}",
        ):
            if not run_maa_daily_tasks(enabled_tasks={"Fight"}):
                log("❌ MAA活动任务启动失败", "ERROR")
                farm_summary["status"] = "maa_start_failed"
                return False
            result = wait_maa_complete(timeout=times * 120 + 300, prestarted_boundary=True)
            if result is not True:
                log(f"❌ 活动任务未确认完成: {result}", "ERROR")
                farm_summary["status"] = "failed"
                farm_summary["detail"] = str(result)
                return False
    except Exception as e:
        log(f"❌ 配置或执行活动关失败: {e}", "ERROR")
        farm_summary["status"] = "error"
        farm_summary["detail"] = str(e)
        return False

    current_fight_log = _get_current_maa_run_log()
    fight_evidence = _parse_fight_times_evidence(current_fight_log)
    if not fight_evidence or fight_evidence.get("runs", 0) < 1:
        # MAA禁用自动用药；单关代理因理智不足零次结束时，游戏会停在恢复
        # 弹窗。用户只授权红色临期药剂，因此这里必须同时确认弹窗语义和
        # 红标签后才用一份，并重新走完整关卡定位。普通药和源石仍禁止。
        restore_path = shot(f"event_no_fight_{stage_code}")
        restore_result = _open_restore_and_consume_expiring_potion_after_zero_fight(
            stage_code, restore_path,
        )
        if _expiring_potion_retries < 3 and restore_result in ("retry_stage", True):
            farm_summary.update({
                "status": "retry_after_expiring_potion",
                "detail": "零次Fight，已图形确认并使用1份红色临期药剂",
            })
            return mode_event(
                stage_code=stage_code,
                times=times,
                _expiring_potion_retries=_expiring_potion_retries + 1,
            )
        if restore_result == "stamina":
            farm_summary.update({
                "status": "stamina_exhausted",
                "actual_runs": 0,
                "sanity_consumed": 0,
                "detail": "精确关卡详情/恢复窗确认理智不足；未使用普通药或源石",
            })
            log(f"ℹ️ 活动{stage_code}因理智不足自然停止；保留下一关断点")
            return "stamina_exhausted"
        farm_summary.update({
            "status": "unverified",
            "detail": "MAA虽提示任务链结束，但没有FightTimes真实完成次数证据",
        })
        log(
            f"❌ 活动{stage_code}没有真实代理完成次数证据，拒绝写入复刻断点",
            "ERROR",
        )
        return False
    configured_cost = int(
        ((event or {}).get("sanity_costs") or {}).get(stage_code, 0) or 0
    )
    if not configured_cost and event and stage_code == event.get("farm_stage"):
        configured_cost = int(event.get("farm_cost", 0) or 0)
    drop_runs = _parse_stage_drops_run_count(current_fight_log, stage_code)
    actual_runs = max(int(fight_evidence["runs"]), int(drop_runs or 0))
    actual_cost = (
        actual_runs * configured_cost
        if configured_cost else int(fight_evidence["sanity_cost"])
    )
    farm_summary.update({
        "actual_runs": actual_runs,
        "sanity_consumed": actual_cost,
        "series_batches": (
            [actual_runs]
            if drop_runs > int(fight_evidence["runs"])
            else fight_evidence["series_batches"]
        ),
    })
    sanity_matches = re.findall(
        r"Current Sanity: (\d+) , Max Sanity: (\d+)", current_fight_log or ""
    )
    if sanity_matches:
        farm_summary["sanity_remaining"] = int(sanity_matches[-1][0])
    farm_summary["status"] = "completed"
    _CURRENT_RUN_LAST_STAMINA_BATTLE_AT = datetime.now()
    if event and stage_code == event.get("farm_stage") and times > 1:
        _save_event_farm_checkpoint(
            event, farm_summary.get("actual_runs", 0),
            farm_summary.get("sanity_remaining"),
            f"本轮MAA Fight任务链完成；真实代理{farm_summary.get('actual_runs', 0)}次，"
            f"消耗理智{farm_summary.get('sanity_consumed', '未识别')}",
            sanity_consumed=farm_summary.get("sanity_consumed"),
            series_batches=farm_summary.get("series_batches"),
        )
    log(
        f"✅ 活动{stage_code}执行结束：请求上限{times}次，"
        f"真实完成{farm_summary.get('actual_runs', 0)}次，"
        f"消耗理智{farm_summary.get('sanity_consumed', '未识别')}"
    )
    return True


def _update_event_task_replay(event, stage, status, detail=""):
    """持久化复刻活动任务重打断点；旧首通记录不能代替本次复刻重打。"""
    data = _load_event_progress()
    event_state = data.setdefault("events", {}).setdefault(event["name"], {})
    replay = event_state.setdefault("task_replay", {})
    replay.setdefault("event_start", event.get("start"))
    base_stage = str(stage).split(":", 1)[0]
    mode = "challenge" if ":challenge" in str(stage) else "normal"
    cost = int((event.get("sanity_costs") or {}).get(base_stage, 0) or 0)
    record = {
        "status": status,
        "detail": detail,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if status == "completed" and cost:
        mode_progress = (
            (((event_state.get("stages") or {}).get(base_stage) or {}).get("modes") or {})
            .get(mode, {}) or {}
        )
        attempted_jobs = list(dict.fromkeys(mode_progress.get("attempted_jobs") or []))
        total_runs = max(1, len(attempted_jobs)) if mode == "challenge" else 1
        failed_runs = max(0, total_runs - 1)
        record.update({
            "actual_runs": 1,
            "failed_runs": failed_runs,
            "total_runs": total_runs,
            "sanity_consumed": cost,
            "total_sanity_consumed": total_runs * cost,
        })
    replay.setdefault("stages", {})[stage] = record
    data["last_update"] = datetime.now().isoformat(timespec="seconds")
    _atomic_write_json(EVENT_PROGRESS_FILE, data)
    run = _RUN_SUMMARY.setdefault("event", {}).setdefault("task_replay", {})
    run.setdefault("stages", {})[stage] = deepcopy(record)

    # task_replay is the per-rerun ledger, while stages is the per-stage visual
    # state consumed by recovery/reporting.  Keep both views synchronized so a
    # successful proxy replay cannot disappear merely because no challenge
    # probe happened for that stage.
    stage_status = "cleared" if status == "completed" else status
    _update_event_progress(
        event["name"], base_stage, stage_status, detail, mode=mode,
    )


def _completed_event_task_replays(event):
    data = _load_event_progress()
    replay = ((data.get("events", {}).get(event["name"], {}) or {}).get("task_replay") or {})
    if replay.get("event_start") != event.get("start"):
        return set()
    return {
        stage for stage, record in (replay.get("stages") or {}).items()
        if (record or {}).get("status") == "completed"
    }


def _event_task_replay_deferred_today(event, checkpoint_key, now=None):
    """Respect the per-game-day retry budget after a challenge was deferred."""
    now = now or datetime.now()
    replay = (
        (_load_event_progress().get("events", {}).get(event["name"], {}) or {})
        .get("task_replay", {}) or {}
    )
    record = ((replay.get("stages") or {}).get(checkpoint_key) or {})
    # Older runs wrote `failed` after clear_event_stage had already exhausted
    # its full retry loop.  Treat that legacy status as the same-day deferred
    # budget too, rather than reopening the whole challenge on process restart.
    if record.get("status") not in {"deferred", "failed"}:
        return False
    # 地图/控件/MAA等技术故障从未消耗“不同作业战斗预算”。旧版曾把
    # navigation_failed写成当日预算耗尽，导致修复后仍要等到次日才能
    # 复测。技术记录必须立即允许恢复，只有真正可归因的作业/战斗预算
    # 耗尽才受同游戏日延期门约束。
    detail = str(record.get("detail") or "")
    if any(marker in detail for marker in (
        "navigation_failed", "technical", "maa_", "timeout", "sync_blocked",
    )):
        return False
    try:
        updated_at = datetime.fromisoformat(record.get("updated_at", ""))
    except (TypeError, ValueError):
        return False
    return _game_day_key(updated_at) == _game_day_key(now)


def mode_event_rerun_tasks(event):
    """复刻活动：按任务重置要求，把每个耗理智关用代理重新完成一次。"""
    stages = list(event.get("replay_stages") or [])
    if not stages:
        log(f"❌ {event['name']}没有配置复刻任务重打关卡", "ERROR")
        return False
    if not verify_event_navigation_ready(event):
        return False

    completed = _completed_event_task_replays(event)
    # 恢复同一复刻的持久断点到本轮报告；旧版记录没有结构化理智时，按
    # 已确认的关卡固定消耗补齐，不从请求次数反推。
    replay_data = (
        (_load_event_progress().get("events", {}).get(event["name"], {}) or {})
        .get("task_replay", {}) or {}
    )
    run_replay = _RUN_SUMMARY.setdefault("event", {}).setdefault("task_replay", {})
    run_replay["event_start"] = replay_data.get("event_start")
    run_replay["stages"] = deepcopy(replay_data.get("stages") or {})
    for key, record in run_replay["stages"].items():
        base_stage = str(key).split(":", 1)[0]
        cost = int((event.get("sanity_costs") or {}).get(base_stage, 0) or 0)
        if (record or {}).get("status") == "completed" and cost:
            record.setdefault("actual_runs", 1)
            record.setdefault("sanity_consumed", cost)
    for index, display_name in enumerate(stages, 1):
        if display_name in completed:
            log(f"  [复刻任务] {display_name}本次复刻已有代理完成证据，跳过")
            continue
        write_status(
            f"复刻活动代理重打: {display_name}",
            f"{index}/{len(stages)} | 每关真实代理1次",
        )
        log(f"\n>>> [复刻任务 {index}/{len(stages)}] {display_name} 代理1次")
        result = mode_event(stage_code=display_name, times=1)
        if result == "stamina_exhausted":
            _update_event_task_replay(
                event, display_name, "pending_stamina",
                "进入精确关卡后确认理智不足；未开战，保留为下一恢复点",
            )
            run_replay["next_stage"] = display_name
            run_replay["status"] = "stamina_exhausted"
            log(
                f"ℹ️ 复刻任务运行至{display_name}前理智不足；"
                "本轮正常收口，下一次从该关继续",
                "WARN",
            )
            return "stamina_exhausted"
        if result is not True:
            _update_event_task_replay(
                event, display_name, "failed", f"代理流程未闭环: {result}"
            )
            log(f"⛔ {display_name}代理重打失败，冻结后续理智消耗", "ERROR")
            return False
        cost = int((event.get("sanity_costs") or {}).get(display_name, 0) or 0)
        _update_event_task_replay(
            event, display_name, "completed",
            f"MAA当前关卡代理1次完成；消耗理智{cost or '未识别'}",
        )
        completed.add(display_name)

    # 复刻任务列表还会单独要求部分高难关的突袭模式。突袭没有代理指挥，
    # 因此这里只对契约列出的精确目标调用MAA作业；旧突袭徽记仅证明历史
    # 通关，不能代替本次复刻的重新完成证据。
    pending_challenges = []
    for display_name in event.get("required_challenge_replays", []):
        checkpoint_key = f"{display_name}:challenge"
        if checkpoint_key in completed:
            log(f"  [复刻任务] {display_name}突袭本次复刻已有完成证据，跳过")
            continue
        if _event_task_replay_deferred_today(event, checkpoint_key):
            pending_challenges.append({"stage": display_name, "reason": "today_retry_budget_exhausted"})
            log(
                f"  [复刻任务] {display_name}突袭本游戏日已耗尽不同作业重试预算，"
                "保留待补并继续活动收益关",
                "WARN",
            )
            continue
        stage = next(
            (item for item in event.get("stages", []) if item["display"] == display_name),
            None,
        )
        if not stage:
            log(f"❌ 复刻突袭目标未配置关卡: {display_name}", "ERROR")
            return False
        write_status("复刻活动突袭重打", f"{display_name} | MAA精确作业")
        log(f"\n>>> [复刻任务突袭] {display_name} 重新完成一次")
        result = clear_event_stage(
            event, stage, mode="challenge", force_replay=True,
        )
        if result is not True:
            if result in {
                "navigation_failed", "maa_stop_failed", "completed_sync_blocked", "timeout",
            } or (isinstance(result, str) and result.startswith("maa_")):
                _update_event_task_replay(
                    event, checkpoint_key, "technical_error",
                    f"突袭重打技术链未闭环: {result}; 未授权继续刷取",
                )
                log(
                    f"⛔ {display_name}突袭技术链失败({result})；"
                    "冻结后续理智消耗，修复后从本关恢复",
                    "ERROR",
                )
                return False
            _update_event_task_replay(
                event, checkpoint_key, "deferred", f"突袭重打未闭环: {result}; 本游戏日重试预算已耗尽"
            )
            pending_challenges.append({"stage": display_name, "reason": str(result)})
            log(
                f"⚠️ {display_name}突袭尚未开始战斗，保留为待补；"
                "不阻断已授权活动收益关刷取",
                "WARN",
            )
            continue
        _update_event_task_replay(
            event, checkpoint_key, "completed", "MAA突袭作业 + 结算/徽记闭环"
        )
        completed.add(checkpoint_key)

    replay_summary = _RUN_SUMMARY.setdefault("event", {}).setdefault("task_replay", {})
    replay_summary["pending_required_challenges"] = pending_challenges
    if pending_challenges:
        log(
            f"⚠️ {event['name']}普通代理重打已完成；"
            f"仍有{len(pending_challenges)}个指定突袭待补",
            "WARN",
        )
    else:
        log(f"✅ {event['name']}全部耗理智关卡代理与指定突袭重打均已完成")
    return True


def claim_event_task_rewards(event):
    """领取本轮已完成的活动任务奖励；未确认任务页时拒绝盲点。"""
    summary = _RUN_SUMMARY.setdefault("event", {}).setdefault("task_rewards", {})
    summary.update({"status": "checking", "claimed_buttons": 0})
    if not goto_event_map(event):
        summary.update({"status": "failed", "detail": "无法进入活动地图"})
        return False

    # 从地图回到活动大厅；若当前仍是关卡详情，先关详情再退一次。
    back()
    wait(4)
    p = shot("event_task_lobby")
    items = ocr(p)
    text = " ".join(str(value) for value, _x, _y in items)
    task_pos = None
    for keyword in event.get("task_keywords", []):
        task_pos = find_text(items, keyword, exact=False)
        if task_pos:
            break
    if not task_pos:
        # 地图上若只关闭了详情抽屉，再返回一次才是活动大厅。
        if any(name in text for name in _event_stage_names(event)):
            back()
            wait(4)
            p = shot("event_task_lobby_retry")
            items = ocr(p)
            text = " ".join(str(value) for value, _x, _y in items)
            for keyword in event.get("task_keywords", []):
                task_pos = find_text(items, keyword, exact=False)
                if task_pos:
                    break
    if not task_pos:
        summary.update({
            "status": "failed",
            "detail": f"活动大厅未识别任务入口: {text[:160]}",
        })
        log(f"❌ {event['name']}未识别到活动任务入口", "ERROR")
        return False

    tap(*task_pos)
    wait(4)
    claimed = 0
    page_confirmed = False
    for attempt in range(20):
        p = shot(f"event_task_claim_{attempt}")
        items = ocr(p)
        text = " ".join(str(value) for value, _x, _y in items)
        state = get_state()
        if state == "story" or "跳过" in text:
            log("  [活动领奖] 任务入口触发了活动剧情，先跳过剧情再确认任务页")
            if not skip_story():
                tap(*POS_SKIP)
                wait(1)
                tap(*POS_SKIP_CONFIRM)
                wait(5)
            continue
        page_confirmed = page_confirmed or any(
            keyword in text for keyword in event.get("task_keywords", [])
        ) or any(token in text for token in (
            "任务", "通关活动关卡", "领取", "旅行者的背包", "愿望清单",
        ))
        claim_all = find_text(items, "领取全部", exact=False)
        claim_positions = [
            (x, y) for value, x, y in items
            if "领取" in str(value) and 900 <= x <= 1880 and 100 <= y <= 1000
        ]
        pos = claim_all or (claim_positions[0] if claim_positions else None)
        if pos:
            tap(*pos)
            claimed += 1
            wait(3)
            # 领取活动角色时是“角色展示→获得物资汇总”两层；只关闭一层会
            # 把后续活动刷取和最终日常都卡在奖励页。
            _drain_reward_sequence()
            continue
        if not page_confirmed and attempt < 19:
            # 新开放内容首次进入可能先播放加载动画/活动剧情。没有任务页证据时
            # 只等待或处理已确认的剧情，不在白屏/动画上盲点，也不立即误报失败。
            wait(3)
            continue
        break

    if not page_confirmed:
        summary.update({"status": "failed", "detail": "点击后未确认活动任务页"})
        log("❌ 点击活动任务入口后未确认任务页", "ERROR")
        return False
    summary.update({
        "status": "completed",
        "claimed_buttons": claimed,
        "detail": "已领取当前所有可领取项目" if claimed else "任务页确认无可领取按钮",
    })
    log(f"✅ 活动任务奖励检查完成：点击领取{claimed}次")
    return True

# ============================================================
# 场景模式: 保全派驻 (SSS - Stationary Security Service)
# ============================================================

# 保全派驻作业文件路径 (MAA安装目录下)
SSS_COPILOT_DIR = os.path.join(os.path.dirname(MAA_PATH), "resource", "copilot")
SSS_ONLINE_JOB_DIR = os.path.join(BASE, "outputs", "sss_copilot_jobs")
SSS_FORMATION_BRIDGE_DIR = os.path.join(BASE, "outputs", "sss_formation_bridge")
# 可识别区域与当前MAA作业候选。真正开放区域必须从本期游戏页面读取，
# 不能再把资源目录存在或历史进度当成“本期开放”的证据。
SSS_REGION_CATALOG = {
    "荒废灯塔": {
        "dir": os.path.join("old", "荒废灯塔_Abandoned_Lighthouse"),
        "aliases": ["荒废灯塔", "审判庭", "ABANDONED", "LIGHTHOUSE"],
        "jobs": [
            "SSS_荒废灯塔_浊蒂纯艾版.json",
            "SSS_荒废灯塔-重岳核v2.0（兼容应急）.json",
        ],
    },
    "日达诺夫园区": {
        "dir": "日达诺夫园区_Zhdanov_Industrial_Park",
        "aliases": ["日达诺夫", "索罗科夫", "SOROKOV", "ZHDANOV"],
        "jobs": [],
        # 2026-08-18 当前实机页对应的新作业；下载后仍必须验证type/stage_name/6关结构。
        "prts_ids": [100225],
        "priority": 100,
    },
    "塔山农业实验平台": {
        "dir": "塔山农业实验平台_Tower_Mountains_Agricultural_Experimental_Platform",
        "aliases": ["塔山", "TOWER", "MOUNTAINS", "MOUTOKER"],
        "jobs": [
            "SSS_（新）塔山农业实验平台_荒芜拉普兰德+澄闪+浊心斯卡蒂_智能空域控制机.json",
            "SSS_塔山农业实验平台_浊蒂纯艾澄闪银灰+提丰.json",
        ],
    },
    "阿尔斯特甜品制作平台": {
        "dir": "阿尔斯特甜品制作平台_Alsterii_Manufacture_Platform",
        "aliases": ["阿尔斯特", "ALSTER", "ABMP"],
        "jobs": [
            "SSS_（新）阿尔斯特甜品制作平台_怒潮凛冬+圣聆初雪_溢能回收转化器.json",
            "SSS_阿尔斯特甜品制作平台_浊蒂锏版.json",
        ],
    },
    "施佩尔山脚": {
        "dir": "施佩尔山脚_Spier_Foothills",
        "aliases": ["施佩尔", "SPIER", "FOOTHILLS"],
        "jobs": [
            "SSS_施佩尔山脚_逻各斯+圣聆初雪+浊心斯卡蒂_冷爆机.json",
            "SSS_任务专用_施佩尔山脚_荒芜拉普兰德+圣聆初雪+浊心斯卡蒂_能量扰动放大器.json",
        ],
    },
    "雷神工业测试平台": {
        "dir": "雷神工业测试平台_Raythean_Industries_Test_Platform",
        "aliases": ["雷神工业", "雷神", "RAYTHEAN", "INDUSTRIES"],
        "jobs": [
            "SSS_雷神工业测试平台_逻各斯+遥_便携式医疗设备.json",
            "SSS_雷神工业测试平台.json",
        ],
    },
}

# PRTS 的 SSS 作业只描述核心、职业工具人数和禁用名单，游戏本身仍要求
# 首次手动选满20人。这里保存本账号已核对的高练候选池；三名核心固定，
# 工具位按“高练度优先、同练度档低费用优先”的顺序尝试。只有档案结构、
# 三名核心和各职业工具人数都与在线作业一致时才允许自动点击。
SSS_FORMATION_PROFILES = {
    "日达诺夫园区": [
        {"name": "斩业星熊", "profession": "defender", "skill": 1, "core": True},
        {"name": "圣聆初雪", "profession": "caster", "skill": 2, "core": True},
        {"name": "遥", "profession": "supporter", "skill": 2, "core": True},
        {"name": "凛冬", "alternates": ["德克萨斯", "焰尾"], "profession": "vanguard", "skill": 1},
        {"name": "德克萨斯", "alternates": ["焰尾", "推进之王"], "profession": "vanguard", "skill": 1},
        {"name": "焰尾", "alternates": ["推进之王", "凛冬"], "profession": "vanguard", "skill": 1},
        {"name": "塞雷娅", "alternates": ["黍", "临光"], "profession": "defender", "skill": 1},
        {"name": "黍", "alternates": ["临光", "古米"], "profession": "defender", "skill": 1},
        {"name": "流星", "alternates": ["蓝毒", "灰喉"], "profession": "sniper", "skill": 1},
        {"name": "蓝毒", "alternates": ["灰喉", "能天使"], "profession": "sniper", "skill": 1},
        {"name": "灰喉", "alternates": ["能天使", "红云"], "profession": "sniper", "skill": 1},
        {"name": "能天使", "alternates": ["红云", "杰西卡"], "profession": "sniper", "skill": 1},
        {"name": "艾雅法拉", "alternates": ["刻俄柏", "澄闪"], "profession": "caster", "skill": 1},
        {"name": "刻俄柏", "alternates": ["澄闪", "卡达"], "profession": "caster", "skill": 1},
        {"name": "澄闪", "alternates": ["卡达", "夜烟"], "profession": "caster", "skill": 1},
        {"name": "塑心", "alternates": ["浊心斯卡蒂", "安洁莉娜"], "profession": "supporter", "skill": 1},
        {"name": "浊心斯卡蒂", "alternates": ["安洁莉娜", "酒神"], "profession": "supporter", "skill": 1},
        {"name": "安洁莉娜", "alternates": ["酒神", "铃兰"], "profession": "supporter", "skill": 1},
        {"name": "酒神", "alternates": ["铃兰", "麦哲伦"], "profession": "supporter", "skill": 1},
        {"name": "铃兰", "alternates": ["麦哲伦", "巫恋"], "profession": "supporter", "skill": 1},
    ],
}

SSS_FORMATION_PROFESSIONS = {
    "vanguard", "guard", "defender", "sniper",
    "caster", "medic", "supporter", "specialist",
}
# 兼容旧调用；mode_security只遍历真实页面发现的本期区域。
SSS_REGIONS = SSS_REGION_CATALOG
SSS_MAIN_MARKERS = (
    "保全派驻", "安保派驻", "周期任务", "荒废灯塔", "日达诺夫", "SOROKOV",
    "塔山", "阿尔斯特", "施佩尔", "雷神工业",
    "TOWER", "MOUNTAINS", "ALSTER", "SPIER", "FOOTHILLS", "RAYTHEAN",
)
# 保全派驻进度文件
SSS_PROGRESS_FILE = os.path.join(BASE, "outputs", "保全派驻进度.json")


def load_sss_progress():
    """加载保全派驻进度"""
    default = {
        "last_run": "",
        "completed_regions": [],
        "current_period": "",
        "area_period": "",
        "reward_cycle": "",
        "reward_counts": {"strip": 0, "device": 0},
        "reward_capped": False,
    }
    try:
        if os.path.exists(SSS_PROGRESS_FILE):
            with open(SSS_PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return default


def save_sss_progress(prog):
    """保存保全派驻进度"""
    try:
        with open(SSS_PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(prog, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"  [进度] 保存失败: {e}", "WARN")


def parse_sss_period(page_text):
    """从当前游戏页面生成稳定周期键，不再按旧的每月1/16日推断。"""
    text = str(page_text or "")
    season = re.search(r"#\s*(\d+)", text)
    end_date = re.search(r"(20\d{2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{1,2})", text)
    if season and end_date:
        year, month, day = (int(value) for value in end_date.groups())
        return f"season-{int(season.group(1))}-end-{year:04d}-{month:02d}-{day:02d}"
    return None


def get_current_sss_reward_cycle(now=None):
    """保全清理报酬每月16日04:00刷新；区域赛季结束日不等于奖励周期。"""
    now = now or datetime.now()
    boundary = now.replace(day=16, hour=4, minute=0, second=0, microsecond=0)
    if now < boundary:
        previous_month_last = now.replace(day=1) - timedelta(days=1)
        boundary = previous_month_last.replace(day=16, hour=4, minute=0, second=0, microsecond=0)
    return f"reward-{boundary:%Y-%m-%dT%H:%M}"


def parse_sss_reward_counts(page_text):
    """从保全主页读取数据增补条/仪进度；只接受固定上限60与24附近的数字。"""
    text = str(page_text or "")
    compact = re.sub(r"\s+", "", text)
    # 大号空心数字0在该页面经RapidOCR稳定识别成英文字母O；只在固定
    # “/60、/24”奖励分母前做窄范围纠正，避免污染其他页面文本。
    compact = re.sub(r"[OＯ〇]/(?=60|24)", "0/", compact, flags=re.I)
    result = {"strip": None, "device": None}
    patterns = {
        "strip": (
            r"数据增补条[^0-9]{0,30}(\d{1,3})\s*/\s*60",
            r"(\d{1,3})\s*/\s*60",
        ),
        "device": (
            r"数据增补仪[^0-9]{0,30}(\d{1,3})\s*/\s*24",
            r"(\d{1,3})\s*/\s*24",
        ),
    }
    for key, variants in patterns.items():
        for pattern in variants:
            match = re.search(pattern, compact, re.I)
            if match:
                value = int(match.group(1))
                cap = 60 if key == "strip" else 24
                if 0 <= value <= cap:
                    result[key] = value
                    break
    return result


def read_sss_reward_counts_from_image(image_path, tag="sss_reward_counts"):
    """放大主页左下奖励ROI再读数；全屏OCR会漏掉空心大号数字。"""
    try:
        from PIL import Image
        with Image.open(image_path) as source:
            image = source.convert("RGB")
            width, height = image.size
            roi = image.crop((0, int(height * 0.80), int(width * 0.42), height))
            roi = roi.resize((roi.width * 2, roi.height * 2))
            roi_path = os.path.join(SCREEN_DIR, f"{tag}_{int(time.time()) % 100000}.png")
            roi.save(roi_path)
        items = ocr(roi_path)
        counts = parse_sss_reward_counts(" ".join(text for text, _, _ in items))
        # RapidOCR会把两枚大号0都排在两个分母之前，纯文本顺序因此变成
        # “O O /60 /24”。按画面坐标把每个分母与左侧最近的数字配对。
        # 坐标结果必须覆盖纯文本结果：纯文本曾把右侧的24错配给左侧/60，
        # 得到不可能的“24/60、未知/24”。
        for key, cap in (("strip", 60), ("device", 24)):
            value = _sss_reward_value_from_ocr_items(items, cap)
            if value is None:
                continue
            counts[key] = value
        return counts
    except Exception as exc:
        log(f"  [保全奖励ROI] 读取失败: {exc}", "WARN")
        return {"strip": None, "device": None}


def _sss_reward_value_from_ocr_items(items, cap):
    """按坐标把保全奖励分子绑定到对应分母，避免跨卡片串读。"""
    normalized = []
    for text, x, y in items or []:
        token = re.sub(r"\s+", "", str(text or "")).upper()
        token = token.replace("Ｏ", "O").replace("〇", "O").replace("／", "/")
        normalized.append((token, x, y))

    # 同一OCR框直接给出“0/60”或“O/24”时优先采用。
    for token, _, _ in normalized:
        match = re.fullmatch(rf"(\d{{1,3}}|O)/{int(cap)}", token)
        if not match:
            continue
        value = 0 if match.group(1) == "O" else int(match.group(1))
        if 0 <= value <= cap:
            return value

    denominators = [
        (x, y)
        for token, x, y in normalized
        if re.fullmatch(rf"/?{int(cap)}", token)
    ]
    for dx, dy in denominators:
        candidates = []
        for token, x, y in normalized:
            if x >= dx or abs(y - dy) > 140 or not re.fullmatch(r"(?:\d{1,3}|O)", token):
                continue
            value = 0 if token == "O" else int(token)
            if 0 <= value <= cap:
                candidates.append((x, value))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
    return None


def _sss_full_clear_evidence(page_text, image_path=None, before_counts=None, maa_log=None):
    """用MAA保全终态和游戏详情页/奖励增量共同确认六层完整清理。"""
    compact = re.sub(r"\s+", "", str(page_text or "")).upper()
    counts = parse_sss_reward_counts(page_text)
    if image_path:
        image_counts = read_sss_reward_counts_from_image(
            image_path, tag="sss_result_rewards"
        )
        for key in ("strip", "device"):
            if image_counts.get(key) is not None:
                counts[key] = image_counts[key]

    detail_page = "BESTRECORD" in compact and "周期清理记录" in compact
    page_six_of_six = bool(re.search(r"6\s*/\s*6", compact))
    maa_game_pass = "SSSGamePass" in str(maa_log or "")
    before_counts = before_counts or {}
    rewards_increased = any(
        isinstance(before_counts.get(key), int)
        and isinstance(counts.get(key), int)
        and counts[key] > before_counts[key]
        for key in ("strip", "device")
    )
    # 游戏页6/6本身足够；OCR漏掉首个6时，必须同时具备MAA的SSSGamePass、
    # 正确区域详情页以及奖励增长，不能仅凭AllTasksCompleted认定成功。
    completed = detail_page and (
        page_six_of_six or (maa_game_pass and rewards_increased)
    )
    return {
        "completed": completed,
        "counts": counts,
        "detail_page": detail_page,
        "page_six_of_six": page_six_of_six,
        "maa_game_pass": maa_game_pass,
        "rewards_increased": rewards_increased,
    }


def sss_rewards_capped(counts):
    return bool(counts and counts.get("strip") == 60 and counts.get("device") == 24)


def _sss_retry_allowed(consecutive_failures, limit=3):
    """保全实体作业允许有限概率重试；达到上限后必须停损。"""
    return int(consecutive_failures) < max(1, int(limit))


def get_current_sss_period(page_text=None):
    """获取当前保全周期键；有页面证据时只信页面，离线调用才给未知日桶。"""
    observed = parse_sss_period(page_text)
    if observed:
        return observed
    return f"unverified-{datetime.now():%Y-%m-%d}"


def _sss_region_aliases(region_name):
    info = SSS_REGION_CATALOG.get(region_name, {})
    return [region_name, *info.get("aliases", [])]


def _sss_regions_from_text(text):
    """从当前游戏页文本提取本期区域；不从MAA目录或旧进度推断。"""
    normalized = str(text or "").upper()
    found = []
    for region_name in SSS_REGION_CATALOG:
        if any(str(alias).upper() in normalized for alias in _sss_region_aliases(region_name)):
            found.append(region_name)
    return found


def discover_current_sss_context():
    """读取当前保全主页，返回周期、区域和截图等直接证据。"""
    seen = []
    texts = []
    screenshots = []
    for index in range(4):
        path = shot(f"sss_period_regions_{index}")
        text = ocr_text(path)
        screenshots.append(path)
        texts.append(text)
        for name in _sss_regions_from_text(text):
            if name not in seen:
                seen.append(name)
        if index < 3:
            # 第12期开始平台卡片纵向排列；旧横向滑动不会移动列表。
            swipe(850, 820, 850, 300, 900)
            wait(2)
    combined = " ".join(texts)
    area_period = get_current_sss_period(combined)
    reward_cycle = get_current_sss_reward_cycle()
    reward_counts = parse_sss_reward_counts(combined)
    # 当前第12期主页的0/60与0/24使用空心超大字号，全屏OCR常直接遗漏；
    # 用原始首屏的固定奖励区域复读，仍然只接受60/24两个固定上限。
    if screenshots:
        roi_counts = read_sss_reward_counts_from_image(screenshots[0])
        for key in ("strip", "device"):
            # ROI坐标配对比全屏OCR的文本拼接更可靠，始终覆盖可用结果。
            if roi_counts.get(key) is not None:
                reward_counts[key] = roi_counts[key]
    log(
        f"  [本期区域] 游戏页直接识别: {seen or '无'}；区域期={area_period}；"
        f"奖励周期={reward_cycle}；奖励={reward_counts}"
    )
    return {
        "period": area_period,
        "area_period": area_period,
        "reward_cycle": reward_cycle,
        "reward_counts": reward_counts,
        "reward_capped": sss_rewards_capped(reward_counts),
        "regions": seen,
        "screenshots": screenshots,
        "text": combined,
    }


def discover_current_sss_regions():
    """兼容旧调用；新代码应使用 discover_current_sss_context。"""
    return discover_current_sss_context()["regions"]


def _validate_sss_job(region_name, data):
    if not isinstance(data, dict) or data.get("type") != "SSS":
        return False, "type_not_sss"
    stage_name = str(data.get("stage_name") or "")
    if not any(str(alias).upper() in stage_name.upper() for alias in _sss_region_aliases(region_name)):
        return False, f"stage_mismatch:{stage_name or 'empty'}"
    stages = data.get("stages")
    if not isinstance(stages, list) or len(stages) != 6:
        return False, f"invalid_stage_count:{len(stages) if isinstance(stages, list) else 'missing'}"
    if not data.get("opers") or not data.get("equipment") or not data.get("buff"):
        return False, "prerequisite_fields_missing"
    return True, "ok"


def _cache_sss_job(region_name, op_id, data):
    os.makedirs(SSS_ONLINE_JOB_DIR, exist_ok=True)
    safe_region = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "_", region_name)
    path = os.path.join(SSS_ONLINE_JOB_DIR, f"SSS_{safe_region}_prts_{int(op_id)}.json")
    _atomic_write_json(path, data)
    return path


def _fetch_sss_job(region_name, op_id):
    payload = _fetch_prts_json(f"https://prts.maa.plus/copilot/get/{int(op_id)}", timeout=15)
    content = (payload.get("data") or {}).get("content", "{}")
    data = json.loads(content) if isinstance(content, str) else content
    valid, reason = _validate_sss_job(region_name, data)
    if not valid:
        raise ValueError(f"保全作业#{op_id}校验失败: {reason}")
    path = _cache_sss_job(region_name, op_id, data)
    log(f"  [保全作业] 已缓存精确匹配作业#{op_id}: {os.path.basename(path)}")
    return path, data


def _query_sss_jobs(region_name):
    """查询当前平台作业；查询结果只提供候选，必须再用get接口下载并严格校验。"""
    document = urllib.parse.quote(region_name)
    url = (
        "https://prts.maa.plus/copilot/query?page=1&limit=30&desc=true"
        f"&orderBy=hot&document={document}"
    )
    payload = _fetch_prts_json(url, timeout=15)
    candidates = (payload.get("data") or {}).get("data") or []
    exact = []
    for item in candidates:
        try:
            content = item.get("content") or "{}"
            data = json.loads(content) if isinstance(content, str) else content
            valid, _ = _validate_sss_job(region_name, data)
            if valid:
                exact.append(item)
        except Exception:
            continue
    exact.sort(key=lambda item: int(item.get("id", 0) or 0), reverse=True)
    return exact


def _select_sss_job(region_name, allow_online=True):
    """选取精确匹配作业：MAA本地→已缓存→固定已验证ID→在线热度候选。"""
    info = SSS_REGION_CATALOG.get(region_name) or {}
    job_dir = os.path.join(SSS_COPILOT_DIR, info.get("dir", ""))
    for job_name in info.get("jobs", []):
        job_path = os.path.join(job_dir, job_name)
        if not os.path.isfile(job_path):
            continue
        try:
            with open(job_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            continue
        valid, _ = _validate_sss_job(region_name, data)
        if valid:
            return job_path, data

    if os.path.isdir(SSS_ONLINE_JOB_DIR):
        for job_name in sorted(os.listdir(SSS_ONLINE_JOB_DIR), reverse=True):
            if not job_name.lower().endswith(".json"):
                continue
            job_path = os.path.join(SSS_ONLINE_JOB_DIR, job_name)
            try:
                with open(job_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception:
                continue
            valid, _ = _validate_sss_job(region_name, data)
            if valid:
                return job_path, data

    if not allow_online:
        return None, None
    tried = set()
    for op_id in info.get("prts_ids", []):
        tried.add(int(op_id))
        try:
            return _fetch_sss_job(region_name, op_id)
        except Exception as exc:
            log(f"  [保全作业] 固定作业#{op_id}不可用: {exc}", "WARN")
    try:
        for item in _query_sss_jobs(region_name):
            op_id = int(item.get("id", 0) or 0)
            if not op_id or op_id in tried:
                continue
            try:
                return _fetch_sss_job(region_name, op_id)
            except Exception as exc:
                log(f"  [保全作业] 跳过候选#{op_id}: {exc}", "WARN")
    except Exception as exc:
        log(f"  [保全作业] 在线查询失败: {exc}", "WARN")
    return None, None


def is_sss_completed_this_period(active_regions=None, current_period=None, reward_counts=None, reward_cycle=None):
    """完成口径是本奖励周期60/60与24/24，而不是区域赛季或“各打一遍”。"""
    if sss_rewards_capped(reward_counts):
        return True
    prog = load_sss_progress()
    reward_cycle = reward_cycle or get_current_sss_reward_cycle()
    if prog.get("reward_cycle") != reward_cycle:
        return False
    return bool(prog.get("reward_capped") and sss_rewards_capped(prog.get("reward_counts") or {}))


def _leave_sss_intermediate(page_path, tag="sss_leave"):
    """从保全设置/编队中间页结束当前任务，并只接受真实保全主页。"""
    items = ocr(page_path)
    leave_pos = (
        find_text(items, "离开任务", exact=True)
        or find_text(items, "结束委托", exact=True)
        or find_text(items, "离开任务")
        or find_text(items, "结束委托")
    )
    if not leave_pos:
        return False
    tap(*leave_pos)
    log(f"  [离开任务] @{leave_pos}")
    wait(3)
    confirm_path = shot(f"{tag}_confirm")
    confirm_text = ocr_text(confirm_path)
    if "确认" not in confirm_text or not any(marker in confirm_text for marker in ("结束", "离开")):
        log(f"  ❌ 离开任务后未出现完整确认文案: {confirm_text[:100]}", "ERROR")
        return False
    try:
        from PIL import Image
        with Image.open(confirm_path) as confirm_image:
            width, height = confirm_image.size
        confirm_pos = (int(width * 0.66), int(height * 0.69))
    except Exception:
        confirm_pos = (1265, 745)
    tap(*confirm_pos)
    log(f"  [确认离开] 点击右侧勾选区 @{confirm_pos}")
    wait(5)
    after_text = ""
    for index in range(4):
        after_path = shot(f"{tag}_after_{index}")
        after_text = ocr_text(after_path)
        if _sss_main_page_visible(after_text):
            log("  ✅ 已回到保全派驻主页面")
            return True
        compact = re.sub(r"\s+", "", after_text)
        if "保全作战终止" in compact:
            tap(*POS_DISMISS)
            log("  [保全收尾] 关闭保全作战终止结算页")
            wait(3)
            continue
        if any(marker in compact for marker in ("周期清理记录", "开始保全作战", "全权委托")):
            tap(*POS_TOP_HOME)
            log("  [保全收尾] 从区域详情返回保全主页")
            wait(3)
            continue
        wait(2)
    log(f"  ❌ 离开后未回到保全主页: {after_text[:120]}", "ERROR")
    return False


def _find_sss_terminal_entry(items):
    """只接受终端右上TO-DO卡片内的保全入口，拒绝全屏同名噪声。"""
    for marker in ("数据增补条", "数据增补仪", "保全派驻", "安保派驻"):
        pos = find_text(items, marker)
        if pos and int(pos[0]) >= 1350 and int(pos[1]) <= 360:
            return pos
    return None


def _scan_terminal_todo_for_sss_entry(initial_items=None):
    """只读取当前终端右上TO-DO卡；实机证明该卡不接受手势轮播。"""
    pos = _find_sss_terminal_entry(list(initial_items or []))
    if pos:
        return pos
    log("  [终端TO-DO] 当前卡片不是保全；不再执行无效拖动", "WARN")
    return None

def _find_prts_routine_entry(items):
    """识别终端右侧 P.R.T.S. ROUTINE 面板；只返回受限区域内的明确文字。"""
    for text, x, y in items:
        compact = re.sub(r"[^A-Z]", "", str(text).upper())
        if int(x) < 1350 or not 350 <= int(y) <= 650:
            continue
        if compact in {"PRTS", "ROUTINE"}:
            return int(x), int(y)
    return None


def _try_enter_sss_via_prts_routine(terminal_items):
    """从终端的常态事务面板寻找明确保全入口；任何未知页都停止。"""
    routine_pos = _find_prts_routine_entry(terminal_items)
    if not routine_pos:
        return False
    tap(*routine_pos)
    log(f"  [终端常态事务] 点击明确 P.R.T.S. ROUTINE 面板 @{routine_pos}")
    wait(4)
    page = shot("sss_prts_routine")
    text = ocr_text(page)
    if _sss_main_page_visible(text):
        log("  ✅ P.R.T.S. ROUTINE 已直接进入保全派驻主页")
        return True
    items = ocr(page)
    entry = None
    for marker in ("保全派驻", "安保派驻", "数据增补条", "数据增补仪"):
        entry = find_text(items, marker)
        if entry:
            break
    if not entry:
        log(f"  [终端常态事务] 未出现明确保全入口，停止恢复: {text[:100]}", "WARN")
        return False
    tap(*entry)
    log(f"  [终端常态事务] 点击明确保全入口 @{entry}")
    wait(5)
    verify_page = shot("sss_prts_entry_verify")
    verify_text = ocr_text(verify_page)
    if _sss_main_page_visible(verify_text):
        log("  ✅ 经 P.R.T.S. ROUTINE 进入保全派驻主页")
        return True
    log(f"  [终端常态事务] 点击后未验证为保全主页: {verify_text[:100]}", "WARN")
    return False


def _try_enter_sss_via_terminal_service_tab():
    """从终端底部建筑状资源/常态事务图标进入，只接受后续明确保全文案。"""
    tap(1120, 1005)
    log("  [终端正式入口] 点击底部建筑状资源/常态事务图标 @(1120, 1005)")
    wait(4)
    page = shot("sss_terminal_service_tab")
    text = ocr_text(page)
    if _sss_main_page_visible(text):
        log("  ✅ 底部正式入口已直接进入保全派驻主页")
        return True
    items = ocr(page)
    entry = None
    for marker in ("保全派驻", "安保派驻", "数据增补条", "数据增补仪"):
        entry = find_text(items, marker)
        if entry:
            break
    if not entry:
        log(f"  [终端正式入口] 未出现明确保全入口，停止恢复: {text[:120]}", "WARN")
        return False
    tap(*entry)
    log(f"  [终端正式入口] 点击明确保全入口 @{entry}")
    wait(5)
    verify_page = shot("sss_terminal_service_entry_verify")
    verify_text = ocr_text(verify_page)
    if _sss_main_page_visible(verify_text):
        log("  ✅ 经终端底部正式入口进入保全派驻主页")
        return True
    log(f"  [终端正式入口] 点击后未验证为保全主页: {verify_text[:120]}", "WARN")
    return False


def goto_sss_page():
    """导航到保全派驻页面: 主界面→终端→右上角数据增补条→保全派驻
    
    🔴 2026-07-05 修正: 保全派驻入口在终端页面右上角TO-DO LIST的"数据增补条"区域
    用户确认: 点击右上角"数据增补条"或"数据增补仪"可直接进入保全派驻
    
    Returns:
        bool: True=成功进入保全派驻页面
    """
    log("→ 导航到保全派驻")
    
    # 1. 检查是否已经在保全派驻主页面 (排除导能元件/装备/编队等中间页面)
    p = shot("sss_check_current")
    t = ocr_text(p)
    # 中间页面关键词 (导能元件选择/装备配置/编队/关卡详情等, 不是主页面)
    intermediate_kw = ["离开任务", "结束委托", "选择定向导能元件", "ENERGYCONDUCTION", "确认选择", "战术装备", "快捷编队", "开始部署"]
    is_intermediate = any(k in t for k in intermediate_kw)
    is_main_page = any(k in t.upper() for k in (marker.upper() for marker in SSS_MAIN_MARKERS))
    
    if is_main_page and not is_intermediate:
        log("  ✅ 已在保全派驻页面")
        return True
    if is_intermediate:
        log(f"  [检测] 当前在中间页面(导能元件/装备/编队等), 尝试离开任务回到主页面")
        if _leave_sss_intermediate(p, "sss_resume_leave"):
            return True
        return False
    
    # 2. 确保在主界面
    state = get_state()
    if state != "main_menu":
        if not goto_main_menu():
            log("  ❌ 无法回主界面", "ERROR")
            return False
        wait(2)
    
    # 3. 点击终端进入终端页面 (实测坐标1450,241)
    tap(1450, 241)
    log("  [主界面] 点击终端按钮 (1450, 241)")
    wait(3)
    
    # 4. 点击右上角"数据增补条"进入保全派驻 (实测坐标1627,178)
    p = shot("sss_terminal")
    t = ocr_text(p)

    # 终端会记住上一次打开的子页面；点击终端按钮时可能已经直接恢复到
    # 保全主页。此时不得再把主页左下奖励文字当成终端入口点击，否则会
    # 从正确页面退出并反向误判导航失败。
    if _sss_main_page_visible(t) and not any(k in t for k in intermediate_kw):
        log("  ✅ 终端快捷恢复已直接进入保全派驻主页")
        return True

    items = ocr(p)

    # TO-DO卡片会在集成战略、活动、保全等任务间轮播。只有当前卡片明确
    # 出现保全文案才允许进入；固定坐标会在卡片显示肉鸽时误点进肉鸽。
    data_pos = _scan_terminal_todo_for_sss_entry(items)
    if not data_pos:
        if _try_enter_sss_via_terminal_service_tab():
            return True
        log("  ❌ 终端已核验快捷卡、P.R.T.S.与底部正式入口，仍未找到明确保全入口", "ERROR")
        return False
    tap(*data_pos)
    log(f"  [入口] 点击保全派驻入口 @{data_pos}")
    wait(5)
    
    # 5. 验证进入保全派驻页面
    p2 = shot("sss_page")
    t2 = ocr_text(p2)
    if any(k in t2 for k in intermediate_kw):
        log("  [入口] 检测到上次未结束的保全任务，先结束残留任务")
        return _leave_sss_intermediate(p2, "sss_entry_leave")
    if any(k in t2.upper() for k in (marker.upper() for marker in SSS_MAIN_MARKERS)):
        log("  ✅ 进入保全派驻页面")
        return True
    
    log(f"  ❌ 未进入保全派驻页面, OCR: {t2[:80]}")
    return False


def check_sss_reward_status():
    """检查保全派驻页面是否有可领取的奖励
    
    Returns:
        str: "has_reward"=有奖励可领, "no_reward"=无奖励, "need_battle"=需要打关卡, "unknown"
    """
    p = shot("sss_status")
    t = ocr_text(p)
    items = ocr(p)
    
    log(f"  [保全派驻页面] OCR: {t[:150]}")
    
    # 检测"领取"/"结算"按钮
    claim_pos = find_text(items, "领取") or find_text(items, "结算")
    if claim_pos:
        log(f"  → 检测到可领取奖励 @{claim_pos}")
        return "has_reward"
    
    # 检测"全权委托"
    delegate_pos = find_text(items, "全权委托")
    if delegate_pos:
        log(f"  → 检测到全权委托选项 @{delegate_pos}")
        return "has_delegate"
    
    # 检测"开始任务"/"开始作战"
    start_pos = find_text(items, "开始任务") or find_text(items, "开始作战") or find_text(items, "开始")
    if start_pos:
        log(f"  → 检测到可开始作战 @{start_pos}")
        return "need_battle"
    
    return "unknown"


def _sss_region_entry_confirmed(page_text):
    text = str(page_text or "")
    return any(marker in text for marker in (
        "开始保全作战", "全权委托", "开始部署", "结束委托", "暂停任务",
        "最佳记录", "BESTRECORD", "BEST RECORD", "通关记录",
    ))


def _sss_main_page_visible(page_text):
    text = str(page_text or "")
    return any(marker in text for marker in SSS_MAIN_MARKERS) and any(
        marker in text for marker in ("清理报酬", "数据增补条", "数据增补仪", "周期任务")
    )


def _next_monday_date(now=None):
    current = (now or datetime.now()).date()
    days = (7 - current.weekday()) % 7
    # 保全位于当周剿灭之后；若今天正是周一，保护的是下一次周更。
    if days == 0:
        days = 7
    return current + timedelta(days=days)


def _parse_delegate_expiry_buckets(text, now=None):
    """从代理卡说明读取[(张数, 到期日)]；无法成对确认就返回空。

    只接受同一短句内同时出现的张数和到期日/剩余天数，避免把奖励数量、
    周期倒计时等无关数字当成代理卡库存。
    """
    compact_lines = [re.sub(r"\s+", "", line) for line in str(text or "").splitlines()]
    current = (now or datetime.now()).date()
    buckets = []
    seen = set()
    day_patterns = (
        re.compile(r"(\d{1,2})张[^\n]{0,24}?(\d{1,3})天(?:后)?(?:过期|到期)"),
        re.compile(r"(\d{1,3})天(?:后)?(?:过期|到期)[^\n]{0,24}?(\d{1,2})张"),
    )
    date_patterns = (
        re.compile(r"(\d{1,2})张[^\n]{0,24}?(\d{1,2})月(\d{1,2})日(?:过期|到期)?"),
        re.compile(r"(\d{1,2})月(\d{1,2})日(?:过期|到期)?[^\n]{0,24}?(\d{1,2})张"),
    )
    for line in compact_lines:
        for index, pattern in enumerate(day_patterns):
            for match in pattern.finditer(line):
                if index == 0:
                    count, days = int(match.group(1)), int(match.group(2))
                else:
                    days, count = int(match.group(1)), int(match.group(2))
                key = (count, current + timedelta(days=days))
                if 0 < count <= 99 and key not in seen:
                    seen.add(key)
                    buckets.append(key)
        for index, pattern in enumerate(date_patterns):
            for match in pattern.finditer(line):
                if index == 0:
                    count, month, day = map(int, match.groups())
                else:
                    month, day, count = map(int, match.groups())
                year = current.year
                try:
                    expiry = current.replace(year=year, month=month, day=day)
                    if expiry < current:
                        expiry = expiry.replace(year=year + 1)
                except ValueError:
                    continue
                key = (count, expiry)
                if 0 < count <= 99 and key not in seen:
                    seen.add(key)
                    buckets.append(key)
    return sorted(buckets, key=lambda item: item[1])


def _sss_delegate_card_decision(text, now=None):
    """只有按到期分桶证明周一仍可用5张时，才允许保全消耗2张。"""
    monday = _next_monday_date(now)
    buckets = _parse_delegate_expiry_buckets(text, now=now)
    if not buckets:
        return {
            "allow": False,
            "reason": "未读到代理卡张数与到期日的成对证据，改用实体通关",
            "reserve": ANNIHILATION_DELEGATE_RESERVE,
            "buckets": [],
        }
    total = sum(count for count, _expiry in buckets)
    expiring_before_monday = sum(count for count, expiry in buckets if expiry <= monday)
    valid_on_monday = total - expiring_before_monday
    # 游戏默认先消耗较早到期卡；不足2张临期卡时，剩余消耗会动用长效卡。
    long_lived_spend = max(0, SSS_FULL_DELEGATE_COST - expiring_before_monday)
    valid_after = valid_on_monday - long_lived_spend
    allow = total >= SSS_FULL_DELEGATE_COST and valid_after >= ANNIHILATION_DELEGATE_RESERVE
    return {
        "allow": allow,
        "reason": (
            f"代理卡总数{total}，周一前到期{expiring_before_monday}，"
            f"委托后周一可用{valid_after}，需保留{ANNIHILATION_DELEGATE_RESERVE}"
        ),
        "reserve": ANNIHILATION_DELEGATE_RESERVE,
        "total": total,
        "expiring_before_monday": expiring_before_monday,
        "valid_after": valid_after,
        "buckets": [(count, expiry.isoformat()) for count, expiry in buckets],
    }


def select_sss_region(region_name):
    """在保全派驻页面选择区域
    
    Args:
        region_name: 区域名, 如"阿尔斯特甜品制作平台" 或 "塔山农业实验平台"
    
    Returns:
        bool: True=成功选中区域
    """
    # 🔴 2026-07-05 修复: OCR可能识别为英文, 需要同时搜索中英文关键词
    # 塔山农业实验平台 → "塔山" 或 "TOWER" 或 "MOUNTAINS"
    # 阿尔斯特甜品制作平台 → "阿尔斯特" 或 "ALSTER" 或 "ABMP"
    search_keywords = _sss_region_aliases(region_name)

    # 发现流程可能已把纵向平台列表滚到底；每次选择前先回到列表顶部，
    # 否则排在首位的复刻平台会永远找不到。
    for _ in range(2):
        swipe(850, 300, 850, 820, 700)
        wait(1)
    
    p = shot("sss_regions")
    items = ocr(p)

    def _open_from_label(label_pos, keyword, suffix):
        tap(*label_pos)
        log(f"  [选区域] 选中'{region_name}' (关键词'{keyword}') @{label_pos}")
        wait(3)
        check_path = shot(f"sss_region_open_{suffix}_selected")
        check_text = ocr_text(check_path)
        if _sss_region_entry_confirmed(check_text):
            return True
        if not _sss_main_page_visible(check_text):
            log(f"  [选区域] 选中后出现未知页面，拒绝盲点: {check_text[:100]}", "WARN")
            return False

        # 第12期平台页第一次点击只会选中卡片。再次点击卡面左侧图片区才真正进入。
        card_pos = (max(140, int(label_pos[0]) - 300), min(900, int(label_pos[1]) + 70))
        tap(*card_pos)
        log(f"  [进平台] 二次点击卡面 @{card_pos}")
        wait(5)
        detail_path = shot(f"sss_region_open_{suffix}_detail")
        detail_text = ocr_text(detail_path)
        if _sss_region_entry_confirmed(detail_text):
            log(f"  ✅ 已真正进入'{region_name}'详情/作战页")
            return True
        log(f"  ❌ 卡片已选中但未进入详情页，OCR: {detail_text[:120]}", "ERROR")
        return False

    for kw in search_keywords:
        pos = find_text(items, kw)
        if pos:
            return _open_from_label(pos, kw, "top")
    
    # 尝试滑动查找
    for i in range(3):
        swipe(960, 700, 960, 300, 1000)
        wait(2)
        p2 = shot(f"sss_region_{i}")
        items2 = ocr(p2)
        for kw in search_keywords:
            pos2 = find_text(items2, kw)
            if pos2:
                return _open_from_label(pos2, kw, f"scroll_{i}")
    
    log(f"  ❌ 未找到区域'{region_name}' (尝试关键词: {search_keywords})", "ERROR")
    return False


def _notify_nonblocking(msg, title="通知"):
    """非阻塞弹窗通知 (不卡住主流程)"""
    import threading, ctypes
    try:
        MB_TOPMOST = 0x00040000
        MB_SETFOREGROUND = 0x00010000
        MB_ICONWARNING = 0x00000030
        MB_OK = 0x00000000
        flags = MB_TOPMOST | MB_SETFOREGROUND | MB_ICONWARNING | MB_OK
        def _auto_close_msgbox(timeout=60):
            """SSS中间警告60秒后自动关闭；最终汇报弹窗不走此函数。"""
            time.sleep(timeout)
            user32 = ctypes.windll.user32
            WM_CLOSE = 0x0010
            from ctypes import wintypes
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            @callback_type
            def enum_proc(hwnd, _lparam):
                length = user32.GetWindowTextLengthW(hwnd)
                if length:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if buf.value == title:
                        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return True
            user32.EnumWindows(enum_proc, 0)
        def _show():
            ctypes.windll.user32.MessageBoxW(0, msg, title, flags)
        threading.Thread(target=_auto_close_msgbox, daemon=True).start()
        t = threading.Thread(target=_show, daemon=True)
        t.start()
        log(f"  [通知] 已弹出: {title}")
    except Exception as e:
        log(f"  [通知] 弹窗失败: {e}", "WARN")


def _check_sss_begin_exceeded():
    """检查MAA日志中SSSBegin是否超限 (编队/装备不对的典型症状)
    
    Returns:
        bool: True=检测到SSSBegin超限
    """
    try:
        with open(MAA_LOG, 'r', encoding='utf-8', errors='replace') as f:
            # 只保留最近500行，避免为一次SSS探测复制整份64MiB日志。
            recent = "".join(deque(f, maxlen=500))
        if "SSSBegin" in recent and "exceeded the limit" in recent:
            return True
        # 也检查exec_times
        if "SSSBegin" in recent and "exec_times" in recent:
            return True
    except:
        pass
    return False


def _validate_sss_formation_profile(region_name, job_config):
    """校验本账号快捷编队档与在线作业约束完全一致。"""
    profile = SSS_FORMATION_PROFILES.get(region_name)
    if not isinstance(profile, list) or len(profile) != 20:
        return False, f"formation_profile_size:{len(profile) if isinstance(profile, list) else 'missing'}"

    names = [str(item.get("name") or "").strip() for item in profile]
    if any(not name for name in names) or len(set(names)) != len(names):
        return False, "formation_profile_names_invalid"
    for item in profile:
        profession = str(item.get("profession") or "")
        skill = item.get("skill")
        if profession not in SSS_FORMATION_PROFESSIONS or skill not in (1, 2, 3):
            return False, f"formation_profile_item_invalid:{item.get('name')}"

    expected_cores = {
        str(item.get("name") or ""): int(item.get("skill") or 0)
        for item in (job_config.get("opers") or [])
        if item.get("name")
    }
    actual_cores = {
        item["name"]: int(item["skill"])
        for item in profile
        if item.get("core")
    }
    if actual_cores != expected_cores:
        return False, f"formation_core_mismatch:{actual_cores}!={expected_cores}"

    expected_tools = {
        key: int(value or 0)
        for key, value in (job_config.get("tool_men") or {}).items()
        if key in SSS_FORMATION_PROFESSIONS
    }
    actual_tools = {key: 0 for key in SSS_FORMATION_PROFESSIONS}
    for item in profile:
        if not item.get("core"):
            actual_tools[item["profession"]] += 1
    for profession in SSS_FORMATION_PROFESSIONS:
        if actual_tools[profession] != expected_tools.get(profession, 0):
            return False, (
                f"formation_tool_count_mismatch:{profession}:"
                f"{actual_tools[profession]}!={expected_tools.get(profession, 0)}"
            )
    return True, "ok"


def _sss_formation_selected_count(items):
    """读取编队页右侧竖排 N/20；返回真实已选人数。"""
    numbers = []
    for text, x, y in items or []:
        if x < 1760 or not (350 <= y <= 720):
            continue
        numbers.extend(int(value) for value in re.findall(r"\d{1,2}", str(text)))
    if len(numbers) >= 2 and numbers[-1] == 20:
        return numbers[-2]
    return None


def _build_sss_maa_formation_job(region_name, job_config):
    """把SSS编队档转换成MAA通用Copilot自动编队作业。

    MAA 6.16.8 的 ``SSSCopilotTask`` 明确关闭了 ``BattleFormationTask``，
    但普通 ``Copilot`` 仍完整提供职业筛选、姓名OCR、技能选择和缺员报告。
    这里只做数据适配，不复制MAA的识图/点击算法。
    """
    valid, reason = _validate_sss_formation_profile(region_name, job_config)
    if not valid:
        raise ValueError(f"SSS编队档与在线作业不一致: {reason}")
    profile = SSS_FORMATION_PROFILES[region_name]
    groups = []
    for index, item in enumerate(profile, start=1):
        candidates = []
        for candidate in [item["name"], *(item.get("alternates") or [])]:
            if candidate and candidate not in {oper["name"] for oper in candidates}:
                candidates.append({"name": candidate, "skill": int(item["skill"])})
        groups.append({
            "name": f"SSS-{index:02d}-{item['profession']}",
            "opers": candidates,
        })

    payload = {
        "minimum_required": "v6.16.8",
        # 1-7只用于通过Copilot作业格式校验；本桥接不导航、不进入战斗。
        "stage_name": "1-7",
        "doc": {
            "title": f"SSS {region_name} MAA原生自动编队桥接",
            "details": "仅执行BattleFormationTask，完成后由控制层立即停止。",
        },
        "opers": [],
        "groups": groups,
        "actions": [],
    }
    os.makedirs(SSS_FORMATION_BRIDGE_DIR, exist_ok=True)
    safe_region = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "_", region_name)
    path = os.path.join(SSS_FORMATION_BRIDGE_DIR, f"SSS_{safe_region}_maa_formation.json")
    _atomic_write_json(path, payload)
    return path, payload


def _maa_core_formation_event(msg, details):
    """归类MaaCore回调；独立成纯函数便于离线验证停止边界。"""
    subtask = str((details or {}).get("subtask") or "")
    taskchain = str((details or {}).get("taskchain") or "")
    if msg == 20002 and subtask == "BattleFormationTask" and taskchain == "Copilot":
        return "formation_completed"
    if msg == 20000 and subtask == "BattleFormationTask":
        return "formation_error"
    if msg in (10000, 3):
        return "task_error"
    return ""


def _run_maa_core_formation_only(job_path, timeout=300):
    """直接复用MaaCore原生自动编队，并在编队完成回调处停止。

    普通Copilot的下一步是 ``BattleStartAll``。SSS编队页没有普通关的
    “开始行动”模板，但仍在完成回调出现后立即发出Stop，形成双重保险，
    避免把编队桥接误当作战斗任务继续执行。
    """
    import ctypes
    import threading

    _close_maacore_screenshot_bridge()
    if _maa_task_queue_running():
        log("  ❌ MAA已有队列运行，禁止并发启动编队桥接", "ERROR")
        return False
    if not ensure_maa_install_ready(allow_recovery=True):
        return False
    detect_mumu_adb_port()

    # MaaCore与WPF GUI不能同时争用同一控制器；仅关闭已确认空闲的MAA。
    try:
        _stop_idle_maa_for_update()
    except Exception as exc:
        log(f"  ❌ 无法释放空闲MAA控制器: {exc}", "ERROR")
        return False

    root = _maa_install_root()
    dll_path = os.path.join(root, "MaaCore.dll")
    user_dir = os.path.join(SSS_FORMATION_BRIDGE_DIR, "maa_core_user")
    os.makedirs(user_dir, exist_ok=True)
    dll_dir_cookie = None
    handle = None
    callback_ref = None
    events = []
    formation_completed = threading.Event()
    failed = threading.Event()
    selected = set()

    try:
        if hasattr(os, "add_dll_directory"):
            dll_dir_cookie = os.add_dll_directory(root)
        core = ctypes.WinDLL(dll_path)
        callback_type = ctypes.WINFUNCTYPE(
            None, ctypes.c_int32, ctypes.c_char_p, ctypes.c_void_p
        )

        core.AsstSetUserDir.argtypes = [ctypes.c_char_p]
        core.AsstSetUserDir.restype = ctypes.c_uint8
        core.AsstLoadResource.argtypes = [ctypes.c_char_p]
        core.AsstLoadResource.restype = ctypes.c_uint8
        core.AsstCreateEx.argtypes = [callback_type, ctypes.c_void_p]
        core.AsstCreateEx.restype = ctypes.c_void_p
        core.AsstDestroy.argtypes = [ctypes.c_void_p]
        core.AsstSetInstanceOption.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_char_p]
        core.AsstSetInstanceOption.restype = ctypes.c_uint8
        core.AsstSetConnectionExtras.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        core.AsstSetConnectionExtras.restype = None
        core.AsstConnect.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
        ]
        core.AsstConnect.restype = ctypes.c_uint8
        core.AsstAppendTask.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        core.AsstAppendTask.restype = ctypes.c_int32
        core.AsstStart.argtypes = [ctypes.c_void_p]
        core.AsstStart.restype = ctypes.c_uint8
        core.AsstStop.argtypes = [ctypes.c_void_p]
        core.AsstStop.restype = ctypes.c_uint8
        core.AsstRunning.argtypes = [ctypes.c_void_p]
        core.AsstRunning.restype = ctypes.c_uint8

        def on_callback(msg, raw_details, _custom):
            try:
                details = json.loads(
                    raw_details.decode("utf-8", errors="replace") if raw_details else "{}"
                )
            except Exception:
                details = {}
            event = _maa_core_formation_event(int(msg), details)
            if event:
                events.append((event, details))
            if details.get("what") == "BattleFormationSelected":
                name = ((details.get("details") or {}).get("selected") or "")
                if name:
                    selected.add(str(name))
            if event == "formation_completed":
                formation_completed.set()
            elif event in ("formation_error", "task_error"):
                failed.set()

        callback_ref = callback_type(on_callback)
        if not core.AsstSetUserDir(os.fsencode(user_dir)):
            raise RuntimeError("AsstSetUserDir失败")
        if not core.AsstLoadResource(os.fsencode(root)):
            raise RuntimeError("AsstLoadResource失败")
        handle = core.AsstCreateEx(callback_ref, None)
        if not handle:
            raise RuntimeError("AsstCreateEx失败")
        # 与本机MAA已验证连接配置一致；连接配置负责选择MuMu截图/输入方式。
        core.AsstSetInstanceOption(handle, 6, b"Bilibili")
        core.AsstSetConnectionExtras(
            b"MuMuEmulator12", _maa_mumu_core_extras().encode("utf-8")
        )
        if not core.AsstConnect(
            handle, os.fsencode(ADB), DEVICE.encode("utf-8"), b"MuMuEmulator12"
        ):
            raise RuntimeError(f"MaaCore连接失败: {DEVICE}")
        params = json.dumps({
            "filename": os.path.abspath(job_path),
            "formation": True,
            "need_navigate": False,
            "ignore_requirements": True,
            "add_trust": False,
        }, ensure_ascii=False).encode("utf-8")
        task_id = core.AsstAppendTask(handle, b"Copilot", params)
        if task_id <= 0:
            raise RuntimeError("AsstAppendTask(Copilot)失败")
        if not core.AsstStart(handle):
            raise RuntimeError("AsstStart失败")

        deadline = time.time() + max(30, int(timeout))
        while time.time() < deadline and not formation_completed.is_set() and not failed.is_set():
            if not core.AsstRunning(handle):
                break
            time.sleep(0.05)

        # 无论成功/失败都先停止，禁止普通Copilot继续走BattleStartAll。
        core.AsstStop(handle)
        stop_deadline = time.time() + 15
        while core.AsstRunning(handle) and time.time() < stop_deadline:
            time.sleep(0.05)

        if not formation_completed.is_set():
            reason = events[-1][0] if events else "timeout_or_stopped"
            log(f"  ❌ MAA原生自动编队未完成: {reason}，已选{len(selected)}/20", "ERROR")
            return False
        log(f"  ✅ MAA原生BattleFormationTask完成，回调已停止后续战斗；已选{len(selected)}/20")
        return True
    except Exception as exc:
        log(f"  ❌ MAA原生自动编队桥接失败: {type(exc).__name__}: {exc}", "ERROR")
        return False
    finally:
        if handle:
            try:
                core.AsstStop(handle)
            except Exception:
                pass
            try:
                core.AsstDestroy(handle)
            except Exception:
                pass
        if dll_dir_cookie:
            try:
                dll_dir_cookie.close()
            except Exception:
                pass


def _run_maa_core_roguelike_once(params, timeout=3600):
    """Run one bounded Roguelike task through MaaCore and retain callbacks.

    MAA 6.16.8's WPF serializer omits the official ``use_foldartal`` field.
    This direct path is used only when that Core-only option is explicitly
    requested. It owns the controller for the whole call and closes only an
    already-idle MAA GUI before connecting.
    """
    import ctypes
    import threading

    global _LAST_MAA_RUN_LOG
    _LAST_MAA_RUN_LOG = ""
    _close_maacore_screenshot_bridge()
    if _maa_task_queue_running():
        log("  ❌ MAA已有队列运行，禁止并发启动MaaCore肉鸽", "ERROR")
        return {"ok": False, "reason": "maa_queue_running"}
    if not ensure_maa_install_ready(allow_recovery=True):
        return {"ok": False, "reason": "maa_install_unavailable"}
    detect_mumu_adb_port()
    try:
        _stop_idle_maa_for_update()
    except Exception as exc:
        log(f"  ❌ 无法释放空闲MAA控制器: {exc}", "ERROR")
        return {"ok": False, "reason": "maa_controller_busy", "error": str(exc)}

    root = _maa_install_root()
    dll_path = os.path.join(root, "MaaCore.dll")
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    evidence_dir = os.path.join(OUTPUT_DIR, "maa_core_roguelike")
    user_dir = os.path.join(evidence_dir, "user")
    callback_path = os.path.join(evidence_dir, f"callbacks_{run_stamp}.log")
    os.makedirs(user_dir, exist_ok=True)

    callback_names = {
        3: "AllTasksCompleted",
        10000: "TaskChainError",
        10001: "TaskChainStart",
        10002: "TaskChainCompleted",
        10003: "TaskChainExtraInfo",
        10004: "TaskChainStopped",
        20000: "SubTaskError",
        20001: "SubTaskStart",
        20002: "SubTaskCompleted",
        20003: "SubTaskExtraInfo",
    }
    callback_lines = []
    all_done = threading.Event()
    chain_completed = threading.Event()
    chain_error = threading.Event()
    dll_dir_cookie = None
    handle = None
    callback_ref = None
    core = None
    timed_out = False

    try:
        if hasattr(os, "add_dll_directory"):
            dll_dir_cookie = os.add_dll_directory(root)
        core = ctypes.WinDLL(dll_path)
        callback_type = ctypes.WINFUNCTYPE(
            None, ctypes.c_int32, ctypes.c_char_p, ctypes.c_void_p
        )
        core.AsstSetUserDir.argtypes = [ctypes.c_char_p]
        core.AsstSetUserDir.restype = ctypes.c_uint8
        core.AsstLoadResource.argtypes = [ctypes.c_char_p]
        core.AsstLoadResource.restype = ctypes.c_uint8
        core.AsstCreateEx.argtypes = [callback_type, ctypes.c_void_p]
        core.AsstCreateEx.restype = ctypes.c_void_p
        core.AsstDestroy.argtypes = [ctypes.c_void_p]
        core.AsstSetInstanceOption.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_char_p]
        core.AsstSetInstanceOption.restype = ctypes.c_uint8
        core.AsstSetConnectionExtras.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        core.AsstSetConnectionExtras.restype = None
        core.AsstConnect.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
        ]
        core.AsstConnect.restype = ctypes.c_uint8
        core.AsstAppendTask.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        core.AsstAppendTask.restype = ctypes.c_int32
        core.AsstStart.argtypes = [ctypes.c_void_p]
        core.AsstStart.restype = ctypes.c_uint8
        core.AsstStop.argtypes = [ctypes.c_void_p]
        core.AsstStop.restype = ctypes.c_uint8
        core.AsstRunning.argtypes = [ctypes.c_void_p]
        core.AsstRunning.restype = ctypes.c_uint8

        def on_callback(msg, raw_details, _custom):
            try:
                details = json.loads(
                    raw_details.decode("utf-8", errors="replace") if raw_details else "{}"
                )
            except Exception:
                details = {}
            name = callback_names.get(int(msg), f"AsstMsg{int(msg)}")
            line = f"{name} {json.dumps(details, ensure_ascii=False, separators=(',', ':'))}"
            callback_lines.append(line)
            if int(msg) == 3:
                all_done.set()
            elif int(msg) == 10002 and details.get("taskchain") == "Roguelike":
                chain_completed.set()
            elif int(msg) == 10000 and details.get("taskchain") == "Roguelike":
                chain_error.set()
            if int(msg) in (3, 10000, 10001, 10002) or (
                int(msg) == 20003 and details.get("what") == "RoguelikeSettlement"
            ):
                log(f"  MaaCore {line}")

        callback_ref = callback_type(on_callback)
        if not core.AsstSetUserDir(os.fsencode(user_dir)):
            raise RuntimeError("AsstSetUserDir失败")
        if not core.AsstLoadResource(os.fsencode(root)):
            raise RuntimeError("AsstLoadResource失败")
        handle = core.AsstCreateEx(callback_ref, None)
        if not handle:
            raise RuntimeError("AsstCreateEx失败")
        core.AsstSetInstanceOption(handle, 6, b"Bilibili")
        core.AsstSetConnectionExtras(
            b"MuMuEmulator12", _maa_mumu_core_extras().encode("utf-8")
        )
        if not core.AsstConnect(
            handle, os.fsencode(ADB), DEVICE.encode("utf-8"), b"MuMuEmulator12"
        ):
            raise RuntimeError(f"MaaCore连接失败: {DEVICE}")
        payload = json.dumps(params, ensure_ascii=False).encode("utf-8")
        task_id = core.AsstAppendTask(handle, b"Roguelike", payload)
        if task_id <= 0:
            raise RuntimeError("AsstAppendTask(Roguelike)失败")
        if not core.AsstStart(handle):
            raise RuntimeError("AsstStart失败")

        deadline = time.time() + max(30, int(timeout))
        while time.time() < deadline and not all_done.is_set():
            if not core.AsstRunning(handle):
                break
            time.sleep(0.2)
        timed_out = not all_done.is_set() and core.AsstRunning(handle)
        if timed_out:
            log("  ⚠️ MaaCore肉鸽达到本次时间边界，开始有界停止", "WARN")
        if core.AsstRunning(handle):
            core.AsstStop(handle)
            stop_deadline = time.time() + 30
            while core.AsstRunning(handle) and time.time() < stop_deadline:
                time.sleep(0.1)
    except Exception as exc:
        callback_lines.append(
            "ControllerException " + json.dumps(
                {"type": type(exc).__name__, "error": str(exc)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        log(f"  ❌ MaaCore肉鸽直连失败: {type(exc).__name__}: {exc}", "ERROR")
    finally:
        _LAST_MAA_RUN_LOG = "\n".join(callback_lines) + ("\n" if callback_lines else "")
        try:
            with open(callback_path, "w", encoding="utf-8") as callback_file:
                callback_file.write(_LAST_MAA_RUN_LOG)
        except Exception as exc:
            log(f"  ⚠️ MaaCore回调证据写入失败: {exc}", "WARN")
        if handle and core:
            try:
                core.AsstStop(handle)
            except Exception:
                pass
            try:
                core.AsstDestroy(handle)
            except Exception:
                pass
        if dll_dir_cookie:
            try:
                dll_dir_cookie.close()
            except Exception:
                pass

    ok = bool(all_done.is_set() and chain_completed.is_set() and not chain_error.is_set())
    reason = (
        "completed" if ok else
        "taskchain_error" if chain_error.is_set() else
        "timeout" if timed_out else
        "incomplete"
    )
    return {
        "ok": ok,
        "reason": reason,
        "all_tasks_completed": all_done.is_set(),
        "taskchain_completed": chain_completed.is_set(),
        "taskchain_error": chain_error.is_set(),
        "callback_log": callback_path,
    }


def _configure_sss_formation(region_name, job_config, already_open=False):
    """调用MAA原生自动编队，回到SSS页后只做20/20与阵容确认闭环。"""
    valid, reason = _validate_sss_formation_profile(region_name, job_config)
    if not valid:
        log(f"  ❌ SSS编队档与在线作业不一致: {reason}", "ERROR")
        return False

    # 旧版自制选择器可能把现场留在“清空选择”页；先退出到MAA能识别的
    # SSS首批小队页。正常生产路径不会触发这一恢复分支。
    current_path = shot("sss_formation_bridge_pre")
    current_text = ocr_text(current_path)
    if "清空选择" in current_text:
        back()
        wait(2)
        current_path = shot("sss_formation_bridge_back")
        current_text = ocr_text(current_path)
    if not any(marker in current_text for marker in ("快捷编队", "首批作战小队选任", "阵容确认")):
        log(f"  ❌ 未确认SSS编队页，不能启动MAA自动编队: {current_text[:100]}", "ERROR")
        return False

    try:
        bridge_path, _ = _build_sss_maa_formation_job(region_name, job_config)
    except Exception as exc:
        log(f"  ❌ 生成MAA自动编队桥接作业失败: {exc}", "ERROR")
        return False
    log(f"  [编队] 交给MAA原生BattleFormationTask: {os.path.basename(bridge_path)}")
    if not _run_maa_core_formation_only(bridge_path):
        return False

    formation_path = shot("sss_formation_ready")
    formation_items = ocr(formation_path)
    selected_count = _sss_formation_selected_count(formation_items)
    if selected_count != 20:
        formation_text = " ".join(t for t, _, _ in formation_items)
        log(
            f"  ❌ 返回编队页后真实人数={selected_count or '未识别'}/20，"
            f"拒绝确认: {formation_text[:120]}",
            "ERROR",
        )
        return False
    ready_pos = find_text(formation_items, "阵容确认", exact=True) or find_text(
        formation_items, "阵容确认"
    )
    if not ready_pos:
        log("  ❌ 20/20已确认，但未找到'阵容确认'按钮", "ERROR")
        return False
    tap(*ready_pos)
    log(f"  [编队] 20/20，点击阵容确认 @{ready_pos}")
    wait(5)
    return True


def run_sss_copilot(region_name):
    """执行SSS保全派驻Copilot作业。

    设置阶段由控制层选择导能元件/战术装备，并通过 MaaCore 的
    ``BattleFormationTask`` 原生自动编队；控制层只转换作业数据、核验
    游戏页真实20/20并确认阵容，不复制MAA的干员OCR与选人算法。随后在
    “开始部署”页把原始SSS作业交回MAA执行六阶段战斗。

    Returns:
        bool: True=成功完成
    """
    global _SSS_NEED_MANUAL
    region_info = SSS_REGION_CATALOG.get(region_name)
    if not region_info:
        log(f"  ❌ 未知区域: {region_name}", "ERROR")
        return False

    job_path, job_config = _select_sss_job(region_name)
    if not job_path:
        log(f"  ❌ 当前MAA完整包没有与'{region_name}'匹配的受支持SSS作业", "ERROR")
        return False
    log(f"  [作业] {os.path.basename(job_path)}")

    # 加载作业配置
    try:
        with open(job_path, 'r', encoding='utf-8') as f:
            job_config = json.load(f)
    except Exception as e:
        log(f"  ⚠️ 无法读取作业配置: {e}", "WARN")
        job_config = {}

    required_equipment = job_config.get("equipment", [])
    required_strategy = job_config.get("strategy", "优选策略")
    buff_name = job_config.get("buff", "智能空域控制机")
    required_opers = [op.get("name", "") for op in job_config.get("opers", [])]
    tool_men = job_config.get("tool_men", {})

    # 0. 先检查当前是否已在"开始部署"界面(用户可能已手动操作到这)
    p_pre = shot("pre_check")
    t_pre = ocr_text(p_pre)
    before_counts = parse_sss_reward_counts(t_pre)
    if "开始部署" in t_pre:
        log("  ✅ 已在'开始部署'界面, 直接启动MAA!")
        _SSS_NEED_MANUAL = False
        # 直接跳到启动MAA步骤
        log("  → 启动MAA SSS Copilot...")
        if not run_maa_copilot(job_path, allow_sss_deploy=True):
            log("  ❌ MAA启动失败", "ERROR")
            return False
        r = wait_maa_complete(timeout=1800)
        if r is not True:
            log(f"  ❌ MAA执行异常: {r}", "ERROR")
            if _check_sss_begin_exceeded():
                log("  🔍 检测到SSSBegin超限", "ERROR")
            return False
        wait(5)
        dismiss_reward()
        p7 = shot("sss_result")
        t7 = ocr_text(p7)
        evidence = _sss_full_clear_evidence(
            t7, p7, before_counts, _get_current_maa_run_log()
        )
        log(f"  [结算页] OCR: {t7[:100]}；证据={evidence}")
        if evidence["completed"]:
            log(f"  ✅ SSS Copilot当前全阶段实体通关完成，奖励={evidence['counts']}")
            return True
        log("  ❌ MAA队列结束，但游戏页/奖励没有保全全阶段完成证据", "ERROR")
        return False

    # 0b. 检查是否在进行中的保全任务页面(暂停任务/结束委托)
    if "暂停任务" in t_pre or "结束委托" in t_pre:
        log("  [检测] 在进行中的保全任务页面, 尝试继续或结束")
        # 如果有"开始部署"按钮在附近, 直接用
        if "开始部署" in t_pre:
            log("  ✅ 检测到'开始部署', 直接启动MAA!")
            _SSS_NEED_MANUAL = False
            log("  → 启动MAA SSS Copilot...")
            if not run_maa_copilot(job_path, allow_sss_deploy=True):
                return False
            r = wait_maa_complete(timeout=1800)
            if r is not True:
                log(f"  ❌ MAA执行异常: {r}", "ERROR")
                return False
            wait(5)
            dismiss_reward()
            p7 = shot("sss_result")
            t7 = ocr_text(p7)
            evidence = _sss_full_clear_evidence(
                t7, p7, before_counts, _get_current_maa_run_log()
            )
            if evidence["completed"]:
                log(f"  ✅ SSS Copilot当前全阶段实体通关完成，奖励={evidence['counts']}")
                return True
            log("  ❌ MAA队列结束，但游戏页/奖励没有保全全阶段完成证据", "ERROR")
            return False
        # 否则点击"结束委托"回到主页面
        items_pre = ocr(p_pre)
        end_pos = find_text(items_pre, "结束委托") or find_text(items_pre, "结束")
        if end_pos:
            tap(*end_pos)
            log(f"  [结束委托] @{end_pos}")
            wait(5)
            # 可能有确认弹窗
            p_end = shot("end_confirm")
            t_end = ocr_text(p_end)
            if "确认" in t_end:
                items_end = ocr(p_end)
                confirm_pos = find_text(items_end, "确认") or (1100, 700)
                tap(*confirm_pos)
                wait(5)

    # 1. 在保全派驻主页面点击区域卡片
    if not select_sss_region(region_name):
        return False
    wait(5)

    # 2. 检查区域详情页
    p = shot("sss_region_detail")
    t = ocr_text(p)
    items = ocr(p)
    log(f"  [详情页] OCR: {t[:80]}")

    # 3. 检测全权委托是否可用 (已通关区域才有)
    delegate_pos = find_text(items, "全权委托")
    delegate_locked = ("不使用好友助战" in t) or ("BEST RECORD" in t and "通关于" not in t) or \
                      ("通关" in t and "解锁" in t)

    if delegate_pos and not delegate_locked:
        log("  → 全权委托可用，先核对代理卡到期分桶与周一5张保留线")
        tap(*delegate_pos)
        wait(4)
        p2 = shot("delegate_confirm")
        t2 = ocr_text(p2)
        items2 = ocr(p2)
        confirm_pos = find_text(items2, "确认使用") or find_text(items2, "确认")
        card_decision = _sss_delegate_card_decision(t2)
        log(f"  [代理卡门禁] {card_decision['reason']}")
        if confirm_pos and card_decision["allow"]:
            tap(*confirm_pos)
            log("  [全权委托] 确认使用")
            wait(15)
            p_reward = shot("sss_delegate_reward")
            t_reward = ocr_text(p_reward)
            reward_seen = get_state() in ("victory", "reward") or any(
                marker in t_reward
                for marker in ("获得物资", "委托完成", "清理完成", "任务完成")
            )
            dismiss_reward()
            p_delegate = shot("sss_delegate_result")
            t_delegate = ocr_text(p_delegate)
            delegate_evidence = any(
                marker in t_delegate
                for marker in ("清理完成", "委托完成", "任务完成", "获得物资")
            )
            after_counts = parse_sss_reward_counts(t_delegate)
            counts_increased = any(
                isinstance(before_counts.get(key), int)
                and isinstance(after_counts.get(key), int)
                and after_counts[key] > before_counts[key]
                for key in ("strip", "device")
            )
            if reward_seen or delegate_evidence or counts_increased:
                log("  ✅ 全权委托完成，已取得奖励/委托结算证据")
                return True
            log("  ❌ 已确认使用全权委托，但未取得奖励或委托结算证据", "ERROR")
            return False
        else:
            log("  ⚠️ 全权委托未通过库存/到期门禁，回退到实体通关")
            if confirm_pos:
                back()
                wait(3)
                p = shot("sss_region_detail_after_delegate_guard")
                t = ocr_text(p)
                items = ocr(p)

    # 4. 实体通关: 点击"开始保全作战"
    log("  → 使用实体通关(MAA SSS Copilot)")
    start_pos = find_text(items, "开始保全作战") or find_text(items, "开始")
    if start_pos:
        tap(*start_pos)
    else:
        log("  ❌ 详情页没有识别到'开始保全作战'，拒绝点击固定坐标", "ERROR")
        return False
    log("  [开始保全作战]")
    wait(5)

    # 5. 自动穿越SSS设置页面 (导能元件 → 装备 → 编队 → 开始部署)
    # 🔴 2026-07-08 改为自动导航, 不再弹窗阻塞等人工操作
    # 无法自动满足作业编队时必须安全退出并统一清理，不能无限保留前台。
    _SSS_NEED_MANUAL = False
    log("  [自动设置] 尝试自动穿越装备/编队页面...")
    
    reached_deploy = False
    setup_start = time.time()
    last_setup_signature = None
    unchanged_setup_reads = 0
    while time.time() - setup_start < 120:  # 最多2分钟
        wait(4)
        p_setup = shot("sss_setup")
        t_setup = ocr_text(p_setup)

        # 选择平台失败时，旧逻辑可能误点到主页的导能元件说明卡，并在同一
        # 位置反复点击两分钟。说明页不是作战设置页，必须立即停损。
        if "仅可用于" in t_setup and "选择定向导能元件" not in t_setup:
            log("  ❌ 当前是导能元件说明页，不是保全作战设置页；停止盲点", "ERROR")
            return False

        setup_signature = re.sub(r"\s+", "", t_setup)[:180]
        if setup_signature and setup_signature == last_setup_signature:
            unchanged_setup_reads += 1
        else:
            unchanged_setup_reads = 0
            last_setup_signature = setup_signature
        if unchanged_setup_reads >= 3:
            log(f"  ❌ 保全设置页连续未变化，停止重复点击；OCR={t_setup[:100]}", "ERROR")
            return False
        
        if "开始部署" in t_setup:
            log("  ✅ 已到达'开始部署'界面!")
            reached_deploy = True
            break
        
        # 检测导能元件选择页面
        if "选择定向导能元件" in t_setup or "ENERGYCONDUCTION" in t_setup or "定向导能元件" in t_setup:
            items_setup = ocr(p_setup)
            # 新周期首次进入没有默认选中项；必须先按作业buff精确选卡，
            # 再点击确认，不能把灰色确认按钮的存在误当成已选择。
            buff_pos = find_text(items_setup, buff_name, exact=True) or find_text(items_setup, buff_name)
            if not buff_pos:
                log(f"  ❌ 当前元件页未找到作业指定元件'{buff_name}'", "ERROR")
                return False
            tap(*buff_pos)
            log(f"  [导能元件] 选择'{buff_name}' @{buff_pos}")
            wait(2)
            selected_path = shot("sss_buff_selected")
            selected_items = ocr(selected_path)
            confirm_pos = find_text(selected_items, "确认选择") or find_text(selected_items, "确认")
            if confirm_pos:
                tap(*confirm_pos)
                log(f"  [导能元件] 点击确认 @{confirm_pos}")
            else:
                log(
                    f"  ❌ 未识别到导能元件确认按钮；拒绝默认坐标点击。作业要求={buff_name}",
                    "ERROR",
                )
                return False
            wait(3)
            continue
        
        # 检测编队页面必须早于战术装备。编队页底部导航也包含“战术装备”，
        # 若先做宽泛装备匹配，会把已经抵达的编队页再次当成装备页点击。
        if (
            "首批作战小队选任" in t_setup
            or "阵容确认" in t_setup
            or "快捷编队" in t_setup
            or "FORMATION" in t_setup
        ):
            if not _configure_sss_formation(region_name, job_config):
                log(f"  [编队证据] 已保存: {p_setup}", "ERROR")
                return False
            continue

        # 检测战术装备配置页面。只接受该页面独有标题/按钮，不能因底部
        # 导航栏里出现“战术装备”就进入此分支。
        if "请确认战术装备配置" in t_setup or "装备确认" in t_setup:
            if not isinstance(required_equipment, list) or len(required_equipment) != 8:
                log(f"  ❌ 作业战术装备数组无效: {required_equipment}", "ERROR")
                return False
            try:
                from PIL import Image
                with Image.open(p_setup) as equipment_image:
                    width, height = equipment_image.size
            except Exception:
                width, height = 1920, 1080
            # 页面顺序为：先锋、重装、术师、辅助 / 近卫、狙击、医疗、特种。
            # A/B点击区分别位于每张卡上沿的1/4和3/4处。
            column_centers = (0.13, 0.38, 0.63, 0.88)
            row_y = (0.216, 0.535)
            for index, choice in enumerate(required_equipment):
                normalized = str(choice).strip().upper()
                if normalized not in ("A", "B"):
                    log(f"  ❌ 作业战术装备第{index + 1}项不是A/B: {choice}", "ERROR")
                    return False
                card_center = column_centers[index % 4]
                x = int(width * (card_center + (-0.058 if normalized == "A" else 0.058)))
                y = int(height * row_y[index // 4])
                tap(x, y)
                wait(0.3)
            configured_path = shot("sss_equipment_configured")
            configured_items = ocr(configured_path)
            confirm_pos = find_text(configured_items, "装备确认", exact=True) or find_text(
                configured_items, "装备确认"
            )
            if not confirm_pos:
                log("  ❌ 未识别到右下角'装备确认'按钮；拒绝点击页眉", "ERROR")
                return False
            tap(*confirm_pos)
            log(f"  [战术装备] 已按作业设置{required_equipment}，点击装备确认 @{confirm_pos}")
            wait(5)
            continue
        
        # 日志输出当前未知状态
        elapsed = int(time.time() - setup_start)
        if elapsed % 30 < 5:
            log(f"  [自动设置] {elapsed}s, 当前OCR: {t_setup[:60]}")
    
    if not reached_deploy:
        log("  ⚠️ 自动设置超时(120s), 可能是首次进入需要手动配置")
        # 回退到等待模式 (最多3分钟)
        fallback_start = time.time()
        while time.time() - fallback_start < 180:
            wait(10)
            p_check = shot("wait_deploy")
            t_check = ocr_text(p_check)
            if "开始部署" in t_check:
                log("  ✅ 检测到'开始部署'按钮!")
                reached_deploy = True
                break
            elapsed = int(time.time() - fallback_start)
            if elapsed % 60 < 15:
                log(f"  [等待] {elapsed}s, OCR: {t_check[:50]}")
    
    if not reached_deploy:
        log("  ❌ 无法到达'开始部署'界面(总计5分钟)", "ERROR")
        return False

    # 7. 启动MAA SSS Copilot
    log("  → 启动MAA SSS Copilot...")
    if not run_maa_copilot(job_path, allow_sss_deploy=True):
        log("  ❌ MAA启动失败", "ERROR")
        return False

    # 8. 等待MAA完成
    r = wait_maa_complete(timeout=1800)
    if r is not True:
        log(f"  ❌ MAA执行异常: {r}", "ERROR")
        if _check_sss_begin_exceeded():
            log("  🔍 检测到SSSBegin超限: 编队或装备配置不符合作业要求", "ERROR")
        return False

    # 9. 结算
    wait(5)
    dismiss_reward()

    # 10. 验证通关
    p7 = shot("sss_result")
    t7 = ocr_text(p7)
    evidence = _sss_full_clear_evidence(
        t7, p7, before_counts, _get_current_maa_run_log()
    )
    log(f"  [结算页] OCR: {t7[:100]}；证据={evidence}")

    if evidence["completed"]:
        log(f"  ✅ SSS Copilot当前全阶段实体通关完成，奖励={evidence['counts']}")
        return True
    elif "失败" in t7 or "重试" in t7:
        log(f"  ❌ SSS战斗失败", "ERROR")
        return False
    else:
        log(f"  ❌ 无法从游戏结算页确认当前全阶段完成，不写入保全完成记录", "ERROR")
        return False
def mode_security():
    """按月中刷新周期循环执行保全，直到60/60与24/24都有当前页证据。"""
    log("=" * 60)
    log("  场景: 保全派驻")
    log("=" * 60)
    
    # 1. 导航到保全派驻；周期和开放平台都必须从同一当前页面读取。
    if not goto_sss_page():
        log("  ❌ 无法进入保全派驻页面", "ERROR")
        _RUN_SUMMARY["security"] = {"status": "blocked", "reason": "navigation_failed"}
        return False

    context = discover_current_sss_context()
    current_period = context["area_period"]
    reward_cycle = context["reward_cycle"]
    reward_counts = context["reward_counts"]
    active_regions = context["regions"]
    log(f"  区域期: {current_period}；奖励周期: {reward_cycle}；当前奖励: {reward_counts}")
    if reward_counts.get("strip") is None or reward_counts.get("device") is None:
        log("  ❌ 无法从当前保全主页读取60/24奖励计数，拒绝用历史进度代替", "ERROR")
        _RUN_SUMMARY["security"] = {
            "status": "blocked", "reason": "reward_counts_unrecognized",
            "period": current_period, "reward_cycle": reward_cycle,
            "reward_counts": reward_counts, "active_regions": active_regions,
            "screenshots": context["screenshots"],
        }
        return False
    if sss_rewards_capped(reward_counts):
        log(f"  ℹ️ 当前奖励页({reward_cycle})已封顶60/60、24/24, 无需识别平台或加载作业")
        _RUN_SUMMARY["security"] = {
            "status": "completed", "reason": "current_reward_page_capped",
            "period": current_period, "reward_cycle": reward_cycle,
            "reward_counts": reward_counts, "reward_capped": True,
            "active_regions": active_regions,
            "evidence": "current_sss_reward_page_60_60_24_24",
        }
        prog = load_sss_progress()
        prog.update({
            "current_period": current_period,
            "area_period": current_period,
            "reward_cycle": reward_cycle,
            "reward_counts": reward_counts,
            "reward_capped": True,
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "evidence": "current_sss_reward_page_60_60_24_24",
        })
        save_sss_progress(prog)
        return True
    if not active_regions:
        log("  ❌ 奖励未封顶且无法从当前游戏页确认本期开放平台；拒绝使用旧硬编码区域", "ERROR")
        _RUN_SUMMARY["security"] = {
            "status": "blocked", "reason": "regions_unrecognized",
            "period": current_period, "reward_cycle": reward_cycle,
            "reward_counts": reward_counts, "screenshots": context["screenshots"],
        }
        return False
    log(f"  开放区域: {active_regions}")
    log("  策略: 选择精确匹配作业，重复完整清理；每轮必须看到奖励计数增长")

    # 优先运行当前有精确作业且优先级高的平台；一个平台可重复清理，无需把每个平台各打一遍。
    runnable = []
    blocked = []
    for region_name in active_regions:
        job_path, _ = _select_sss_job(region_name)
        if job_path:
            runnable.append((int((SSS_REGION_CATALOG.get(region_name) or {}).get("priority", 0)), region_name, job_path))
        else:
            blocked.append({
                "region": region_name,
                "reason": "matching_job_missing",
            })
    runnable.sort(key=lambda item: item[0], reverse=True)
    attempts = []
    successful_clears = 0
    if not runnable:
        log("  ❌ 当前开放平台均无精确匹配保全作业", "ERROR")
    else:
        target_region = runnable[0][1]
        target_job = runnable[0][2]
        log(f"  [执行目标] {target_region} / {os.path.basename(target_job)}")
        # 0/0通常需要三次完整清理到60/24。实体作业可能在末层概率失败；
        # 允许最多连续3次失败，但每次成功即清零，且总运行次数仍限制为8轮。
        consecutive_failures = 0
        for attempt in range(1, 9):
            if sss_rewards_capped(reward_counts):
                break
            log(f"\n--- 保全清理第{attempt}轮: {target_region} ---")
            if not goto_sss_page():
                blocked.append({"region": target_region, "reason": "return_to_sss_failed"})
                break
            before = dict(reward_counts)
            ok = run_sss_copilot(target_region)
            record = {
                "attempt": attempt,
                "region": target_region,
                "job": target_job,
                "before": before,
                "battle_or_delegate_closed": bool(ok),
            }
            if not ok:
                record["status"] = "run_failed_or_prerequisite_unmet"
                attempts.append(record)
                consecutive_failures += 1
                if _sss_retry_allowed(consecutive_failures):
                    log(
                        f"  ↻ 当前轮未闭环；连续失败{consecutive_failures}/3，"
                        "保留有限重试机会",
                        "WARN",
                    )
                    continue
                blocked.append({
                    "region": target_region,
                    "reason": "three_consecutive_run_failures",
                })
                log("  ⏸ 保全连续失败已达3次，停止重复同一作业", "WARN")
                break
            if not goto_sss_page():
                record["status"] = "post_run_page_failed"
                attempts.append(record)
                blocked.append({"region": target_region, "reason": record["status"]})
                break
            after_context = discover_current_sss_context()
            after = after_context["reward_counts"]
            record["after"] = after
            increased = any(
                isinstance(before.get(key), int) and isinstance(after.get(key), int)
                and after[key] > before[key]
                for key in ("strip", "device")
            )
            if not increased and not sss_rewards_capped(after):
                record["status"] = "reward_counts_not_increased"
                attempts.append(record)
                blocked.append({"region": target_region, "reason": record["status"]})
                log("  ❌ MAA/委托终态后奖励计数未增长，不计为有效清理", "ERROR")
                break
            record["status"] = "verified_clear"
            attempts.append(record)
            successful_clears += 1
            consecutive_failures = 0
            reward_counts = after
            log(f"  ✅ 第{attempt}轮奖励增长: {before} → {after}")

    reward_capped = sss_rewards_capped(reward_counts)
    prog = load_sss_progress()
    prog.update({
        "current_period": current_period,
        "area_period": current_period,
        "reward_cycle": reward_cycle,
        "reward_counts": reward_counts,
        "reward_capped": reward_capped,
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "completed_regions": sorted({item["region"] for item in attempts if item.get("status") == "verified_clear"}),
        "attempts": attempts,
    })
    save_sss_progress(prog)

    goto_main_menu()
    log(f"\n保全派驻奖励: 数据增补条{reward_counts.get('strip')}/60，数据增补仪{reward_counts.get('device')}/24")
    _RUN_SUMMARY["security"] = {
        "status": "completed" if reward_capped else "partial",
        "period": current_period,
        "reward_cycle": reward_cycle,
        "reward_counts": reward_counts,
        "reward_capped": reward_capped,
        "active_regions": active_regions,
        "completed_regions": prog["completed_regions"],
        "successful_clears": successful_clears,
        "attempts": attempts,
        "blocked_regions": blocked,
        "screenshots": context["screenshots"],
    }
    if reward_capped:
        log("✅ 本奖励周期保全派驻已封顶")
    else:
        log("⚠️ 保全派驻奖励未封顶；已按真实阻塞原因留账", "WARN")
    return reward_capped

ROGUELIKE_TUTORIAL_MARKERS = (
    "留存招募券", "通宝", "本期集成战略包含", "岁兽残识",
    "勘察设备", "坍缩范式", "密文板", "密文宣告", "独眼巨人的远见",
)


def _close_roguelike_tutorial_once():
    """Close one verified emulator-first tutorial; never click a generic dialog blindly."""
    path = shot("roguelike_tutorial_probe")
    items = ocr(path)
    text = " ".join(label for label, _, _ in items)
    if "关闭" not in text or not any(marker in text for marker in ROGUELIKE_TUTORIAL_MARKERS):
        return None
    close_pos = find_text(items, "关闭", exact=True) or find_text(items, "关闭")
    if not close_pos:
        return None
    marker = next(marker for marker in ROGUELIKE_TUTORIAL_MARKERS if marker in text)
    tap(*close_pos)
    wait(3)
    log(f"→ 已关闭肉鸽模拟器首次教学页并准备接管同一局: {marker}")
    return {"marker": marker, "screenshot": path, "position": close_pos}


def _close_roguelike_interruption_once():
    """Recover one verified non-battle page left behind by a Roguelike run.

    A first clear can end on a theme story cutscene after MaaCore has already
    emitted ``TaskChainError``.  Reopening MAA cannot change that screen, so
    counting each retry as a new technical crash only burns the restart budget
    and eventually closes the emulator.  Handle the verified story UI through
    ADB first; keep the older first-emulator tutorial recovery as the fallback.
    """
    path = shot("roguelike_interruption_probe")
    items = ocr(path)
    text = " ".join(label for label, _, _ in items)
    if "查看数据回溯" in text:
        current_text = text
        actions = []
        after_path = path
        for _ in range(4):
            if any(marker in current_text for marker in (
                "获得生机细胞",
                "分数合计",
                "得分",
                "通讯记录已收录",
            )):
                pos = POS_MIZUKI_REVIEW_DONE
                action = "完成统计"
            else:
                pos = POS_MIZUKI_REVIEW_NEXT
                action = "翻到统计"
            tap(*pos)
            actions.append(action)
            wait(5)
            after_path = shot("roguelike_data_review_summary_after")
            current_text = " ".join(label for label, _, _ in ocr(after_path))
            if "查看数据回溯" not in current_text:
                log(f"→ 已闭环水月首次结局回顾页: {' → '.join(actions)}")
                return {
                    "kind": "mizuki_data_review_summary",
                    "marker": "查看数据回溯",
                    "screenshot": path,
                    "actions": actions,
                    "state_after": "left_data_review_summary",
                }
        log("❌ 水月首次结局回顾页4次操作后仍未退出，保留现场", "ERROR")
        return None

    if "数据回溯" in text and "开始回溯" in text:
        start_pos = (
            find_text(items, "开始回溯", exact=True)
            or find_text(items, "开始回溯")
            or POS_MIZUKI_DATA_REVIEW_START
        )
        tap(*start_pos)
        wait(6)
        after_path = shot("roguelike_data_review_after")
        after_text = " ".join(label for label, _, _ in ocr(after_path))
        if "数据回溯" in after_text and "开始回溯" in after_text:
            log("❌ 水月数据回溯页点击后仍未退出，保留现场并拒绝盲目重启", "ERROR")
            return None
        log("→ 已完成水月首次结局数据回溯，允许恢复同一肉鸽队列")
        return {
            "kind": "mizuki_data_review",
            "marker": "开始回溯",
            "screenshot": path,
            "position": start_pos,
            "state_after": "left_data_review",
        }

    compact = re.sub(r"\s+", "", text)
    # 银淞结算可能先展示本轮新解锁收藏品和生态标本奖励。这个页面只在
    # “新解锁 + 获得生态标本”两个稳定锚点同时存在时处理；一次点击后
    # 必须证明原页面消失。后续仍可能出现科考记录页，由下一次安全扫描
    # 继续处理，不能把一层奖励页消失误报为整条结算链完成。
    if "本次探索新解锁" in compact and "获得生态标本" in compact:
        reward_pos = (
            find_text(items, "获得生态标本", exact=True)
            or find_text(items, "获得生态标本")
            or (1050, 914)
        )
        tap(*reward_pos)
        wait(5)
        after_path = shot("sami_collection_reward_after")
        after_compact = re.sub(
            r"\s+", "", " ".join(label for label, _, _ in ocr(after_path))
        )
        if (
            "本次探索新解锁" in after_compact
            and "获得生态标本" in after_compact
        ):
            log("❌ 银淞收藏品结算确认后页面未退出，保留现场", "ERROR")
            return None
        log("→ 已确认银淞收藏品/生态标本结算层，继续扫描后续安全页")
        return {
            "kind": "sami_collection_reward",
            "marker": "获得生态标本",
            "screenshot": path,
            "position": reward_pos,
            "state_after": "left_collection_reward",
        }


    # 银淞首次完整探索会在回顾页之后弹出科考记录经验确认层。MAA 6.16.8
    # 会在此发出 TaskChainError；这已是整轮结算安全边界，不是新战斗。
    # 仅在“科考记录 + 明确经验进度比”同时成立时点击固定圆勾，并用页面
    # 消失作验收，避免把普通奖励弹窗或肉鸽主页误关。
    if "科考记录" in compact and re.search(r"\d{1,4}/\d{1,4}", compact):
        confirm_pos = (960, 900)
        tap(*confirm_pos)
        wait(5)
        after_path = shot("sami_expedition_records_after")
        after_text = re.sub(
            r"\s+", "", " ".join(label for label, _, _ in ocr(after_path))
        )
        if "科考记录" in after_text and re.search(
            r"\d{1,4}/\d{1,4}", after_text
        ):
            log("❌ 银淞科考记录确认后页面未退出，保留现场", "ERROR")
            return None
        log("→ 已确认银淞科考记录结算，进入文化比较安全边界")
        return {
            "kind": "sami_expedition_records",
            "marker": "科考记录",
            "screenshot": path,
            "position": confirm_pos,
            "state_after": "left_expedition_records_reward",
        }


    story_markers = ("跳过", "SKIP", "自动OFF", "自动 OFF", "幕间")
    if any(marker in text for marker in story_markers):
        state_after = _leave_story_before_daily(max_attempts=8)
        if state_after == "story":
            log("❌ 肉鸽结算剧情仍未退出，保留现场并拒绝盲目重启", "ERROR")
            return None
        log(f"→ 已处理肉鸽结算/解锁剧情，恢复后页面={state_after}")
        return {
            "kind": "story",
            "marker": next(marker for marker in story_markers if marker in text),
            "screenshot": path,
            "state_after": state_after,
        }

    tutorial = _close_roguelike_tutorial_once()
    if tutorial:
        tutorial = dict(tutorial)
        tutorial["kind"] = "tutorial"
    return tutorial


def _roguelike_settlement_details(log_text):
    """Return only direct MaaCore RoguelikeSettlement detail objects in order."""
    settlements = []
    for line in (log_text or "").splitlines():
        if '"what":"RoguelikeSettlement"' not in line:
            continue
        marker = "SubTaskExtraInfo "
        if marker not in line:
            continue
        try:
            payload = json.loads(line.split(marker, 1)[1])
        except (ValueError, TypeError):
            continue
        if payload.get("what") != "RoguelikeSettlement":
            continue
        details = payload.get("details")
        if isinstance(details, dict) and isinstance(details.get("game_pass"), bool):
            settlements.append(dict(details))
    return settlements


def _roguelike_settlement_results(log_text):
    """Return MaaCore settlement diagnostics; never use them as game-clear proof."""
    return [item["game_pass"] for item in _roguelike_settlement_details(log_text)]


PHANTOM_HOME_MARKERS = ("古堡笔记", "幕后筹备", "开始探索")
PHANTOM_NOTES_MARKERS = ("购买等级", "列表中查看")
PHANTOM_PREPARATION_MARKERS = ("当前加成总览", "幕后筹备", "晦暗的灵感")


def _phantom_is_home_text(text):
    text = str(text or "")
    return all(marker in text for marker in PHANTOM_HOME_MARKERS)


def _phantom_is_notes_text(text):
    text = str(text or "")
    return all(marker in text for marker in PHANTOM_NOTES_MARKERS)


def _phantom_is_preparation_text(text):
    text = str(text or "")
    return all(marker in text for marker in PHANTOM_PREPARATION_MARKERS[:2])


def _phantom_find_leftmost(items, keyword):
    matches = [
        (cx, cy) for text, cx, cy in (items or [])
        if keyword in str(text or "")
    ]
    return min(matches, key=lambda pos: pos[0]) if matches else None


def _phantom_theme_entry_position(items):
    """Return the visible Phantom card button, never another theme's button."""
    phantom_titles = [
        (cx, cy) for text, cx, cy in (items or [])
        if "PHANTOM" in str(text or "").upper()
        or "傀影" in str(text or "")
    ]
    buttons = [
        (cx, cy) for text, cx, cy in (items or [])
        if "进入主题" in str(text or "")
    ]
    if not phantom_titles or not buttons:
        return None
    title_x = min(phantom_titles, key=lambda pos: pos[1])[0]
    # One card is roughly 550 px wide.  The entry button sits to the right of
    # its title, so nearest-x is safer than taking the first visible button.
    return min(buttons, key=lambda pos: abs(pos[0] - title_x))


def navigate_to_phantom_home(max_steps=18):
    """Navigate from a known game page to Phantom home with OCR verification.

    This deliberately follows the real UI path: home -> terminal -> long-term
    exploration -> all Integrated Strategies themes -> Phantom.  The terminal
    shortcut card is not used because it inherits the last theme and can enter
    the wrong mode.
    """
    theme_swipes = 0
    evidence = []
    for step in range(max_steps):
        path = shot(f"phantom_progress_nav_{step + 1}")
        items = ocr(path)
        text = " ".join(label for label, _, _ in items)
        evidence.append(path)
        if _phantom_is_home_text(text):
            return {"ok": True, "screenshot": path, "steps": step, "evidence": evidence}

        if _phantom_is_notes_text(text) or _phantom_is_preparation_text(text):
            tap(*POS_BACK)
            wait(3)
            continue

        if "获得物资" in text or "首次获得" in text:
            tap(*POS_DISMISS)
            wait(3)
            continue

        terminal = find_text(items, "终端", exact=True)
        if terminal and any(marker in text for marker in ("编队", "干员", "公开招募")):
            tap(*terminal)
            wait(6)
            continue

        if "ATTENTION" in text and "集成战略" in text:
            # Verified terminal bottom navigation icon for long-term exploration.
            tap(1435, 1000)
            wait(6)
            continue

        if "长期探索" in text and "集成战略" in text and "查看全部主题" in text:
            view_all = [
                (cx, cy) for label, cx, cy in items
                if "查看全部主题" in label and cx < 1100
            ]
            if view_all:
                tap(*min(view_all, key=lambda pos: pos[0]))
                wait(6)
                continue

        theme_entry = _phantom_theme_entry_position(items)
        if theme_entry:
            tap(*theme_entry)
            wait(7)
            continue

        if "进入主题" in text and theme_swipes < 4:
            swipe(500, 850, 1600, 850, 800)
            theme_swipes += 1
            wait(5)
            continue

        # A settlement overlay or a one-off reward page has no unique button;
        # only use the verified bottom confirmation coordinate on those pages.
        if any(marker in text for marker in ("古堡笔记", "获得蜡烛", "本次探索")):
            tap(*POS_DISMISS)
            wait(3)
            continue
        break
    return {"ok": False, "reason": "phantom_home_not_reached", "evidence": evidence}


def _phantom_preparation_points(items):
    """Read the points at the top-right of the preparation page."""
    candidates = []
    for text, cx, cy in items or []:
        match = re.fullmatch(r"\D*(\d{1,5})\D*", str(text or "").strip())
        if match and cx >= 1500 and cy <= 140:
            candidates.append((cx, int(match.group(1))))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def _phantom_upgrade_cost(items):
    for text, _, _ in items or []:
        match = re.search(r"-\s*(\d{1,4})", str(text or ""))
        if match:
            return int(match.group(1))
    return None


def _phantom_available_preparation_nodes(path):
    """Detect bright, not-yet-bought normal and terminal preparation nodes."""
    if not path or not os.path.exists(path):
        return []
    try:
        from PIL import Image
        image = Image.open(path).convert("RGB")
    except Exception:
        return []

    x_candidates = (810, 885, 1110, 1185)
    y_candidates = (215, 290, 395, 470, 575, 655, 755, 840)
    found = []
    for cx in x_candidates:
        for cy in y_candidates:
            crop = image.crop((cx - 55, cy - 55, cx + 55, cy + 55))
            white = 0
            orange = 0
            pixels = (
                crop.get_flattened_data()
                if hasattr(crop, "get_flattened_data")
                else crop.getdata()
            )
            for r, g, b in pixels:
                if min(r, g, b) > 185 and max(r, g, b) - min(r, g, b) < 35:
                    white += 1
                if r > 160 and r - g > 45 and g - b > 20 and b < 110:
                    orange += 1
            if white >= 500 and orange < 100:
                found.append((cx, cy, white))

    # The final TALENT V node is an oval at the far-right edge rather than one
    # of the square grid nodes.  The old detector scanned the page but silently
    # ignored this different geometry, leaving enough points unspent even when
    # the terminal node was visibly unlocked.
    terminal_cx, terminal_cy, terminal_radius = 1580, 570, 75
    terminal = image.crop((
        terminal_cx - terminal_radius,
        terminal_cy - terminal_radius,
        terminal_cx + terminal_radius,
        terminal_cy + terminal_radius,
    ))
    terminal_white = 0
    terminal_orange = 0
    terminal_pixels = (
        terminal.get_flattened_data()
        if hasattr(terminal, "get_flattened_data")
        else terminal.getdata()
    )
    for r, g, b in terminal_pixels:
        if min(r, g, b) > 185 and max(r, g, b) - min(r, g, b) < 35:
            terminal_white += 1
        if r > 160 and r - g > 45 and g - b > 20 and b < 110:
            terminal_orange += 1
    if terminal_white >= 1000 and terminal_orange < 100:
        found.append((terminal_cx, terminal_cy, terminal_white))

    # The alternative x/y grids overlap around real nodes. Keep one strongest
    # center per 90 px cluster so one node cannot consume multiple attempts.
    result = []
    for cx, cy, score in sorted(found, key=lambda item: item[2], reverse=True):
        if any(abs(cx - ox) < 90 and abs(cy - oy) < 90 for ox, oy in result):
            continue
        result.append((cx, cy))
    return sorted(result, key=lambda pos: (pos[1], pos[0]))


def claim_phantom_castle_notes_rewards():
    """Claim currently unlocked Castle Notes rewards and verify the marker clears."""
    nav = navigate_to_phantom_home()
    result = {"ok": False, "claimed": False, "navigation": nav, "screenshots": []}
    if not nav.get("ok"):
        result["reason"] = "phantom_home_not_reached"
        return result

    home = shot("phantom_claim_home")
    home_items = ocr(home)
    notes = find_text(home_items, "古堡笔记", exact=True) or find_text(home_items, "古堡笔记")
    if not notes:
        result["reason"] = "castle_notes_entry_not_found"
        return result
    tap(*notes)
    wait(5)

    before = shot("phantom_claim_before")
    before_items = ocr(before)
    before_text = " ".join(label for label, _, _ in before_items)
    result["screenshots"].append(before)
    if not _phantom_is_notes_text(before_text):
        result["reason"] = "castle_notes_page_not_confirmed"
        return result
    claim = find_text(before_items, "一键领取", exact=True) or find_text(before_items, "一键领取")
    result["claimable_before"] = before_text.count("可领取")
    if not claim:
        result.update({"ok": True, "claimed": False, "reason": "nothing_claimable"})
        tap(*POS_BACK)
        wait(3)
        return result

    tap(*claim)
    wait(4)
    for index in range(16):
        frame = shot(f"phantom_claim_flow_{index + 1}")
        items = ocr(frame)
        text = " ".join(label for label, _, _ in items)
        result["screenshots"].append(frame)
        if _phantom_is_notes_text(text):
            remaining = find_text(items, "一键领取", exact=True) or find_text(items, "一键领取")
            result["claimable_after"] = text.count("可领取")
            if not remaining:
                result.update({"ok": True, "claimed": True, "reason": "claim_marker_cleared"})
                tap(*POS_BACK)
                wait(3)
                return result
            tap(*remaining)
            wait(3)
            continue
        if "首次获得" in text or "获得物资" in text or index < 3:
            tap(*POS_DISMISS)
            wait(3)
            continue
        break
    result["reason"] = "claim_flow_not_closed"
    return result


def apply_phantom_preparation_points(max_upgrades=16, max_sections=7):
    """Spend every currently affordable Phantom preparation point safely."""
    result = {"ok": False, "upgrades": [], "scans": [], "screenshots": []}
    nav = navigate_to_phantom_home()
    result["navigation"] = nav
    if not nav.get("ok"):
        result["reason"] = "phantom_home_not_reached"
        return result

    for _ in range(max_upgrades + 1):
        purchased = False
        for section in range(max_sections):
            home = shot("phantom_preparation_home")
            home_items = ocr(home)
            prep = find_text(home_items, "幕后筹备", exact=True) or find_text(home_items, "幕后筹备")
            if not prep:
                result["reason"] = "preparation_entry_not_found"
                return result
            tap(*prep)
            wait(4)
            for _swipe in range(section):
                swipe(1600, 520, 500, 520, 800)
                wait(2)

            page = shot(f"phantom_preparation_scan_s{section}")
            page_items = ocr(page)
            page_text = " ".join(label for label, _, _ in page_items)
            result["screenshots"].append(page)
            if not _phantom_is_preparation_text(page_text):
                result["reason"] = "preparation_page_not_confirmed"
                return result
            points = _phantom_preparation_points(page_items)
            nodes = _phantom_available_preparation_nodes(page)
            result["scans"].append({"section": section, "points": points, "nodes": nodes})
            if nodes:
                node = nodes[0]
                tap(*node)
                wait(3)
                detail = shot(f"phantom_preparation_candidate_s{section}")
                detail_items = ocr(detail)
                detail_text = " ".join(label for label, _, _ in detail_items)
                result["screenshots"].append(detail)
                confirm = (
                    find_text(detail_items, "确认升级", exact=True)
                    or find_text(detail_items, "确认升级")
                )
                cost = _phantom_upgrade_cost(detail_items)
                if confirm and (points is None or cost is None or points >= cost):
                    tap(*confirm)
                    wait(4)
                    after = shot(f"phantom_preparation_purchased_s{section}")
                    after_items = ocr(after)
                    after_text = " ".join(label for label, _, _ in after_items)
                    after_points = _phantom_preparation_points(after_items)
                    result["screenshots"].append(after)
                    verified = (
                        "已升级" in after_text
                        and (
                            points is None
                            or after_points is None
                            or after_points < points
                        )
                    )
                    result["upgrades"].append({
                        "section": section,
                        "node": node,
                        "cost": cost,
                        "points_before": points,
                        "points_after": after_points,
                        "verified": verified,
                    })
                    tap(*POS_BACK)
                    wait(3)
                    if not verified:
                        result["reason"] = "upgrade_not_verified"
                        return result
                    purchased = True
                    break

            tap(*POS_BACK)
            wait(3)
        if not purchased:
            result.update({
                "ok": True,
                "reason": "no_affordable_unlocked_node",
                "points_remaining": (
                    result["scans"][-1].get("points") if result["scans"] else None
                ),
            })
            return result

    result["reason"] = "upgrade_budget_exhausted"
    return result


def service_phantom_progress(check_preparation=False):
    """Service a settled Phantom run without reopening completed progression.

    Backstage preparation is already fully maxed on this account.  It is only
    revisited when an explicit caller opts in; normal settlement service now
    claims Castle Notes rewards and leaves the completed tree alone.
    """
    claim = claim_phantom_castle_notes_rewards()
    preparation = (
        apply_phantom_preparation_points()
        if check_preparation
        else {
            "ok": True,
            "skipped": True,
            "reason": "preparation_fully_maxed",
            "upgrades": [],
        }
    )
    return {
        "ok": bool(claim.get("ok") and preparation.get("ok")),
        "claim": claim,
        "preparation": preparation,
        "serviced_at": datetime.now().isoformat(timespec="seconds"),
    }


MIZUKI_HOME_MARKERS = ("生态谱系", "开始探索")
MIZUKI_COGNITION_MARKERS = ("认知塑造", "主观想象", "认知完备")


def _mizuki_is_home_text(text):
    text = re.sub(r"\s+", "", str(text or ""))
    # RapidOCR sometimes returns the two large glyph groups in opposite reading
    # order ("开始" ... "探索").  Requiring the concatenated token rejected a
    # real Deep Exploration home even though both words and Ecology Pedigree
    # were present.
    has_start = "开始探索" in text or ("开始" in text and "探索" in text)
    return (
        "生态谱系" in text
        and has_start
        and any(marker in text for marker in (
            "认知塑造", "认知完备", "深入探索", "追忆映射", "常规行动",
        ))
    )


def _mizuki_is_cognition_text(text):
    """Require the cognition page, never the similarly named home entry."""
    text = re.sub(r"\s+", "", str(text or ""))
    # The home OCR often splits the large action label into two tokens
    # (``开始`` and ``探索``).  Testing only the unspaced literal caused the
    # already-complete home to be mistaken for the cognition tree, after which
    # the Back key escaped the Mizuki theme and could land on another theme.
    if "生态谱系" in text and "开始探索" in text:
        return False
    return (
        "开始探索" not in text
        and (
            # The tree itself labels the counter as Subjective Imagination;
            # "Cognitive Shaping" is only present on the home-page entry.
            (
                "主观想象" in text
                and (
                    "认知塑造" in text
                    or any(marker in text for marker in (
                        "已塑造", "当前加成", "资源调配", "理性与判断", "生存本能", "攻击性",
                    ))
                )
            )
            or (
                "认知完备" in text
                and any(marker in text for marker in ("合计加成", "属性", "探索", "分队"))
            )
        )
    )


def _mizuki_is_active_exploration_detail_text(text):
    """Recognise a resumable exploration detail without resuming it.

    The theme remembers an unfinished Deep Exploration and can open on the
    guide-port page whose only forward action is ``继续探索``.  That page is a
    valid navigation intermediate, not the Mizuki home and not proof that any
    reward is complete.  Reward verification must back out of it first; it must
    never press Continue merely to make progress through navigation.
    """
    compact = re.sub(r"\s+", "", str(text or ""))
    return (
        "继续探索" in compact
        and (
            "导览信息端口" in compact
            or "探索奖励" in compact
            or "驻扎" in compact
        )
        and any(marker in compact for marker in (
            "深入探索", "追忆映射", "常规行动",
        ))
    )


def _mizuki_abandon_active_exploration_for_verification():
    """Close a remembered active run so permanent rewards can be inspected.

    This mirrors MAA's 1280x720 Roguelike StartExplore -> Abandon -> Confirm
    regions at the emulator's fixed 1920x1080 resolution.  Every write click is
    still gated by the real OCR page before it: the guide-port page must expose
    Continue, and the confirmation dialog must explicitly say Abandon.
    """
    result = {"ok": False, "screenshots": []}
    detail = shot("mizuki_active_detail_before_abandon")
    detail_items = ocr(detail)
    detail_text = " ".join(label for label, _, _ in detail_items)
    result["screenshots"].append(detail)
    if not _mizuki_is_active_exploration_detail_text(detail_text):
        result["reason"] = "active_detail_not_confirmed"
        return result

    continue_pos = (
        find_text(detail_items, "继续探索", exact=True)
        or find_text(detail_items, "继续探索")
    )
    if not continue_pos:
        result["reason"] = "continue_exploration_not_found"
        return result
    tap(*continue_pos)
    wait(7)

    active = shot("mizuki_active_map_before_close")
    active_text = re.sub(r"\s+", "", ocr_text(active))
    result["screenshots"].append(active)
    # MAA's Abandon control lives in [1076,243,177,179] at 1280x720.
    # The active map must no longer be the guide port and must contain at least
    # one stable roguelike HUD/map marker before the fixed-region click.
    active_markers = (
        "目标生命", "源石锭", "希望", "节点", "层", "探索进度", "当前探索",
    )
    if "继续探索" in active_text or not any(
        marker in active_text for marker in active_markers
    ):
        result["reason"] = "active_map_not_confirmed"
        return result
    tap(1747, 499)
    wait(3)

    confirm = shot("mizuki_abandon_confirm")
    confirm_items = ocr(confirm)
    confirm_text = re.sub(
        r"\s+", "", " ".join(label for label, _, _ in confirm_items)
    )
    result["screenshots"].append(confirm)
    if "放弃" not in confirm_text or not any(
        marker in confirm_text for marker in ("探索", "确认", "确定")
    ):
        result["reason"] = "abandon_confirmation_not_confirmed"
        return result
    confirm_pos = (
        find_text(confirm_items, "确认", exact=True)
        or find_text(confirm_items, "确定", exact=True)
    )
    if confirm_pos:
        tap(*confirm_pos)
    else:
        # MAA's confirmation ROI [720,413,249,168] scaled by 1.5.
        tap(1267, 745)
    wait(8)
    result.update({"ok": True, "reason": "active_exploration_abandoned"})
    return result


def _mizuki_cognition_points(items):
    """Read Subjective Imagination from the Mizuki home/tree UI.

    The home entry often OCRs as one label (``认知塑造 18``), while the tree
    page may split the icon label and number.  Only accept a nearby small
    integer so Ecology Pedigree level and difficulty cannot be mistaken for
    spendable cognition points.
    """
    normalized = []
    for text, cx, cy in items or []:
        label = str(text or "").strip()
        normalized.append((label, int(cx), int(cy)))
        if "认知完备" in label:
            return 0
        if "认知塑造" in label or "主观想象" in label:
            match = re.search(r"(\d{1,3})", label)
            if match:
                return int(match.group(1))

    anchors = [
        (cx, cy) for label, cx, cy in normalized
        if "认知塑造" in label or "主观想象" in label
    ]
    candidates = []
    for label, cx, cy in normalized:
        if not re.fullmatch(r"\d{1,3}", label):
            continue
        value = int(label)
        for ax, ay in anchors:
            distance = abs(cx - ax) + abs(cy - ay)
            if distance <= 260:
                candidates.append((distance, value))
                break
    return min(candidates, default=(0, None), key=lambda item: item[0])[1]


def _mizuki_cognition_progress(items):
    """Read the permanent-tree completion counter such as ``53/58``."""
    for text, _, _ in items or []:
        match = re.search(r"(\d{1,3})\s*/\s*(\d{1,3})", str(text or ""))
        if match:
            current, total = map(int, match.groups())
            if 0 <= current <= total <= 999:
                return current, total
    return None


def _mizuki_theme_entry_position(items):
    """Return only the visible Mizuki theme-card entry button."""
    titles = [
        (cx, cy) for text, cx, cy in (items or [])
        if "MIZUKI" in str(text or "").upper()
        or "水月与深蓝之树" in str(text or "")
    ]
    buttons = [
        (cx, cy) for text, cx, cy in (items or [])
        if "进入主题" in str(text or "")
    ]
    if not titles or not buttons:
        return None
    title_x = min(titles, key=lambda pos: pos[1])[0]
    return min(buttons, key=lambda pos: abs(pos[0] - title_x))


def navigate_to_mizuki_home(max_steps=18):
    """Reach the real Mizuki home through verified OCR states only."""
    theme_swipes = 0
    evidence = []
    for step in range(max_steps):
        path = shot(f"mizuki_progress_nav_{step + 1}")
        items = ocr(path)
        text = " ".join(label for label, _, _ in items)
        evidence.append(path)
        if _mizuki_is_home_text(text):
            # Cognition inspection needs the ordinary home.  Reward pages
            # remember their last selected tab, so normalise them before
            # returning instead of making every later service fail navigation.
            normal_action = (
                find_text(items, "常规行动", exact=True)
                or find_text(items, "常规行动")
            )
            if normal_action and not any(
                marker in text for marker in ("认知塑造", "认知完备")
            ):
                tap(*normal_action)
                wait(5)
                continue
            return {
                "ok": True,
                "screenshot": path,
                "steps": step,
                "evidence": evidence,
            }

        if _mizuki_is_cognition_text(text):
            tap(*POS_BACK)
            wait(3)
            continue

        # An unfinished exploration blocks the permanent reward pages.  The
        # user explicitly requires closing that exploration first.  Do so only
        # through the page-gated MAA-equivalent abandon sequence; a failure is
        # terminal for this navigation attempt and never falls through to a
        # blind Continue/Abandon click.
        if _mizuki_is_active_exploration_detail_text(text):
            abandoned = _mizuki_abandon_active_exploration_for_verification()
            if not abandoned.get("ok"):
                return {
                    "ok": False,
                    "reason": abandoned.get("reason") or "active_exploration_not_closed",
                    "evidence": evidence + abandoned.get("screenshots", []),
                    "active_exploration": abandoned,
                }
            evidence.extend(abandoned.get("screenshots", []))
            continue

        # After a run the game can remain on the data-backtracking/score pages.
        # Those are not navigation failures: advance the verified settlement
        # until the Mizuki home is visible, then service permanent rewards.
        if any(marker in text for marker in (
            "查看数据回溯", "联系中断", "通过层数", "得分！", "生态谱系达到上限",
        )):
            tap(*POS_DISMISS)
            wait(6)
            continue

        # Mizuki home differs by selected mode.  Memory Mapping and Deep
        # Exploration omit the cognition entry, so switch to Normal Action
        # before declaring the home unrecognised.
        normal_action = find_text(items, "常规行动", exact=True) or find_text(items, "常规行动")
        if normal_action and "开始探索" in text and "认知塑造" not in text:
            tap(*normal_action)
            wait(5)
            continue

        if "获得物资" in text or "首次获得" in text:
            tap(*POS_DISMISS)
            wait(3)
            continue

        terminal = find_text(items, "终端", exact=True)
        if terminal and any(marker in text for marker in ("编队", "干员", "公开招募")):
            tap(*terminal)
            wait(6)
            continue

        if "ATTENTION" in text and "集成战略" in text:
            tap(1435, 1000)
            wait(6)
            continue

        if "长期探索" in text and "集成战略" in text and "查看全部主题" in text:
            view_all = [
                (cx, cy) for label, cx, cy in items
                if "查看全部主题" in label and cx < 1100
            ]
            if view_all:
                tap(*min(view_all, key=lambda pos: pos[0]))
                wait(6)
                continue

        theme_entry = _mizuki_theme_entry_position(items)
        if theme_entry:
            tap(*theme_entry)
            wait(7)
            continue

        if "进入主题" in text and theme_swipes < 4:
            swipe(500, 850, 1600, 850, 800)
            theme_swipes += 1
            wait(5)
            continue

        # Never use a generic centre tap merely because Ecology Pedigree is
        # visible.  On the Mizuki home that coordinate is a mode tab and was
        # the root cause of bouncing between Normal and Memory Mapping.
        break
    return {"ok": False, "reason": "mizuki_home_not_reached", "evidence": evidence}


def _mizuki_memory_reward_claimed(path):
    """Classify the Memory Mapping reward badge from the real rendered UI.

    A claimed memory uses a low-saturation grey check mark.  An unfinished
    memory uses a saturated gold chest in the same fixed 1920x1080 region.
    OCR is deliberately not used for this small icon.
    """
    if not path or not os.path.exists(path):
        return False
    try:
        import numpy as np
        from PIL import Image

        with Image.open(path) as source:
            image = np.asarray(source.convert("RGB"))
        if image.shape[0] < 740 or image.shape[1] < 1510:
            return False
        badge = image[620:740, 1320:1510]
        colourfulness = (badge.max(axis=2) - badge.min(axis=2)).mean()
        return float(colourfulness) < 12.0
    except Exception:
        return False


def probe_mizuki_reward_progress(memory_total=8, deep_total=12):
    """Read permanent Mizuki reward progress from the game UI.

    This is a read-only verification pass.  A completed MAA task chain proves
    one run ended; it never proves an entire reward category is exhausted.
    """
    result = {
        "ok": False,
        "memory_mapping": {
            "completed": 0,
            "total": int(memory_total),
            "status": "ui_verification_failed",
        },
        "deep_exploration": {
            "completed": 0,
            "total": int(deep_total),
            "status": "ui_verification_failed",
        },
        "screenshots": [],
    }
    if _maa_task_queue_running():
        result["reason"] = "maa_queue_running"
        return result
    nav = navigate_to_mizuki_home()
    result["navigation"] = nav
    if not nav.get("ok"):
        result["reason"] = "mizuki_home_not_reached"
        return result

    # Memory Mapping is circular; exactly eight right moves cover every card
    # regardless of which memory the UI remembered from the previous visit.
    tap(988, 998)
    wait(4)
    memory_completed = 0
    for index in range(int(memory_total)):
        path = shot(f"mizuki_memory_progress_{index + 1}")
        result["screenshots"].append(path)
        if _mizuki_memory_reward_claimed(path):
            memory_completed += 1
        tap(680, 850)
        wait(2)
    result["memory_mapping"].update({
        "completed": memory_completed,
        "status": (
            "ui_verified_complete"
            if memory_completed >= int(memory_total)
            else "ui_verified_partial"
        ),
    })

    # Deep Exploration is also a fixed carousel.  The detail panel explicitly
    # says that its exploration reward has been claimed, which is stronger
    # evidence than the task-chain result or a cached progress file.
    tap(657, 998)
    wait(4)
    deep_completed = 0
    for index in range(int(deep_total)):
        path = shot(f"mizuki_deep_progress_{index + 1}")
        result["screenshots"].append(path)
        compact = re.sub(r"\s+", "", ocr_text(path))
        if "探索奖励已领取" in compact or (
            "探索条目" in compact and "已完成" in compact
        ):
            deep_completed += 1
        tap(1550, 380)
        wait(2)
    result["deep_exploration"].update({
        "completed": deep_completed,
        "status": (
            "ui_verified_complete"
            if deep_completed >= int(deep_total)
            else "ui_verified_partial"
        ),
    })
    result["ok"] = True
    result["reason"] = "ui_verified"

    # Leave the theme on the ordinary page, the common starting point used by
    # the existing MAA integration.
    tap(1330, 998)
    wait(3)
    return result


def _mizuki_cognition_node_candidates(path, ocr_items=None):
    """Find round cognition nodes; confirmation text remains the write gate."""
    if not path or not os.path.exists(path):
        return []
    try:
        import cv2
        import numpy as np
        # cv2.imread on Windows cannot reliably open the project's Chinese
        # path.  Decode bytes instead so a valid screenshot never becomes an
        # empty candidate list solely because of its directory name.
        with open(path, "rb") as source:
            image = cv2.imdecode(np.frombuffer(source.read(), dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return []
    if image is None:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 1.5)
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=55,
        param1=90,
        param2=27,
        minRadius=26,
        maxRadius=78,
    )
    if circles is None:
        return []

    # Every real node has a short label immediately below it.  Requiring that
    # label removes star-map rings, connecting-line intersections and the
    # large bottom detail panel which HoughCircles otherwise misclassifies.
    # The OCR labels are already available to the caller, so this adds no
    # second OCR pass during the tree scan.
    ignored_labels = {
        "主观想象", "已塑造", "认知塑造", "认知完备", "资源调配",
        "理性与判断", "开始探索", "当前节点未解锁", "已升级",
    }
    label_anchors = []
    for label, lx, ly in (ocr_items or []):
        label = re.sub(r"\s+", "", str(label or ""))
        if not label or label in ignored_labels:
            continue
        if re.fullmatch(r"\d+(?:/\d+)?", label):
            continue
        if len(label) > 14 or any(marker in label for marker in (
            "分队", "希望消耗", "指挥等级", "解锁", "物品", "当前节点",
        )):
            continue
        label_anchors.append((int(lx), int(ly), label))

    height, width = image.shape[:2]
    candidates = []
    for raw_x, raw_y, raw_radius in circles[0]:
        cx, cy, radius = int(raw_x), int(raw_y), int(raw_radius)
        if not (180 <= cx <= width - 150 and 145 <= cy <= height - 120):
            continue
        if label_anchors and not any(
            abs(cx - lx) <= max(85, int(radius * 1.5))
            and 28 <= ly - cy <= 145
            for lx, ly, _ in label_anchors
        ):
            continue
        x1, x2 = max(0, cx - radius), min(width, cx + radius + 1)
        y1, y2 = max(0, cy - radius), min(height, cy + radius + 1)
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        value = hsv[:, :, 2]
        saturation = hsv[:, :, 1]
        bright = int(((value >= 165) & (saturation <= 95)).sum())
        cyan = int(
            ((hsv[:, :, 0] >= 75) & (hsv[:, :, 0] <= 115)
             & (saturation >= 65) & (value >= 115)).sum()
        )
        if bright < 140 and cyan < 45:
            continue
        candidates.append((cx, cy, bright + cyan * 3))

    deduped = []
    for cx, cy, score in sorted(candidates, key=lambda item: item[2], reverse=True):
        if any(abs(cx - ox) < 45 and abs(cy - oy) < 45 for ox, oy, _ in deduped):
            continue
        deduped.append((cx, cy, score))
    return [(cx, cy) for cx, cy, _ in sorted(deduped, key=lambda item: (item[1], item[0]))]


def _mizuki_cognition_upgrade_cost(items):
    for text, _, _ in items or []:
        label = str(text or "")
        match = re.search(r"(?:消耗|需要|-)\s*(\d{1,3})", label)
        if match:
            return int(match.group(1))
    return None


def _mizuki_open_cognition_tree_view(
    row, column, max_rows=6, max_columns=8, tag="scan"
):
    """Open a deterministic two-dimensional cognition-tree viewport.

    The Mizuki tree is both wider and taller than one screen.  The old scan
    only dragged horizontally and therefore never reached the user's final
    five nodes at the bottom.  Every candidate now starts from the ordinary
    home, resets to the top-left edge, then moves to one explicit row/column;
    this also closes any detail panel left by the previous candidate.
    """
    nav = navigate_to_mizuki_home()
    if not nav.get("ok"):
        return {"ok": False, "reason": "mizuki_home_not_reached", "navigation": nav}
    home = shot(f"mizuki_cognition_grid_home_{tag}")
    home_items = ocr(home)
    entry = (
        find_text(home_items, "认知塑造", exact=True)
        or find_text(home_items, "认知塑造")
    )
    if not entry:
        return {"ok": False, "reason": "cognition_entry_not_found", "screenshot": home}
    tap(*entry)
    wait(4)

    # Content follows the finger.  Drag right/down repeatedly to clamp the
    # viewport to the top-left edge, then drag left/up to the requested cell.
    for _ in range(int(max_columns)):
        swipe(500, 520, 1600, 520, 650)
        wait(0.4)
    for _ in range(int(max_rows)):
        swipe(960, 260, 960, 820, 650)
        wait(0.4)
    for _ in range(int(row)):
        swipe(960, 820, 960, 260, 650)
        wait(0.8)
    for _ in range(int(column)):
        swipe(1600, 520, 500, 520, 650)
        wait(0.8)

    page = shot(f"mizuki_cognition_grid_{tag}_r{row}_c{column}")
    items = ocr(page)
    text = " ".join(label for label, _, _ in items)
    if not _mizuki_is_cognition_text(text):
        return {
            "ok": False,
            "reason": "cognition_page_not_confirmed",
            "screenshot": page,
            "navigation": nav,
        }
    return {
        "ok": True,
        "screenshot": page,
        "items": items,
        "navigation": nav,
    }


def _mizuki_cognition_label_anchors(items):
    """Map node-caption OCR to the circular icon immediately above it.

    Mizuki cognition nodes consistently render as a circular icon with a
    boxed caption underneath.  The caption is the stable semantic anchor;
    circle-only detection also catches decorations and already-open detail
    controls.  Captions whose icon would be outside the viewport or behind
    the bottom detail drawer are deferred to an adjacent viewport.
    """
    excluded = {
        "主观想象",
        "认知塑造",
        "已塑造",
        "确认升级",
        "已升级",
        "当前节点未解锁",
        "导览信息端口",
        "深蓝记录仪",
        "开始探索",
        "常规行动",
        "深入探索",
        "追忆映射",
    }
    anchors = []
    for label, x, y in items or []:
        text = re.sub(r"\s+", "", str(label or ""))
        if not text or text in excluded:
            continue
        if any(marker in text for marker in (
            "已塑造", "确认升级", "当前节点未解锁", "战斗获取",
        )):
            continue
        if re.fullmatch(r"[-+]?\d+(?:/\d+)?", text):
            continue
        if any(marker in text for marker in ("获取", "概率", "经验+", "%")):
            continue
        x, y = int(x), int(y)
        icon_y = y - 92
        if not (110 <= x <= 1870 and 80 <= icon_y <= 780 and 170 <= y <= 870):
            continue
        if any(abs(x - old["icon"][0]) < 45 and abs(icon_y - old["icon"][1]) < 45 for old in anchors):
            continue
        anchors.append({"label": text, "icon": (x, icon_y), "caption": (x, y)})
    # The unfinished frontier is at the bottom; inspect lower captions first.
    return sorted(anchors, key=lambda item: (-item["caption"][1], item["caption"][0]))


def apply_mizuki_cognition_points(
    max_upgrades=24, max_sections=8, max_rows=6, bottom_rows=2
):
    """Spend currently available Mizuki cognition points at a safe boundary.

    OCR first anchors each boxed node caption, then clicks the corresponding
    circular ability icon immediately above it.  That spatial match is still
    not sufficient authority to buy: the bottom-right detail panel must expose
    an explicit upgrade/confirm button.  After buying, the code returns home
    and proves the point counter fell before updating its result.
    """
    result = {"ok": False, "upgrades": [], "scans": [], "screenshots": []}
    for upgrade_index in range(max_upgrades + 1):
        current = shot(f"mizuki_cognition_boundary_{upgrade_index}")
        current_items = ocr(current)
        current_text = " ".join(label for label, _, _ in current_items)
        if _mizuki_is_cognition_text(current_text):
            # A previous failed service may already have left the tree open.
            # Return to home so the point counter before/after follows one
            # stable measurement path.
            tap(*POS_BACK)
            wait(3)
            nav = navigate_to_mizuki_home()
        else:
            nav = navigate_to_mizuki_home()
        result["navigation"] = nav
        if not nav.get("ok"):
            result["reason"] = "mizuki_home_not_reached"
            return result

        home = shot(f"mizuki_cognition_home_{upgrade_index}")
        home_items = ocr(home)
        home_text = " ".join(label for label, _, _ in home_items)
        result["screenshots"].append(home)
        points_before = _mizuki_cognition_points(home_items)
        result["points_before"] = points_before
        if "认知完备" in home_text or points_before == 0:
            result.update({
                "ok": True,
                "reason": "cognition_complete_or_no_points",
                "points_remaining": 0,
            })
            return result

        purchased = False
        page_items = []
        # The user has directly located the remaining nodes at the bottom.
        # Inspect the lowest two viewport rows first instead of re-reading the
        # already-complete upper tree for hours.
        rows_to_scan = list(reversed(range(int(max_rows))))[
            : max(1, min(int(bottom_rows), int(max_rows)))
        ]
        for row in rows_to_scan:
            if purchased:
                break
            for section in range(int(max_sections)):
                view = _mizuki_open_cognition_tree_view(
                    row,
                    section,
                    max_rows=max_rows,
                    max_columns=max_sections,
                    tag=f"u{upgrade_index}_s{section}",
                )
                result["navigation"] = view.get("navigation", result.get("navigation"))
                page = view.get("screenshot")
                if page:
                    result["screenshots"].append(page)
                if not view.get("ok"):
                    result["reason"] = view.get("reason") or "cognition_page_not_confirmed"
                    navigate_to_mizuki_home()
                    return result
                page_items = view["items"]
                nodes = _mizuki_cognition_label_anchors(page_items)
                result["scans"].append({
                    "upgrade": upgrade_index,
                    "row": row,
                    "section": section,
                    "points": points_before,
                    "nodes": nodes,
                })
                for node in nodes:
                    # Selecting another caption-anchored icon replaces the
                    # existing detail drawer; the tree itself does not move.
                    tap(*node["icon"])
                    wait(2)
                    detail = shot(
                        f"mizuki_cognition_candidate_u{upgrade_index}_r{row}_s{section}"
                    )
                    detail_items = ocr(detail)
                    detail_text = re.sub(
                        r"\s+", "", " ".join(label for label, _, _ in detail_items)
                    )
                    result["screenshots"].append(detail)
                    confirm = (
                        find_text(detail_items, "确认升级", exact=True)
                        or find_text(detail_items, "确认升级")
                        or find_text(detail_items, "点亮", exact=True)
                        or find_text(detail_items, "点亮")
                    )
                    cost = _mizuki_cognition_upgrade_cost(detail_items)
                    if "当前节点未解锁" in detail_text or "已升级" in detail_text:
                        continue
                    if not confirm:
                        continue
                    if points_before is not None and cost is not None and points_before < cost:
                        continue
                    tap(*confirm)
                    wait(4)
                    nav_after = navigate_to_mizuki_home()
                    if not nav_after.get("ok"):
                        result["reason"] = "home_not_reached_after_upgrade"
                        return result
                    after = shot(f"mizuki_cognition_purchased_{upgrade_index}")
                    after_items = ocr(after)
                    points_after = _mizuki_cognition_points(after_items)
                    result["screenshots"].append(after)
                    verified = (
                        points_before is not None
                        and points_after is not None
                        and points_after < points_before
                    )
                    result["upgrades"].append({
                        "row": row,
                        "section": section,
                        "node": node["icon"],
                        "label": node["label"],
                        "cost": cost,
                        "points_before": points_before,
                        "points_after": points_after,
                        "verified": verified,
                    })
                    if not verified:
                        result["reason"] = "cognition_upgrade_not_verified"
                        return result
                    purchased = True
                    break
                if purchased:
                    break

        if not purchased:
            navigate_to_mizuki_home()
            progress = _mizuki_cognition_progress(page_items)
            if progress and progress[0] < progress[1]:
                # A point balance does not prove that a node is currently
                # purchasable.  Treat the user-identified bottom frontier with
                # no explicit upgrade confirmation as locked/not currently
                # purchasable, not as a technical failure; never blind-click.
                result.update({
                    "ok": True,
                    "reason": "bottom_nodes_no_available_upgrade",
                    "points_remaining": points_before,
                    "progress": {"current": progress[0], "total": progress[1]},
                })
                return result
            result.update({
                "ok": points_before in (None, 0),
                "reason": "no_verified_upgrade_candidate",
                "points_remaining": points_before,
            })
            return result

    result["reason"] = "cognition_upgrade_budget_exhausted"
    return result


def service_mizuki_progress():
    """Service Mizuki permanent growth after a settled exploration."""
    cognition = apply_mizuki_cognition_points()
    return {
        "ok": bool(cognition.get("ok")),
        "cognition": cognition,
        "serviced_at": datetime.now().isoformat(timespec="seconds"),
    }


def _jiegarden_ui_probe(path):
    """Read the JieGarden home screen and fingerprint its difficulty badge.

    The badge is intentionally treated as an image, not OCR text: the small white
    digit is below the reliable OCR size on a 1920x1080 emulator screenshot.
    """
    result = {
        "screenshot": path,
        "is_jiegarden_home": False,
        "badge_fingerprint": "",
        "badge_ink_pixels": 0,
    }
    if not path or not os.path.exists(path):
        return result
    text = ocr_text(path)
    result["is_jiegarden_home"] = bool(
        "界园志异" in text and ("请君入园" in text or "探索" in text)
    )
    if not result["is_jiegarden_home"]:
        return result

    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        width, height = image.size
        # 0715实机：右侧“请君入园”左边的紫色难度徽记；只截数字内部，
        # 避开六边形白边与右侧按钮文字，并按固定大小归一化。
        badge = image.crop((
            int(width * 0.833), int(height * 0.660),
            int(width * 0.852), int(height * 0.710),
        )).resize((36, 54), Image.Resampling.NEAREST)
        mask = bytes(
            1 if max(pixel) >= 180 and max(pixel) - min(pixel) < 100 else 0
            for pixel in badge.getdata()
        )
    result["_badge_mask"] = mask
    result["badge_fingerprint"] = hashlib.sha256(mask).hexdigest()
    result["badge_ink_pixels"] = int(sum(mask))
    return result


def _public_jiegarden_probe(probe):
    """Drop the binary comparison payload before persisting run evidence."""
    return {key: value for key, value in (probe or {}).items() if not key.startswith("_")}


def _jiegarden_visual_progress(before, after, mismatch_threshold=0.02):
    """Confirm one difficulty unlock only when the game-home badge changed."""
    if not before or not before.get("is_jiegarden_home"):
        return {"confirmed": False, "reason": "before_not_jiegarden_home"}
    if not after or not after.get("is_jiegarden_home"):
        return {"confirmed": False, "reason": "after_not_jiegarden_home"}
    old_mask = before.get("_badge_mask") or b""
    new_mask = after.get("_badge_mask") or b""
    if not old_mask or len(old_mask) != len(new_mask):
        return {"confirmed": False, "reason": "badge_mask_unavailable"}
    mismatch = sum(a != b for a, b in zip(old_mask, new_mask)) / len(old_mask)
    return {
        "confirmed": bool(mismatch >= float(mismatch_threshold)),
        "reason": "badge_changed" if mismatch >= float(mismatch_threshold) else "badge_unchanged",
        "mismatch_ratio": round(mismatch, 6),
    }


def mode_roguelike(
    theme="garden",
    difficulty=2147483647,
    starts_count=1,
    max_tutorial_recoveries=2,
    core_char="维什戴尔",
    squad="远程战术分队",
    roles="稳扎稳打",
    mode="Exp",
    use_foldartal=None,
    run_timeout=3600,
):
    """执行有次数边界的肉鸽；模拟器首次教学页仅允许有限恢复。"""
    canonical = _resolve_roguelike_theme(theme)
    if use_foldartal is not None and canonical != "Sami":
        raise ValueError("use_foldartal仅适用于Sami主题")
    direct_core = use_foldartal is not None
    mode_value = ROGUELIKE_MODES.get(str(mode or "Exp").strip().lower())
    reward_mode = mode_value in {"Squad", "Exploration"}
    log("=" * 60)
    difficulty_label = (
        "当前最高已解锁（完整通关后下一局自动升一级）"
        if int(difficulty) == 2147483647 else str(difficulty)
    )
    log(
        f"  场景: 肉鸽 ({ROGUELIKE_THEME_NAMES[canonical]})，难度={difficulty_label}"
    )
    log("=" * 60)
    max_tutorial_recoveries = max(0, int(max_tutorial_recoveries))
    run_timeout = max(30, int(run_timeout))
    _RUN_SUMMARY["roguelike"] = {
        "theme": canonical,
        "theme_name": ROGUELIKE_THEME_NAMES[canonical],
        "difficulty_target": int(difficulty),
        "difficulty_policy": "highest_unlocked" if int(difficulty) == 2147483647 else "fixed",
        "starts_count": int(starts_count),
        "core_char": str(core_char or ""),
        "squad": str(squad or ""),
        "roles": str(roles or ""),
        "mode": str(mode or "Exp"),
        "use_foldartal": use_foldartal,
        "execution_backend": "MaaCore" if direct_core else "MAA_WPF",
        "run_timeout": run_timeout,
        "tutorial_recoveries": [],
        "interruption_recoveries": [],
        "status": "preparing",
    }

    visual_before = None
    if canonical == "JieGarden":
        before_path = shot("roguelike_visual_before")
        visual_before = _jiegarden_ui_probe(before_path)
        _RUN_SUMMARY["roguelike"]["visual_before"] = _public_jiegarden_probe(visual_before)

    try:
        with temporary_maa_config(
            lambda cfg: _configure_roguelike(
                cfg, canonical, difficulty=difficulty, starts_count=starts_count,
                core_char=core_char,
                squad=squad, roles=roles, mode=mode,
            ),
            f"仅Roguelike，主题={canonical}，难度={difficulty}，次数={starts_count}",
        ):
            # MAA 启动后只使用内存中的完整任务参数。即使 Roguelike 仍是唯一
            # 启用任务，CoreChar/Squad/Difficulty 等磁盘字段变更也不会热加载；
            # 因此每个受监督单局都从空闲进程边界重载，不能只比较 IsEnable。
            if _maa_process_exists() is True and not direct_core:
                if _maa_task_queue_running():
                    _RUN_SUMMARY["roguelike"]["status"] = "maa_already_running"
                    log("❌ MAA仍有任务运行，拒绝覆盖肉鸽参数", "ERROR")
                    return False
                reload_maa_after_config_switch(
                    f"Roguelike完整参数重载: {canonical}/{difficulty}/{squad}/{roles}/{core_char}"
                )
            for attempt in range(max_tutorial_recoveries + 1):
                if direct_core:
                    core_params = _roguelike_core_params(
                        canonical,
                        difficulty=difficulty,
                        starts_count=starts_count,
                        core_char=core_char,
                        squad=squad,
                        roles=roles,
                        mode=mode,
                        use_foldartal=use_foldartal,
                    )
                    _RUN_SUMMARY["roguelike"]["core_params"] = dict(core_params)
                    core_result = _run_maa_core_roguelike_once(
                        core_params, timeout=run_timeout
                    )
                    _RUN_SUMMARY["roguelike"]["core_result"] = dict(core_result)
                    result = bool(core_result.get("ok"))
                else:
                    if not run_maa_daily_tasks(enabled_tasks={"Roguelike"}):
                        log("❌ MAA肉鸽任务启动失败", "ERROR")
                        _RUN_SUMMARY["roguelike"]["status"] = "start_failed"
                        return False
                    result = wait_maa_complete(
                        timeout=run_timeout, prestarted_boundary=True
                    )
                if result is True:
                    after_path = shot("roguelike_visual_after")
                    visual_after = _jiegarden_ui_probe(after_path) if canonical == "JieGarden" else None
                    if visual_after is not None:
                        _RUN_SUMMARY["roguelike"]["visual_after"] = _public_jiegarden_probe(visual_after)
                        visual_progress = _jiegarden_visual_progress(visual_before, visual_after)
                        _RUN_SUMMARY["roguelike"]["visual_progress"] = visual_progress

                    settlement_details = _roguelike_settlement_details(_LAST_MAA_RUN_LOG)
                    settlements = [item["game_pass"] for item in settlement_details]
                    _RUN_SUMMARY["roguelike"]["settlements"] = settlements
                    _RUN_SUMMARY["roguelike"]["settlement_details"] = settlement_details

                    # Monthly Squad / Memory Mapping and Deep Exploration are
                    # reward-service modes.  Their MAA chains may complete on
                    # the mode home after auto-iteration and therefore have no
                    # ordinary exploration settlement payload.  The verified
                    # TaskChainCompleted boundary is sufficient to finish this
                    # bounded service call; callers still record it separately
                    # from an ordinary ending/difficulty clear.
                    if reward_mode:
                        _RUN_SUMMARY["roguelike"].update({
                            "status": "reward_mode_completed",
                            "reward_mode": mode_value,
                            "game_pass": False,
                            "reward_service_boundary": "maa_taskchain_completed",
                            "last_settlement": (
                                settlement_details[-1] if settlement_details else None
                            ),
                        })
                        break

                    # 实际难度属于每次结算事实，失败探索也必须记录。旧逻辑只在
                    # game_pass=true 时写入，导致“最高已解锁”运行长期无法回答
                    # 到底在打哪一级，并让不同难度的暴毙样本混在一起。
                    if settlement_details:
                        actual_difficulty = settlement_details[-1].get("difficulty")
                        if actual_difficulty is not None:
                            try:
                                _RUN_SUMMARY["roguelike"]["actual_difficulty"] = int(
                                    actual_difficulty
                                )
                            except (TypeError, ValueError):
                                _RUN_SUMMARY["roguelike"][
                                    "actual_difficulty_raw"
                                ] = actual_difficulty

                    # 所有肉鸽主题共用同一证据规则，但每个主题写独立账本。
                    # 账本失败不能反向中断真实游戏流程；它只在结算安全边界
                    # 记录成功/失败和部署证据，供后续独立探索生成最小关内优化。
                    try:
                        import roguelike_collapse_tracking

                        collapse_update = roguelike_collapse_tracking.update_collapse_tracking(
                            _LAST_MAA_RUN_LOG,
                            theme=canonical,
                            run_context={
                                "difficulty_target": int(difficulty),
                                "difficulty_policy": (
                                    "highest_unlocked"
                                    if int(difficulty) == 2147483647
                                    else "fixed"
                                ),
                                "actual_difficulty": _RUN_SUMMARY["roguelike"].get(
                                    "actual_difficulty"
                                ),
                                "core_char": str(core_char or ""),
                                "squad": str(squad or ""),
                                "roles": str(roles or ""),
                                "mode": str(mode or "Exp"),
                            },
                        )
                        collapse_summary = collapse_update.get("summary") or {}
                        _RUN_SUMMARY["roguelike"]["collapse_tracking"] = {
                            "ledger": collapse_update.get("ledger_path"),
                            "new_outcome_count": len(
                                collapse_update.get("new_outcomes") or []
                            ),
                            "optimization_candidate_count": collapse_summary.get(
                                "optimization_candidate_count", 0
                            ),
                            "optimization_candidates": collapse_summary.get(
                                "optimization_candidates", []
                            ),
                        }
                    except Exception as collapse_error:
                        _RUN_SUMMARY["roguelike"]["collapse_tracking_warning"] = (
                            f"{type(collapse_error).__name__}: {collapse_error}"
                        )
                        log(
                            "⚠️ 肉鸽暴毙账本未写入；不影响本次真实探索: "
                            f"{collapse_error}",
                            "WARN",
                        )

                    # 用户0715纠正：是否通关只看游戏界面。MaaCore结算字段只保留
                    # 为诊断证据，不能让脚本在徽记仍为7时宣称已通关。
                    if canonical == "JieGarden":
                        if not visual_progress.get("confirmed"):
                            _RUN_SUMMARY["roguelike"]["status"] = "visual_progress_unconfirmed"
                            log(
                                "❌ MAA队列已结束，但游戏首页难度徽记没有确认升级: "
                                f"{visual_progress.get('reason')}",
                                "ERROR",
                            )
                            return False
                        _RUN_SUMMARY["roguelike"]["status"] = "visual_game_pass_confirmed"
                        _RUN_SUMMARY["roguelike"]["game_pass"] = True
                        _RUN_SUMMARY["roguelike"]["visual_difficulty_advanced"] = True
                        break

                    if not settlement_details:
                        _RUN_SUMMARY["roguelike"]["status"] = "settlement_unconfirmed"
                        log("❌ MAA队列结束，但没有肉鸽结算证据", "ERROR")
                        return False
                    if not settlements[-1]:
                        _RUN_SUMMARY["roguelike"]["status"] = "exploration_failed"
                        log("❌ 本次探索已结算，但 game_pass=false，不能算作通关", "ERROR")
                        return False
                    _RUN_SUMMARY["roguelike"]["status"] = "game_pass_confirmed"
                    _RUN_SUMMARY["roguelike"]["game_pass"] = True
                    break

                # 超时或日志终态不完整时，必须先让真实队列变为空闲；绝不能
                # 直接杀 MAA 或在旧任务仍运行时再次点击 Link Start。
                if _maa_task_queue_running():
                    stopped = _stop_maa_task_queue(timeout=30)
                    _RUN_SUMMARY["roguelike"]["timeout_stop_confirmed"] = bool(stopped)
                    if not stopped:
                        _RUN_SUMMARY["roguelike"]["status"] = "stop_failed"
                        log("❌ 肉鸽超时后未能确认MAA停止", "ERROR")
                        return False

                if attempt >= max_tutorial_recoveries:
                    _RUN_SUMMARY["roguelike"]["status"] = "recovery_limit"
                    log(f"❌ 肉鸽任务失败且已达到教学页恢复上限: {result}", "ERROR")
                    return False
                recovery = _close_roguelike_interruption_once()
                if not recovery:
                    _RUN_SUMMARY["roguelike"]["status"] = "unrecognised_error"
                    log(f"❌ 肉鸽错误画面不是已验证剧情/教学页: {result}", "ERROR")
                    return False
                _RUN_SUMMARY["roguelike"]["interruption_recoveries"].append(recovery)
                if recovery.get("kind") == "tutorial":
                    _RUN_SUMMARY["roguelike"]["tutorial_recoveries"].append(recovery)
            else:
                return False
    except Exception as e:
        log(f"❌ 配置或执行肉鸽失败: {e}", "ERROR")
        _RUN_SUMMARY["roguelike"]["status"] = "exception"
        _RUN_SUMMARY["roguelike"]["error"] = str(e)
        return False

    log("✅ 肉鸽完成")
    return True


def _next_daily_deadline(value, now=None):
    """把HH:MM解析为下一次本地截止时间；非法值直接拒绝。"""
    if not value:
        return None
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value))
    if not match:
        raise ValueError("截止时间必须为HH:MM")
    hour, minute = map(int, match.groups())
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("截止时间超出有效范围")
    now = now or datetime.now()
    deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if deadline <= now:
        deadline += timedelta(days=1)
    return deadline


def mode_reclamation(target_cycles=440, stop_at=None):
    """沙洲遗闻无存档刷繁荣点；达到轮数或每日截止时间后主动停止MAA。"""
    global _LAST_MAA_RUN_LOG
    _LAST_MAA_RUN_LOG = ""
    target_cycles = max(1, int(target_cycles or 440))
    stop_deadline = _next_daily_deadline(stop_at) if stop_at else None
    log("=" * 60)
    log("  场景: 生息演算 - 沙洲遗闻（无存档刷点）")
    log("=" * 60)
    _RUN_SUMMARY["reclamation"] = {
        "theme": "Tales",
        "mode": "ProsperityNoSave",
        "clear_store": False,
        "target_cycles": target_cycles,
        "stop_at": stop_at,
        "stop_deadline": stop_deadline.isoformat(timespec="seconds") if stop_deadline else None,
        "status": "preparing",
    }

    probe = shot("reclamation_resume_probe")
    probe_text = ocr_text(probe)
    owned_existing = _reclamation_resume_allowed(probe_text)
    if owned_existing:
        _RUN_SUMMARY["reclamation"]["owned_existing_save"] = True
        log("→ 检测到本轮Tales临时档；先按双确认图形闭环安全删除，再重新开始")
        if not _reset_owned_reclamation_temporary_save():
            _RUN_SUMMARY["reclamation"]["status"] = "owned_save_reset_failed"
            _RUN_SUMMARY["flow_control"] = {
                "status": "paused",
                "reason": "本轮自动化临时档删除未完成；拒绝让ProsperityNoSave走PNS-Resume假完成",
            }
            return False
        _RUN_SUMMARY["reclamation"]["owned_save_reset"] = True
        _set_reclamation_ownership("clean", reason="pre_start_reset")
    if not goto_reclamation_tales_main():
        # Starting from the Ark home page means the initial ownership probe
        # cannot see a Tales save.  Navigation may reveal a recent temporary
        # save, so verify ownership here once more before failing closed.
        post_navigation = shot("reclamation_post_navigation_probe")
        if _reclamation_resume_allowed(ocr_text(post_navigation)):
            _RUN_SUMMARY["reclamation"]["owned_existing_save"] = True
            log("→ 导航后发现本轮Tales临时档；已由近期Reclamation日志证明归属，安全删除后重进")
            if not _reset_owned_reclamation_temporary_save():
                _RUN_SUMMARY["reclamation"]["status"] = "owned_save_reset_failed"
                _RUN_SUMMARY["flow_control"] = {
                    "status": "paused",
                    "reason": "导航后发现的本轮自动化临时档删除未完成",
                }
                return False
            _RUN_SUMMARY["reclamation"]["owned_save_reset"] = True
            _set_reclamation_ownership("clean", reason="post_navigation_reset")
            navigation_ok = goto_reclamation_tales_main()
        else:
            navigation_ok = False
        if not navigation_ok:
            _RUN_SUMMARY["reclamation"]["status"] = "navigation_failed"
            _RUN_SUMMARY["flow_control"] = {
                "status": "paused",
                "reason": "生息演算未确认处于沙洲遗闻无存档‘开始演算’页面",
            }
            return False

    combined_run_log = ""
    completed_before_restart = 0
    daily_reset_recoveries = 0
    try:
        with temporary_maa_config(
            lambda cfg: _configure_reclamation_tales(cfg, clear_store=False),
            f"仅Reclamation，Tales无存档刷点，预算{target_cycles}轮",
        ):
            while True:
                if not run_maa_daily_tasks(enabled_tasks={"Reclamation"}):
                    result = "maa_start_failed"
                    break
                _set_reclamation_ownership(
                    "active",
                    reason=(
                        "daily_reset_restart"
                        if daily_reset_recoveries
                        else "reclamation_taskchain_started"
                    ),
                    target_cycles=target_cycles,
                    stop_at=stop_at,
                )
                remaining_cycles = max(1, target_cycles - completed_before_restart)
                result = _wait_reclamation_cycle_budget(
                    target_cycles=remaining_cycles,
                    timeout=max(900, remaining_cycles * 240),
                    stop_deadline=stop_deadline,
                )
                segment_log = _LAST_MAA_RUN_LOG or _get_current_maa_run_log()
                combined_run_log += ("\n" if combined_run_log else "") + segment_log
                completed_total = _count_reclamation_completed_cycles(combined_run_log)
                _RUN_SUMMARY["reclamation"]["completed_before_restart"] = completed_total

                if result != "daily_reset_sync":
                    break
                if daily_reset_recoveries >= 1:
                    result = "daily_reset_recovery_limit"
                    break
                if not _recover_reclamation_after_daily_reset(segment_log):
                    result = "daily_reset_recovery_failed"
                    break
                daily_reset_recoveries += 1
                completed_before_restart = completed_total
                _RUN_SUMMARY["reclamation"]["daily_reset_recoveries"] = daily_reset_recoveries
                log(
                    f"→ 04:00刷新恢复后续跑：已完成{completed_before_restart}轮，"
                    f"剩余{max(0, target_cycles - completed_before_restart)}轮"
                )
    except Exception as e:
        log(f"❌ 生息演算配置或执行异常: {e}", "ERROR")
        result = f"exception:{e}"

    if result not in ("budget_reached", "deadline_reached", "prosperity_cap_reached"):
        _RUN_SUMMARY["reclamation"]["status"] = "failed"
        _RUN_SUMMARY["reclamation"]["detail"] = str(result)
        _RUN_SUMMARY["preserve_environment"] = True
        _RUN_SUMMARY["flow_control"] = {
            "status": "paused",
            "reason": f"生息演算刷点预算未闭环: {result}",
        }
        log(f"❌ 生息演算未确认完成，保留游戏/MAA/MuMu现场: {result}", "ERROR")
        return False

    run_log = combined_run_log or _get_current_maa_run_log()
    _LAST_MAA_RUN_LOG = run_log
    required_cycles = target_cycles if result == "budget_reached" else 1
    if result == "prosperity_cap_reached":
        completion_ok, completion_detail = _reclamation_completion_evidence(run_log)
    else:
        completion_ok, completion_detail = _reclamation_budget_evidence(run_log, required_cycles)
    if not completion_ok:
        _RUN_SUMMARY["reclamation"]["status"] = "unconfirmed"
        _RUN_SUMMARY["reclamation"]["completion_detail"] = completion_detail
        _RUN_SUMMARY["preserve_environment"] = True
        _RUN_SUMMARY["flow_control"] = {
            "status": "paused",
            "reason": f"MAA已停止但缺少预算轮数/删档闭环: {completion_detail}",
        }
        return False

    # Stop may land on a clean start page directly. If a just-created save remains,
    # only delete it when the current Reclamation log proves ownership.
    if not goto_reclamation_tales_main():
        probe = shot("reclamation_budget_stop_probe")
        # ``run_log`` is already bounded to the Reclamation chain started by
        # this process.  A long run may legitimately exceed the six-hour
        # pre-start takeover window, so its own deadline cleanup must not be
        # rejected merely because the chain is old.
        if _reclamation_resume_allowed(
                ocr_text(probe), run_log, max_age=None
        ) and \
                _reset_owned_reclamation_temporary_save():
            clean = goto_reclamation_tales_main()
        else:
            clean = False
    else:
        clean = True
    if not clean:
        _RUN_SUMMARY["reclamation"]["status"] = "stop_cleanup_failed"
        _RUN_SUMMARY["preserve_environment"] = True
        _RUN_SUMMARY["flow_control"] = {
            "status": "paused",
            "reason": "MAA预算停止后未确认回到沙洲遗闻‘开始演算’无存档页",
        }
        return False

    _set_reclamation_ownership("clean", reason=str(result))

    p = shot("reclamation_completed")
    completion_status = {
        "budget_reached": "completed",
        "deadline_reached": "completed_at_deadline",
        "prosperity_cap_reached": "completed_at_prosperity_cap",
    }[result]
    _RUN_SUMMARY["reclamation"].update({
        "status": completion_status,
        "stop_reason": result,
        "completed_cycles": _count_reclamation_completed_cycles(run_log),
        "completion_ocr": ocr_text(p)[:300],
        "screenshot": p,
    })
    if result == "deadline_reached":
        log(
            f"✅ 沙洲遗闻已在截止时间{stop_at}停止: "
            f"{_count_reclamation_completed_cycles(run_log)}轮，MAA已停止且无临时存档"
        )
    elif result == "prosperity_cap_reached":
        log(
            f"✅ 沙洲遗闻已达到繁荣度上限并由MAA完成删档/商店闭环: "
            f"本段{_count_reclamation_completed_cycles(run_log)}轮；停止剩余无效预算"
        )
    else:
        log(f"✅ 沙洲遗闻刷点预算已完成: {target_cycles}轮，MAA已主动停止且无临时存档")
    return True


def _count_reclamation_completed_cycles(run_log):
    """Count real no-save cycles by the exact second-delete task callback.

    The callback immediately after deletion has ``task=ProsperityNoSave`` and
    keeps the delete marker only in ``pre_task``.  A line-level substring check
    counts both callbacks and halves the requested farming budget.
    """
    completed_task = re.compile(
        r'"task"\s*:\s*"PNS-ProsperityBelowLimit-SwipeSaveConfirm2"'
    )
    return sum(
        1 for line in (run_log or "").splitlines()
        if "SubTaskCompleted" in line
        and completed_task.search(line)
    )


def _reclamation_executed_resume(run_log):
    """Only an actual MAA callback proves that PNS-Resume was executed.

    MAA writes PNS-Resume into every ``to_be_recognized`` candidate list even
    when it actually recognizes and executes PNS-Commence. A plain substring
    check therefore stops a valid new run immediately.
    """
    return bool(re.search(
        r"append_callback\s*\|\s*SubTask(?:Start|Completed)[^\r\n]*"
        r'"task"\s*:\s*"PNS-Resume"',
        run_log or "",
        re.I,
    ))


def _reclamation_unexpected_stop_reason(run_log, process_exists, queue_running):
    """Classify a confirmed MAA disappearance/idle state before the budget."""
    run_log = run_log or ""
    if process_exists is False:
        return "maa_process_disappeared"
    if process_exists is True and queue_running is False:
        if re.search(r'TaskChainStopped[^\r\n]*"taskchain"\s*:\s*"Reclamation"', run_log):
            return "maa_stopped_before_budget"
        if re.search(r'TaskChainCompleted[^\r\n]*"taskchain"\s*:\s*"Reclamation"', run_log):
            return "maa_completed_before_budget"
        return "maa_queue_idle_before_budget"
    return None


def _stop_maa_task_queue(timeout=20):
    """Invoke MAA's Stop button through UIA and require its queue to become idle."""
    try:
        import uiautomation as ua
        maa = _find_real_maa_window(ua)
        if not maa:
            return False
        candidates = []

        def collect(root, depth=0):
            if depth > 12:
                return
            for control in root.GetChildren():
                if control.ControlTypeName == "ButtonControl":
                    name = str(control.Name or "")
                    if "Stop" in name or "停止" in name:
                        try:
                            rect = control.BoundingRectangle
                            if not (rect.left == rect.top == rect.right == rect.bottom == 0):
                                candidates.append((depth, control, name))
                        except Exception:
                            pass
                collect(control, depth + 1)

        collect(maa)
        if not candidates:
            log("❌ MAA运行中但未找到停止按钮", "ERROR")
            return False
        _, button, name = min(candidates, key=lambda item: item[0])
        button.GetInvokePattern().Invoke()
        log(f"→ 已后台调用MAA停止按钮: {name}")
    except Exception as e:
        log(f"❌ 后台调用MAA停止按钮失败: {e}", "ERROR")
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        wait(0.5)
        if not _maa_task_queue_running():
            return True
    return False


def _recover_reclamation_start_today_stall(run_log):
    """Recover the verified Tales tutorial screen where MAA loops on CalcOrNextDay."""
    tail = (run_log or "").splitlines()[-240:]
    repeats = sum(
        1 for line in tail
        if "SubTaskCompleted" in line and "PNS-SkipToCalc-CalcOrNextDay" in line
    )
    if repeats < 30:
        return False
    p = shot("reclamation_start_today_stall")
    items = ocr(p)
    text = " ".join(label for label, _, _ in items)
    if "决断点已补充" not in text or "开启今日" not in text:
        return False
    pos = find_text(items, "开启今日", exact=True)
    if not pos:
        return False
    tap(*pos)
    log("→ 生息演算恢复: 已验证‘决断点已补充’，点击‘开启今日’")
    wait(3)
    return True


def _reclamation_daily_reset_window(now=None):
    """Only treat the narrow 04:00 server-reset boundary as recoverable."""
    now = now or datetime.now()
    minute_of_day = now.hour * 60 + now.minute
    return (3 * 60 + 59) <= minute_of_day <= (4 * 60 + 10)


def _reclamation_daily_reset_interruption(run_log, screen_text, now=None):
    """Require clock, Core state and the exact game sync dialog together.

    A generic Reclamation TaskChainError must never trigger navigation or a
    restart.  The two live failures on 07/21 and 07/22 both occurred while a
    newly commenced cycle was in PNS-OpeningAnimation and the game displayed
    ``数据已更新，即将进行同步`` at the 04:00 daily reset.
    """
    run_log = run_log or ""
    screen_text = re.sub(r"\s+", "", screen_text or "")
    task_error = re.search(
        r'TaskChainError[^\r\n]*"taskchain"\s*:\s*"Reclamation"',
        run_log,
    ) is not None
    opening_interrupted = (
        "PNS-OpeningAnimation" in run_log
        and "PNS-Commence" in run_log
    )
    exact_sync_dialog = "数据已更新" in screen_text and "即将进行同步" in screen_text
    return bool(
        _reclamation_daily_reset_window(now)
        and task_error
        and opening_interrupted
        and exact_sync_dialog
    )


def _recover_reclamation_after_daily_reset(run_log, now=None):
    """Acknowledge the verified 04:00 sync dialog and restore a clean Tales start page."""
    sync_path = shot("reclamation_daily_reset_sync")
    sync_text = ocr_text(sync_path)
    if not _reclamation_daily_reset_interruption(run_log, sync_text, now=now):
        log("❌ 生息演算错误不满足04:00刷新恢复三重证据，拒绝自动重启", "ERROR")
        return False
    if _maa_task_queue_running():
        log("❌ 04:00刷新错误后MAA仍未进入空闲，拒绝叠加启动第二条任务链", "ERROR")
        return False

    from PIL import Image
    with Image.open(sync_path) as image:
        width, height = image.size
    # 07/22 MaaCore原始失败截图：确认勾位于画面中心偏下。
    # 只有上面的完整同步文案成立时才允许使用这个比例坐标。
    tap(int(width * 0.5), int(height * 0.681))
    log("→ 已确认04:00‘数据已更新，即将进行同步’，等待重新进入游戏")

    reached_entry = False
    launch_attempted = False
    deadline = time.time() + 240
    while time.time() < deadline:
        wait(5)
        state = get_state()
        if state in ("main_menu", "reclamation_tales_main"):
            reached_entry = True
            break
        if state == "login":
            tap(*POS_LOGIN_START)
            log("  [04:00恢复] 登录页 → 点击黄色开始按钮")
            wait(12)
            continue
        if state == "announcement":
            _dismiss_announcement_overlay()
            continue
        if state == "network_error":
            path = shot("reclamation_daily_reset_network")
            items = ocr(path)
            pos = (
                find_text(items, "重新连接", exact=True)
                or find_text(items, "重试", exact=True)
                or find_text(items, "确定", exact=True)
            )
            if not pos:
                log("❌ 04:00恢复遇到网络弹窗但未定位明确按钮", "ERROR")
                return False
            tap(*pos)
            wait(8)
            continue
        if state == "home_screen" and not launch_attempted:
            launch_attempted = True
            detect_mumu_adb_port()
            subprocess.run(
                [ADB, "-s", DEVICE, "shell", "monkey", "-p", PKG, "-c",
                 "android.intent.category.LAUNCHER", "1"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            wait(15)
            continue
        if state == "unknown" and handle_popups():
            continue

    if not reached_entry:
        log("❌ 04:00同步确认后240秒仍未到主界面/沙洲遗闻主题页", "ERROR")
        return False

    # The interrupted PNS-Commence may have created a temporary save.  It is
    # safe to delete only because this exact run log and the ownership ledger
    # prove that the save belongs to the current automation run.
    if get_state() != "reclamation_tales_main" and not goto_reclamation_tales_main():
        pass
    probe = shot("reclamation_daily_reset_tales_probe")
    probe_text = ocr_text(probe)
    if "沙洲遗闻" in probe_text and "继续演算" in probe_text:
        if not _reclamation_resume_allowed(probe_text, run_log, max_age=None):
            log("❌ 04:00恢复发现临时档但无法证明归属，拒绝删除", "ERROR")
            return False
        if not _reset_owned_reclamation_temporary_save():
            return False
        _set_reclamation_ownership("clean", reason="daily_reset_recovery")
    elif not ("沙洲遗闻" in probe_text and "开始演算" in probe_text):
        log(f"❌ 04:00恢复未到沙洲遗闻开始/继续演算页: {probe_text[:120]}", "ERROR")
        return False

    if not goto_reclamation_tales_main():
        log("❌ 04:00刷新后未确认回到沙洲遗闻无存档‘开始演算’页", "ERROR")
        return False
    log("✅ 04:00每日刷新已恢复，允许续跑剩余生息演算预算")
    return True


def _reclamation_relevant_log_text(lines):
    """Keep the small evidence subset needed across MAA's 64 MiB log rotations."""
    markers = ("Reclamation", "PNS-", "ProsperityNoSave", "RA@Store")
    return "".join(
        line for line in (lines or [])
        if any(marker in line for marker in markers)
    )


def _stream_reclamation_log(path, after_line=0):
    """流式提取生息演算证据并返回总行数，不复制无关MAA日志。"""
    selected = []
    total_lines = 0
    markers = ("Reclamation", "PNS-", "ProsperityNoSave", "RA@Store")
    with open(path, "r", encoding="utf-8", errors="replace") as stream:
        for index, line in enumerate(stream):
            total_lines = index + 1
            if index >= max(0, int(after_line or 0)) and any(
                marker in line for marker in markers
            ):
                selected.append((index, line))
    return total_lines, _join_bounded_indexed_lines(selected)


def _wait_reclamation_cycle_budget(target_cycles, timeout, stop_deadline=None):
    """Wait for deleted cycles or a wall-clock deadline, then gracefully stop MAA."""
    global _LAST_MAA_RUN_LOG
    start = time.time()
    last_cycles = -1
    last_recovery = 0
    inactive_since = None
    boundary = max(0, _LAST_MAA_RUN_START_LINE)
    segment_identity = None
    archived_run_log = ""
    previous_segment_log = ""

    def snapshot_run_log():
        """Read this run cumulatively even when MAA rotates asst.log to asst.bak.log."""
        nonlocal boundary, segment_identity, archived_run_log, previous_segment_log
        line_count, current_segment = _stream_reclamation_log(MAA_LOG, boundary)
        stat = os.stat(MAA_LOG)
        identity = (getattr(stat, "st_ino", 0), getattr(stat, "st_ctime_ns", 0))
        rotated = (
            segment_identity is not None
            and (identity != segment_identity or line_count < boundary)
        )
        if rotated:
            backup_path = os.path.join(os.path.dirname(MAA_LOG), "asst.bak.log")
            archived_segment = ""
            try:
                backup_count, backup_segment = _stream_reclamation_log(
                    backup_path, boundary
                )
                if backup_count >= boundary:
                    archived_segment = backup_segment
            except Exception:
                archived_segment = ""
            # The last in-memory segment is still safer than discarding all
            # completed cycles if MAA has not finished renaming its backup yet.
            archived_run_log = _join_bounded_indexed_lines(enumerate(
                (archived_run_log + (archived_segment or previous_segment_log)).splitlines(
                    keepends=True
                )
            ))
            boundary = 0
            _line_count, current_segment = _stream_reclamation_log(MAA_LOG, 0)
            log(
                f"  [生息日志轮换] 已保留此前"
                f"{_count_reclamation_completed_cycles(archived_run_log)}轮，继续累计新日志"
            )
        segment_identity = identity
        previous_segment_log = current_segment
        return _join_bounded_indexed_lines(enumerate(
            (archived_run_log + previous_segment_log).splitlines(keepends=True)
        ))

    while time.time() - start < timeout:
        try:
            run_log = snapshot_run_log()
            _LAST_MAA_RUN_LOG = run_log
        except Exception:
            wait(1)
            continue

        if _reclamation_executed_resume(run_log):
            _stop_maa_task_queue()
            return "pns_resume_rejected"
        if 'TaskChainError' in run_log and '"taskchain":"Reclamation"' in run_log:
            error_path = shot("reclamation_taskchain_error")
            error_text = ocr_text(error_path)
            if _reclamation_daily_reset_interruption(
                    run_log, error_text, now=datetime.now()
            ):
                # Core emits TaskChainError a fraction of a second before the
                # GUI flips to idle.  Wait for that real boundary; there is no
                # Stop button once the errored chain has already become idle.
                for _ in range(20):
                    if not _maa_task_queue_running():
                        log("→ 已确认04:00刷新导致Reclamation中断且MAA已空闲，进入有限恢复")
                        return "daily_reset_sync"
                    wait(0.5)
                return "daily_reset_queue_not_idle"
            if _maa_task_queue_running():
                _stop_maa_task_queue()
            return "maa_taskchain_error"

        cycles = _count_reclamation_completed_cycles(run_log)
        if cycles != last_cycles:
            last_cycles = cycles
            log(f"  生息演算刷点进度: {cycles}/{target_cycles}轮")
        if cycles >= target_cycles:
            if not _stop_maa_task_queue():
                return "maa_stop_failed"
            # Core evidence and GUI idle are both required; Stop is not task completion.
            try:
                final_log = snapshot_run_log()
                _LAST_MAA_RUN_LOG = final_log
            except Exception:
                final_log = run_log
            return "budget_reached" if "TaskChainStopped" in final_log else "stop_unconfirmed"

        if stop_deadline and datetime.now() >= stop_deadline:
            log(f"→ 已到生息演算截止时间 {stop_deadline:%Y-%m-%d %H:%M}，停止MAA")
            if not _stop_maa_task_queue():
                return "maa_stop_failed"
            try:
                final_log = snapshot_run_log()
                _LAST_MAA_RUN_LOG = final_log
            except Exception:
                final_log = run_log
            return "deadline_reached" if "TaskChainStopped" in final_log else "stop_unconfirmed"

        process_exists = _maa_process_exists()
        queue_running = _maa_task_queue_running()
        cap_ok, _cap_detail = _reclamation_completion_evidence(run_log)
        chain_completed = bool(re.search(
            r'TaskChainCompleted[^\r\n]*"taskchain"\s*:\s*"Reclamation"',
            run_log,
        ))
        if process_exists and queue_running is False and chain_completed and cap_ok:
            log(
                f"✅ MAA已在{cycles}/{target_cycles}轮时达到繁荣度上限；"
                "真实删档及奖励商店入口证据齐全"
            )
            return "prosperity_cap_reached"
        unexpected_stop = _reclamation_unexpected_stop_reason(
            run_log, process_exists, queue_running,
        )
        if unexpected_stop:
            inactive_since = inactive_since or time.time()
            if time.time() - inactive_since >= 15:
                log(
                    f"❌ MAA在预算完成前已消失或空闲: {unexpected_stop} "
                    f"({cycles}/{target_cycles})",
                    "ERROR",
                )
                return unexpected_stop
        else:
            inactive_since = None

        now = time.time()
        if now - last_recovery >= 20 and _recover_reclamation_start_today_stall(run_log):
            last_recovery = now
        wait(1)

    _stop_maa_task_queue()
    return "budget_timeout"


def _reclamation_budget_evidence(run_log, target_cycles):
    """Bounded farming succeeds on real deleted cycles plus an explicit MAA stop."""
    run_log = run_log or ""
    if _reclamation_executed_resume(run_log):
        return False, "检测到PNS-Resume（DoNothing）"
    cycles = _count_reclamation_completed_cycles(run_log)
    missing = []
    if "PNS-Commence" not in run_log:
        missing.append("开始新演算")
    if cycles < target_cycles:
        missing.append(f"删档轮数{cycles}/{target_cycles}")
    if "TaskChainStopped" not in run_log:
        missing.append("MAA主动停止")
    if missing:
        return False, "缺少" + "、".join(missing)
    return True, f"已完成{cycles}轮并主动停止MAA"


def _reclamation_resume_allowed(
        screen_text, log_text=None, now=None, max_age=timedelta(hours=6)
):
    """只允许从本轮Tales临时档的主题主页恢复。

    实机验证表明 PNS-Navigation 不能识别任意生息地图节点页；必须先返回
    同时具有“沙洲遗闻”和“继续演算”的主题主页。日志只用于证明这份临时档
    是本自动化近6小时内创建/接管的，任务链的 Error 不能抹掉该来源证据。
    """
    screen_text = screen_text or ""
    if not ("沙洲遗闻" in screen_text and "继续演算" in screen_text):
        return False
    if log_text is None:
        try:
            with open(MAA_LOG, "r", encoding="utf-8", errors="replace") as f:
                log_text = f.read()
        except Exception:
            return False
    log_text = log_text or ""
    starts = list(re.finditer(r'TaskChainStart[^\n\r]*"taskchain":"Reclamation"', log_text))
    if not starts:
        return _reclamation_ownership_allows_resume(now=now)
    # 旧任务不能为今天的新临时档提供授权；仅接受近6小时内的真实启动行。
    # 中断恢复本身可能以 TaskChainError 结束，但临时档依旧属于本轮，不能因此
    # 强迫回到地图内再次启动，后者已由实机证明无法被 PNS-Navigation 识别。
    last_start = starts[-1]
    now = now or datetime.now()
    start_context = log_text[max(0, last_start.start() - 96):last_start.end()]
    stamp = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', start_context)
    if not stamp:
        return _reclamation_ownership_allows_resume(now=now)
    try:
        started_at = datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    age = now - started_at
    if timedelta(0) <= age and (max_age is None or age <= max_age):
        return True
    return _reclamation_ownership_allows_resume(now=now)


def _load_reclamation_ownership():
    try:
        with open(RECLAMATION_OWNERSHIP_FILE, "r", encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _set_reclamation_ownership(status, reason="", **extra):
    """持久记录无存档刷点临时档归属；clean状态不会授权未来删档。"""
    record = {
        "theme": "Tales",
        "mode": "ProsperityNoSave",
        "status": str(status),
        "reason": str(reason or ""),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        **extra,
    }
    os.makedirs(os.path.dirname(RECLAMATION_OWNERSHIP_FILE), exist_ok=True)
    temp_path = RECLAMATION_OWNERSHIP_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    os.replace(temp_path, RECLAMATION_OWNERSHIP_FILE)
    return record


def _reclamation_ownership_allows_resume(now=None, max_age=timedelta(hours=36)):
    """允许下一次日程接管上次异常中断留下的Tales临时档。

    页面仍须由调用者同时确认“沙洲遗闻”和“继续演算”；持久记录只保存
    自动化任务链创建临时档的归属，且超过36小时或已标clean都会失效。
    """
    record = _load_reclamation_ownership()
    if not (
        record.get("theme") == "Tales"
        and record.get("mode") == "ProsperityNoSave"
        and record.get("status") == "active"
    ):
        return False
    try:
        updated_at = datetime.fromisoformat(str(record.get("updated_at") or ""))
    except ValueError:
        return False
    now = now or datetime.now()
    age = now - updated_at
    return timedelta(0) <= age <= max_age


def _reclamation_completion_evidence(run_log):
    """排除PNS-Resume假完成，只承认达到上限、删档并进入商店的真实闭环。"""
    run_log = run_log or ""
    if _reclamation_executed_resume(run_log):
        return False, "检测到PNS-Resume（DoNothing），未执行真实刷点"
    required = {
        "开始新演算": "PNS-Commence",
        "繁荣点达到上限": "PNS-ProsperityReachLimit",
        "删除临时存档": "PNS-ProsperityReachLimit-SwipeSaveConfirm2",
        "进入奖励商店": "RA@Store@WaitEnterStore",
    }
    missing = [label for label, marker in required.items() if marker not in run_log]
    if missing:
        return False, "缺少" + "、".join(missing)
    return True, "真实刷点、删档、商店闭环齐全"


def _recover_reclamation_forced_tutorial(map_path, width, height):
    """完成Tales临时档的首次强制教学，返回退出区块后的地图截图。"""
    map_items = ocr(map_path)
    map_text = " ".join(t for t, _, _ in map_items)
    if "我和图耶正在讨论驻扎地建设" not in map_text:
        return map_path

    houshe = find_text(map_items, "后舍", exact=True)
    if not houshe:
        log("❌ 强制教学已出现，但未精确识别高亮的‘后舍’", "ERROR")
        return None
    tap(*houshe)
    wait(3)

    detail = shot("reclamation_tutorial_houshe")
    start = find_text(ocr(detail), "开始行动", exact=True)
    if not start:
        log("❌ 进入后舍后未精确识别‘开始行动’", "ERROR")
        return None
    tap(*start)
    wait(15)

    # 该强制教学只有四个单选回答。只有看见最后一个确切回答后，
    # 才允许尝试暂停/离开，避免在普通剧情或地图上盲点退出坐标。
    choices = (
        "这么快就要启程？",
        "谢谢。",
        "今天大家早些休息吧。",
        "明天还有很多要忙的。",
    )
    reached_battle = False
    for step in range(48):
        frame = shot(f"reclamation_tutorial_dialogue_{step + 1}")
        items = ocr(frame)
        selected = False
        for choice in choices:
            pos = find_text(items, choice, exact=True)
            if not pos:
                continue
            tap(*pos)
            wait(1)
            selected = True
            if choice == choices[-1]:
                # 最后回答后仍有少量收尾对白；多余点击落在空白战场，不会部署或确认。
                for _ in range(5):
                    tap(int(width * 0.807), int(height * 0.940))
                    wait(1)
                wait(3)
                reached_battle = True
            break
        if reached_battle:
            break
        if not selected:
            tap(int(width * 0.807), int(height * 0.940))
            wait(1)

    if not reached_battle:
        log("❌ 强制教学48步内未出现最后一个确切回答，拒绝盲目退出", "ERROR")
        return None

    tap(int(width * 0.943), int(height * 0.074))
    wait(1)
    tap(int(width * 0.057), int(height * 0.074))
    wait(3)
    leave = shot("reclamation_tutorial_leave_confirm")
    leave_items = ocr(leave)
    leave_text = " ".join(t for t, _, _ in leave_items)
    leave_confirm = find_text(leave_items, "确认离开", exact=True)
    if "离开当前区块" not in leave_text or not leave_confirm:
        log("❌ 教学战斗未出现精确‘离开当前区块/确认离开’闭环", "ERROR")
        return None
    tap(*leave_confirm)
    wait(10)

    recovered = shot("reclamation_tutorial_after_leave")
    recovered_text = ocr_text(recovered)
    if "粗制赤金" not in recovered_text or not any(
        key in recovered_text for key in ("晶莹碎片", "后舍", "驻扎地")
    ):
        log("❌ 离开教学区块后未确认回到Tales地图", "ERROR")
        return None
    log("✅ 强制教学临时档已自动推进并退出区块")
    return recovered


def _reset_owned_reclamation_temporary_save():
    """删除已由近6小时Reclamation日志证明归属本轮自动化的Tales临时档。"""
    p = shot("reclamation_reset_entry")
    items = ocr(p)
    text = " ".join(t for t, _, _ in items)
    if not ("沙洲遗闻" in text and "继续演算" in text):
        log("❌ 临时档清理入口不是沙洲遗闻继续演算页", "ERROR")
        return False
    pos = find_text(items, "继续演算", exact=True)
    if not pos:
        return False
    tap(*pos)
    wait(8)

    map_path = shot("reclamation_reset_map")
    map_text = ocr_text(map_path)
    if not ("粗制赤金" in map_text and any(k in map_text for k in ("晶莹碎片", "后舍", "驻扎地"))):
        log("❌ 继续演算后未确认进入Tales地图，拒绝删除", "ERROR")
        return False
    from PIL import Image
    with Image.open(map_path) as image:
        width, height = image.size
    map_path = _recover_reclamation_forced_tutorial(map_path, width, height)
    if not map_path:
        return False
    # A stop can land just after MAA has commenced the next no-save cycle.
    # Tales then replays a map tutorial dialogue which intercepts the first
    # click on the bottom-right ellipsis.  Repeating the same safe click only
    # advances that overlay; once it is gone the click opens the menu.  Never
    # click a delete coordinate until OCR has found the exact label.
    delete_pos = None
    for attempt in range(12):
        tap(int(width * 0.801), int(height * 0.933))
        wait(2)
        menu = shot(f"reclamation_reset_menu_{attempt + 1}")
        menu_items = ocr(menu)
        delete_pos = find_text(menu_items, "删除存档", exact=True)
        if delete_pos:
            break
    if not delete_pos:
        log("❌ 生息地图教学遮罩/更多菜单连续12次未出现精确‘删除存档’", "ERROR")
        return False
    tap(*delete_pos)
    wait(3)

    first = shot("reclamation_reset_confirm1")
    first_items = ocr(first)
    first_text = " ".join(t for t, _, _ in first_items)
    if "确认删除存档" not in first_text or "其余演算内容" not in first_text:
        log("❌ 删除存档第一次确认文案不完整", "ERROR")
        return False
    first_confirm = find_text(first_items, "确认删除", exact=True)
    if not first_confirm:
        return False
    tap(*first_confirm)
    wait(3)

    second = shot("reclamation_reset_confirm2")
    second_items = ocr(second)
    second_text = " ".join(t for t, _, _ in second_items)
    if "仍要删除存档" not in second_text or "操作无法回退" not in second_text:
        log("❌ 删除存档第二次不可回退确认文案不完整", "ERROR")
        return False
    second_confirm = find_text(second_items, "确认删除", exact=True)
    if not second_confirm:
        return False
    tap(*second_confirm)
    wait(10)

    final = shot("reclamation_reset_completed")
    final_text = ocr_text(final)
    ok = "沙洲遗闻" in final_text and "开始演算" in final_text and "继续演算" not in final_text
    if ok:
        log("✅ 本轮自动化Tales临时档已删除，重新出现‘开始演算’")
    else:
        log(f"❌ 临时档删除后未确认开始演算页: {final_text[:120]}", "ERROR")
    return ok

# ============================================================
# 场景模式: 主线推进
# ============================================================

# 全章节关卡列表 (显示名, 内部stage_name)
ALL_CHAPTERS = {}
CHAPTER_STAGE_MAX = {
    # 07/30 实机终局：第13章普通/剧情节点到13-22，第15章普通节点到
    # 15-21，第16章普通节点到16-19；08/21实机在完成17-20后明确解锁
    # 17-21，主页快捷卡也显示该节点。旧逻辑统一生成到20，会漏掉真实
    # 尾关（包括13-22/17-21剧情后的奖励）或追逐不存在的16-20。
    13: 22,
    15: 21,
    16: 19,
    17: 21,
}
for ch in range(10, 18):
    stages = []
    max_stage = CHAPTER_STAGE_MAX.get(ch, 20)
    # 🔴 2026-07-07 修复: ch-1是TR/序章关(非战斗关), 从ch-2开始.
    # 之前从1开始会生成"10-1"等不存在的关卡, 导致脚本尝试攻略TR关并误报阻塞.
    for i in range(2, max_stage + 1):
        display = f"{ch}-{i}"
        if ch <= 14:
            internal = f"tough_{ch}-{i-1:02d}"
        elif ch <= 16:
            internal = f"main_{ch}-{i-1:02d}"
        else:
            internal = f"{ch}-{i}"
        stages.append((display, internal))
    ALL_CHAPTERS[ch] = stages


def _stage_chapter(stage_name):
    """从12-21、H12-4等关卡名提取章节号。"""
    match = re.search(r'(?<!\d)H?(\d{1,2})\s*[-—]\s*\d{1,2}', str(stage_name or ""), re.I)
    return int(match.group(1)) if match else None


def _mainline_target_sort_key(stage_name):
    """按章节真实前沿排序：普通关在同章H关之前，未知名称排到最后。"""
    clean = re.sub(r'\([^)]*\)', '', str(stage_name or '')).strip().upper()
    match = re.fullmatch(r'(H)?(\d{1,2})[-—](\d{1,2})', clean)
    if not match:
        return (999, 9, 999)
    hard_prefix, chapter, index = match.groups()
    return (int(chapter), 1 if hard_prefix else 0, int(index))


# 主线H关按同章顺序推进。用户已确认H关是独立待办链；完成H13-2后
# 必须保留H13-3，而不能被更晚章节的普通关局部结果覆盖。当前已出现的
# 主线H章节均为四关；只有在真实处理某一H关后才使用其同章后继，不会
# 凭该表自行插入一个从未开始的H章节。
HARD_STAGE_SEQUENCES = {
    ch: [f"H{ch}-{index}" for index in range(1, 5)]
    for ch in range(11, 18)
}


def _next_hard_stage(stage, prog):
    """返回同一已开始H链中尚未完成的下一关。"""
    clean = re.sub(r'\([^)]*\)', '', str(stage or '')).strip().upper()
    chapter = _stage_chapter(clean)
    sequence = HARD_STAGE_SEQUENCES.get(chapter, [])
    if clean not in sequence:
        return None
    cleared = set(prog.get("cleared", []))
    shelved = set(prog.get("shelved", []))
    for candidate in sequence[sequence.index(clean) + 1:]:
        if candidate not in cleared and candidate not in shelved:
            return candidate
    return None


def _next_pending_hard_stage(prog=None, chapter=None):
    """普通主线前沿完成后，返回最早尚未闭环的H关。

    旧调度器只有在某个H关已经写入``current``后才会续接同章下一关，
    因而H14/H16/H17这类从未启动过的整章永久不进队列。这里以明确的
    H关序列为边界，并且只跳过已有完成证据或已搁置节点。
    """
    prog = prog or load_progress()
    cleared = set(prog.get("cleared", []))
    shelved = set(prog.get("shelved", []))
    chapters = [chapter] if chapter in HARD_STAGE_SEQUENCES else sorted(HARD_STAGE_SEQUENCES)
    for hard_chapter in chapters:
        for candidate in HARD_STAGE_SEQUENCES.get(hard_chapter, []):
            if candidate not in cleared and candidate not in shelved:
                return candidate
    return None


def _internal_stage_name(ch, display_name):
    """生成MAA作业关卡名；H关必须保留H编号，不能误映射成普通tough关。"""
    clean = re.sub(r'\([^)]*\)', '', str(display_name or "")).strip()
    hard_match = re.fullmatch(r"H(\d{1,2})-(\d{1,2})", clean, re.I)
    if hard_match:
        # MAA作业站的权威内部编号为 hard_CC-NN；_copilot_matches_stage
        # 同时兼容本地新作业直接写HCC-N的格式。
        return f"hard_{int(hard_match.group(1)):02d}-{int(hard_match.group(2)):02d}"
    if clean.upper().startswith("TR-") or "ST" in clean.upper():
        return clean
    stage_num = int(clean.split("-")[1])
    if ch <= 14:
        return f"tough_{ch}-{stage_num-1:02d}"
    if ch <= 16:
        return f"main_{ch}-{stage_num-1:02d}"
    return clean


def _mainline_sanity_cost(ch, display_name):
    """返回本次主线战斗的真实理智成本；H关固定以详情页显示的10计。"""
    clean = re.sub(r'\([^)]*\)', '', str(display_name or "")).strip().upper()
    if clean.startswith("H"):
        return 10
    return int(DIFFICULTY.get(ch, {}).get("sanity_cost", 21))


def _pending_recorded_target(ch, prog=None):
    """进度文件中的明确待办优先于“地图最右侧看起来已清”的弱推断。"""
    prog = prog or load_progress()
    current = re.sub(r'\([^)]*\)', '', str(prog.get("current") or "")).strip()
    cleared = set(prog.get("cleared", []))
    imperfect = set(prog.get("imperfect", []))
    shelved = set(prog.get("shelved", []))
    # 已首通但未完美仍是明确待办；不能因为它同时存在于cleared中就跳去下一章。
    if (
        current
        and current not in shelved
        and _stage_chapter(current) == ch
        and (current not in cleared or current in imperfect)
    ):
        return current
    return None


def _validate_recorded_target_before_battle(ch, stage):
    """把进度文件待办降级为候选，开打前以当前地图图形重新复核。"""
    cleared, perfect = verify_stage_cleared(ch, stage)
    evidence = dict(_LAST_STAGE_MARKER_VERIFICATION or {})
    if evidence.get("status") != "verified":
        log(
            f"⛔ 进度待办{stage}战前图形复核不确定"
            f"({evidence.get('status', 'unknown')})，拒绝开打",
            "ERROR",
        )
        return "uncertain"
    if cleared and perfect:
        update_progress(stage, "cleared", "战前地图复核已完美；自动修订错误待办")
        prog = load_progress()
        if prog.get("current") == stage:
            next_stage = _next_configured_target(ch, prog)
            prog["current"] = next_stage
            save_progress(prog)
        log(f"✅ 进度待办{stage}实际已完美通关；已修订进度并重新调度")
        return "already_perfect"
    if cleared:
        update_progress(stage, "imperfect", "战前地图复核已通关但未完美")
        log(f"  [待办复核] {stage}已通关但未完美，保留补打目标")
        return "imperfect"
    log(f"  [待办复核] {stage}地图节点确认未通关，允许进入战斗")
    return "uncleared"


def _chapter17_phase_has_direct_evidence(prog, stage, phase):
    """阶段账本只有同时具备终态证据时才允许调度器跳过。

    新记录使用显式 ``*_evidence``；迁移前的合法记录只兼容两种可审计
    直接证据：险地详情/结算备注，或沙盘最终白色节点备注/成功组合。
    单独的 ``risk=cleared`` / ``sandbox=cleared`` 永远不构成完成证明。
    """
    prog = prog or {}
    record = ((prog.get("chapter17_phases") or {}).get(stage) or {})
    if record.get(phase) != "cleared":
        return False
    evidence = str(record.get(f"{phase}_evidence") or "").strip()
    if evidence:
        return True
    note = str((prog.get("notes") or {}).get(stage) or "")
    if phase == "risk":
        risk_note = str(record.get("risk_note") or "")
        return bool(
            any(marker in risk_note for marker in ("详情三枚徽记", "结算"))
            or "险地+沙盘闭环，地图最终白色节点确认" in note
        )
    if phase == "sandbox":
        return bool(
            record.get("sandbox_cleared_trial")
            or "险地+沙盘闭环，地图最终白色节点确认" in note
        )
    return False


def _next_configured_target(ch, prog=None):
    """Choose the next expected stage; the game map must still locate it visually."""
    prog = prog or load_progress()
    if ch == 17:
        pending_phase = _chapter17_pending_phase_target(prog)
        if pending_phase:
            return pending_phase
    cleared = set(prog.get("cleared", []))
    standard_only = set(prog.get("cleared_standard_only", []))
    imperfect = set(prog.get("imperfect", []))
    shelved = set(prog.get("shelved", []))
    # 标准环境首通不等于用户要求的最高难度完成。该关可能同时存在于
    # cleared中作为“至少首通”证据；最难难度调度必须优先把它重新列为待办。
    for display_name, _internal_name in ALL_CHAPTERS.get(ch, []):
        if display_name in standard_only and display_name not in shelved:
            return display_name
    # 非完美关同时存在于cleared中。章节普通线走到末尾后，旧逻辑只检查
    # “不在cleared”，会把12-12/12-13这类明确待补关永久漏掉并误报
    # 整章完成。先按章节顺序返回未搁置的非完美节点。
    for display_name, _internal_name in ALL_CHAPTERS.get(ch, []):
        if display_name in imperfect and display_name not in shelved:
            return display_name
    for display_name, _internal_name in ALL_CHAPTERS.get(ch, []):
        if display_name not in cleared and display_name not in shelved:
            return display_name
    return None


def _chapter17_pending_phase_target(prog=None, excluded=None):
    """返回第17章最早尚未完成险地+沙盘闭环的战斗关。

    `cleared` 只说明至少完成过一次普通/险地战斗，不能覆盖阶段账本。
    因此阶段待办必须高于 current 和普通章节顺序，防止跳过沙盘推演。
    """
    prog = prog or load_progress()
    excluded = set(excluded or [])
    phases = prog.get("chapter17_phases") or {}
    for display_name, _internal_name in ALL_CHAPTERS.get(17, []):
        if not _chapter17_stage_requires_sandbox(display_name):
            continue
        if display_name in excluded:
            continue
        if not _chapter17_phase_has_direct_evidence(
            prog, display_name, "risk"
        ) or not _chapter17_phase_has_direct_evidence(
            prog, display_name, "sandbox"
        ):
            return display_name
    return None


def _next_unshelved_mainline_target(prog, start_chapter=None):
    """从当前章节向后找获准的普通主线目标，避免搁置H关重新阻塞调度器。"""
    cleared = set(prog.get("cleared", []))
    standard_only = set(prog.get("cleared_standard_only", []))
    shelved = set(prog.get("shelved", []))
    chapters = sorted(ALL_CHAPTERS)
    if start_chapter in chapters:
        index = chapters.index(start_chapter)
        chapters = chapters[index:] + chapters[:index]
    for chapter in chapters:
        for display_name, _internal_name in ALL_CHAPTERS.get(chapter, []):
            if display_name in standard_only and display_name not in shelved:
                return display_name
            if display_name not in cleared and display_name not in shelved:
                return display_name
    return None


def _shelve_mainline_stage(stage, reason):
    """有界搁置已耗尽作业预算的关卡，并把current移到下个获准普通主线。"""
    clean_stage = re.sub(r'\([^)]*\)', '', str(stage or "")).strip()
    prog = load_progress()
    prog.setdefault("shelved", [])
    prog.setdefault("notes", {})
    if clean_stage and clean_stage not in prog["shelved"]:
        prog["shelved"].append(clean_stage)
    if clean_stage:
        prog["notes"][clean_stage] = reason
    prog["current"] = _next_unshelved_mainline_target(
        prog, start_chapter=_stage_chapter(clean_stage)
    )
    save_progress(prog)
    state = _RUN_SUMMARY.setdefault("mainline", {})
    state.setdefault("shelved_stages", [])
    if clean_stage and clean_stage not in state["shelved_stages"]:
        state["shelved_stages"].append(clean_stage)
    log(f"  [主线] 已搁置{clean_stage}；下一个获准目标={prog.get('current') or '无'}", "WARN")
    return prog.get("current")


def _frontier_imperfect_target(ch, configured_target, prog=None, already_retried=None):
    """Return the immediately preceding imperfect node that may block the frontier."""
    if not configured_target or _stage_chapter(configured_target) != ch:
        return None
    prog = prog or load_progress()
    already_retried = set(already_retried or ())
    imperfect = set(prog.get("imperfect", []))
    match = re.fullmatch(rf"{ch}-(\d+)", configured_target)
    if not match:
        return None
    previous = f"{ch}-{int(match.group(1)) - 1}"
    if previous in imperfect and previous not in already_retried:
        return previous
    return None


def _set_mainline_run_status(status, detail=""):
    """把本轮主线增量写入报告，禁止用历史cleared总数冒充本轮推进。"""
    before = _MAINLINE_RUN_SNAPSHOT or {}
    prog = load_progress()
    new_cleared = sorted(set(prog.get("cleared", [])) - set(before.get("cleared", [])))
    new_imperfect = sorted(set(prog.get("imperfect", [])) - set(before.get("imperfect", [])))
    new_shelved = sorted(set(prog.get("shelved", [])) - set(before.get("shelved", [])))
    state = _RUN_SUMMARY.setdefault("mainline", {})
    state.update({
        "status": status,
        "detail": detail,
        "starting_target": state.get("starting_target"),
        "next_target": prog.get("current"),
        "newly_cleared": new_cleared,
        "newly_imperfect": new_imperfect,
        "newly_shelved": new_shelved,
        "progressed": bool(new_cleared or new_imperfect),
    })
    _save_mainline_handoff(status, detail, state)
    return state

def sync_progress_from_map(ch):
    """进入章节地图, 从左到右扫描, 用六芒星验证实际通关状态, 更新进度文件
    
    🔴 2026-07-10 根源修复: 不依赖进度文件, 直接从游戏地图读取真实状态
    🔴 2026-07-10 优化: 遇到第一个未通关或地图上找不到的关卡就停止
       (关卡是顺序解锁的, 12-12不在地图上→12-13+也不可能在)
    """
    log(f"\n→ 地图同步: 扫描第{ch}章实际通关状态...")
    
    if not _force_to_chapter_map(ch):
        log("  ⚠️ 无法进入章节地图, 跳过同步", "WARN")
        return
    
    prog = load_progress()
    cleared = set(prog.get("cleared", []))
    imperfect = set(prog.get("imperfect", []))
    failed = set(prog.get("failed", []))
    
    stages = ALL_CHAPTERS.get(ch, [])
    updated = False
    
    # 滑到最左边
    for i in range(3):
        swipe(300, 500, 1500, 500, 1000)
        wait(1)
    
    for display, internal in stages:
        if display in cleared:
            continue
        
        # 找关卡
        map_search = re.sub(r'\([^)]*\)', '', display).strip()
        p = shot(f"sync_{display}")
        pos = _find_stage_node_text(ocr(p), map_search)
        
        if not pos:
            for j in range(3):
                swipe(1500, 500, 300, 500, 1000)
                wait(1)
                p = shot(f"sync_{display}_r{j}")
                pos = _find_stage_node_text(ocr(p), map_search)
                if pos:
                    break
        
        if not pos:
            # 🔴 关卡不在地图上 = 还没解锁, 后面的关卡也不可能解锁, 停止扫描
            log(f"  {display}: 地图上未找到(未解锁), 停止扫描")
            break
        
        # 六芒星验证 (对剧情关和战斗关都适用)
        try:
            cleared_status, is_perfect = verify_stage_cleared(ch, display)
            if cleared_status:
                if is_perfect:
                    log(f"  {display}: ✅ 已完美通关(地图验证)")
                    cleared.add(display)
                    imperfect.discard(display)
                    failed.discard(display)
                    prog["notes"][display] = f"地图同步: 完美通关"
                    updated = True
                else:
                    log(f"  {display}: ⚠️ 已非完美通关(地图验证)")
                    cleared.add(display)
                    imperfect.add(display)
                    failed.discard(display)
                    prog["notes"][display] = f"地图同步: 非完美通关"
                    updated = True
            else:
                # 🔴 第一个未通关的关卡 = 下一个目标, 停止扫描
                log(f"  {display}: ❌ 未通关, 这是下一个目标, 停止扫描")
                break
        except Exception as e:
            log(f"  {display}: 验证异常 {e}", "WARN")
            break
    
    if updated:
        prog["cleared"] = sorted(cleared)
        prog["imperfect"] = sorted(imperfect)
        prog["failed"] = sorted(failed)
        save_progress(prog)
        log(f"  → 进度文件已更新: cleared={len(cleared)}, imperfect={len(imperfect)}")
    else:
        log(f"  → 无变化 (cleared={len(cleared)})")

def _check_stamina_confirmed():
    """获取理智值, 连续3次<21才确认不足, 避免OCR误读"""
    stamina = get_stamina()
    if stamina is None or stamina >= 21:
        return stamina
    # 可疑低值, 重试确认
    log(f"  ⚠️ 理智OCR={stamina}, 重试确认...")
    for retry in range(3):
        wait(3)
        s = get_stamina()
        if s is None or s >= 21:
            log(f"  → 重试{retry+1}: 理智={s}, 继续")
            return s
        log(f"  → 重试{retry+1}: 理智={s}")
    return stamina  # 3次都<21, 确认不足

def _find_next_target(ch, cleared):
    """找出第一个未通关的关卡作为current"""
    prog = load_progress()
    imperfect = set(prog.get("imperfect", []))
    shelved = set(prog.get("shelved", []))
    stages = ALL_CHAPTERS.get(ch, [])
    
    # 1. 先找imperfect
    for display, internal in stages:
        if display in imperfect and display not in shelved:
            return display
    # 2. 再找未通关
    for display, internal in stages:
        if display not in cleared and display not in shelved:
            return display
    return None

def mode_mainline(
    start_chapter=None,
    target_stage=None,
    target_max_attempts=5,
    target_excluded_jobs=None,
):
    """主线推进: 从当前进度开始
    
    🔴 2026-07-10 根源修复: 先从地图同步实际进度, 再决定打哪关
    🔴 2026-07-01 优化: 优先处理progress.current指定的关卡
    """
    log("=" * 60)
    log("  场景: 主线推进")
    log("=" * 60)

    global _MAINLINE_RUN_SNAPSHOT, _MAINLINE_STAGE_ATTEMPTS, _MAINLINE_HARD_MAP_EVIDENCE
    _MAINLINE_STAGE_ATTEMPTS = {}
    _MAINLINE_HARD_MAP_EVIDENCE = {}
    prog = load_progress()
    _MAINLINE_RUN_SNAPSHOT = {
        "started_at": datetime.now().isoformat(),
        "cleared": set(prog.get("cleared", [])),
        "imperfect": set(prog.get("imperfect", [])),
        "failed": set(prog.get("failed", [])),
        "shelved": set(prog.get("shelved", [])),
    }

    # 人工点名补关时只处理这一关，不能先走“整章已完成”扫描，也不能
    # 临时把该关从cleared删除来欺骗调度器。深色立方体会在clear_stage
    # 内触发最多5份不同作业的强制补打，蓝色节点才算完成。
    if target_stage:
        target_stage = re.sub(r'\([^)]*\)', '', str(target_stage)).strip()
        target_chapter = _stage_chapter(target_stage)
        if not target_chapter:
            log(f"❌ 无法从指定关卡解析章节: {target_stage}", "ERROR")
            return False
        if start_chapter and start_chapter != target_chapter:
            log(
                f"  [点名补关] --chapter {start_chapter} 与 {target_stage} 不一致，"
                f"以关卡所属第{target_chapter}章为准",
                "WARN",
            )
        _RUN_SUMMARY["mainline"] = {
            "status": "running",
            "starting_target": target_stage,
            "next_target": target_stage,
            "progressed": False,
            "targeted": True,
        }
        target_max_attempts = min(int(target_max_attempts or 5), 5)
        if not _force_to_chapter_map(target_chapter):
            _set_mainline_run_status("navigation_failed", f"无法进入第{target_chapter}章地图")
            return False
        result = clear_stage(
            target_chapter,
            target_stage,
            _internal_stage_name(target_chapter, target_stage),
            max_attempts=target_max_attempts,
            force_replay=True,
            initial_used_ops=target_excluded_jobs,
        )
        if result is True:
            _set_mainline_run_status("completed", f"点名补关{target_stage}已完美")
            return True
        if result == "imperfect":
            _shelve_mainline_stage(target_stage, f"{target_stage}五份不同作业后仍未完美")
            _set_mainline_run_status("shelved", f"{target_stage}五份作业后仍未完美")
            return True
        if result == "stamina":
            _set_mainline_run_status("stamina_exhausted", f"{target_stage}前理智不足")
            return True
        if result in ("navigation_failed", "stage_not_found"):
            _set_mainline_run_status(
                "navigation_failed",
                f"点名关卡{target_stage}地图定位/编队入口失败；未启动MAA、未消耗作业次数",
            )
            return False
        if result == "jobs_unavailable":
            _set_mainline_run_status("blocked", f"点名关卡{target_stage}没有可执行作业")
            return False
        if result == "maa_control_failed":
            _set_mainline_run_status("blocked", f"点名关卡{target_stage}的MAA控件启动失败")
            return False
        if target_stage.upper().startswith("H"):
            _shelve_mainline_stage(target_stage, f"{target_stage}五份不同作业后仍未通关")
            _set_mainline_run_status("shelved", f"点名H关{target_stage}五份作业后仍未通关")
        else:
            _record_decision_request(
                "普通主线阻塞关处理方案",
                f"点名关卡{target_stage}已执行{target_max_attempts}份不同作业仍未通关，未执行任何替代关卡",
                ["G-AUTH-001", "G-MAINLINE-001"],
                {"stage": target_stage, "attempt_budget": target_max_attempts},
            )
            _set_mainline_run_status("blocked", f"点名补关{target_stage}未完成: {result}")
        return False
    
    cleared = set(prog.get("cleared", []))
    imperfect = set(prog.get("imperfect", []))
    cleared_standard_only = set(prog.get("cleared_standard_only", []))
    failed = set(prog.get("failed", []))
    shelved = set(prog.get("shelved", []))
    log(f"已通关(磨难): {sorted(cleared)}")
    if imperfect:
        log(f"首次通关(非完美): {sorted(imperfect)}")
    if cleared_standard_only:
        log(f"标准通关(磨难未通): {sorted(cleared_standard_only)}")
    
    current_target = prog.get("current")
    if current_target:
        log(f"当前目标(进度文件): {current_target}")
    _RUN_SUMMARY["mainline"] = {
        "status": "running",
        "starting_target": current_target,
        "next_target": current_target,
        "progressed": False,
    }
    
    # 确定起始章节
    recorded_chapter = _stage_chapter(current_target)
    standard_only = set(prog.get("cleared_standard_only", []))
    if start_chapter:
        ch = start_chapter
    elif (
        recorded_chapter
        and current_target not in shelved
        and (current_target not in cleared or current_target in imperfect)
    ):
        ch = recorded_chapter
    else:
        ch = 10
        found_regular_target = False
        for c in sorted(ALL_CHAPTERS.keys()):
            all_cleared = all(
                (s[0] in cleared and s[0] not in standard_only) or s[0] in shelved
                for s in ALL_CHAPTERS[c]
            )
            if not all_cleared:
                ch = c
                found_regular_target = True
                break
        # 所有普通/剧情前沿都闭环后，继续最早未完成H章；不能因为current
        # 为空就回到第10章扫描一圈并最终误报“当前配置末端”。
        if not found_regular_target:
            pending_hard = _next_pending_hard_stage(prog)
            if pending_hard:
                ch = _stage_chapter(pending_hard)
    
    log(f"起始章节: 第{ch}章")
    
    # 🔴 2026-07-10 根源重构: 主页→进章节→选难度→检测最右→战斗
    # 不重复导航: 进章节只在换章时做, clear_stage内部会回章节地图
    need_navigate = True  # 第一次需要导航进章节
    frontier_retried = set()
    deferred_chapter17_phases = set()
    while ch in ALL_CHAPTERS:
        # 只在换章节时导航进地图+选难度
        if need_navigate:
            if not _force_to_chapter_map(ch):
                log(f"  ⚠️ 无法进入第{ch}章地图", "WARN")
                _set_mainline_run_status("navigation_failed", f"无法进入第{ch}章地图")
                return False
            if not select_hardest_difficulty(ch):
                _set_mainline_run_status(
                    "blocked", f"第{ch}章最难难度无法确认，未执行自动降级"
                )
                return False
            need_navigate = False
        
        # 进度文件明确指向H12-4等待办时必须先处理；0717旧逻辑只看
        # 12-20/12-21便把整章误判为完成。
        prog = load_progress()
        phase_target = (
            _chapter17_pending_phase_target(
                prog, excluded=deferred_chapter17_phases,
            )
            if ch == 17 else None
        )
        recorded_target = _pending_recorded_target(ch, prog)
        configured_target = phase_target or recorded_target or _next_configured_target(ch, prog)
        hard_candidate = None
        if not configured_target and _next_unshelved_mainline_target(prog) is None:
            # 数组只负责指出“本章理论上仍有H欠账”；真正选谁必须由当前
            # 游戏地图OCR与节点图形决定，不能直接把候选编号送进战斗。
            hard_candidate = _next_pending_hard_stage(prog, chapter=ch)
        # 即使current已经写成下一关，也要先检查其紧邻前置是否仍为非完美。
        # 非完美前置可能尚未解锁下一节点；此前把recorded_target放在此检查
        # 之前，导致13-8不可见时空转五次并被谎报为五份作业失败。
        frontier_imperfect = _frontier_imperfect_target(
            ch, configured_target, prog, frontier_retried
        )
        if frontier_imperfect:
            stage_name, stage_pos, stage_status = frontier_imperfect, None, "frontier_imperfect"
            log(f"  [地图] 新关未展开，先补打前置非完美: {stage_name}")
        elif phase_target:
            stage_name, stage_pos, stage_status = phase_target, None, "chapter17_phase_pending"
            phase = (prog.get("chapter17_phases") or {}).get(phase_target) or {}
            log(
                f"  [第17章阶段闭环] 优先补{phase_target}: "
                f"险地={phase.get('risk', 'pending')}，沙盘={phase.get('sandbox', 'pending')}"
            )
        elif recorded_target:
            stage_name, stage_pos, stage_status = recorded_target, None, "recorded_pending"
            log(f"  [地图] 优先处理进度文件待办: {stage_name}")
        elif configured_target:
            stage_name, stage_pos, stage_status = configured_target, None, "configured_pending"
            log(f"  [地图] 按章节顺序定位下一个待办: {stage_name}")
        else:
            stage_name, stage_pos, stage_status = _find_next_stage_from_map(
                ch, hard_only=bool(hard_candidate),
            )
            if hard_candidate and stage_name:
                log(
                    f"  [H关地图准入] 候选起点={hard_candidate}；"
                    f"地图实际选择={stage_name}({stage_status})"
                )
            elif hard_candidate and stage_status is None:
                stage_status = "hard_not_visible"
        if stage_name is None and stage_status == "hard_not_visible":
            detail = (
                f"第{ch}章账本仍有{hard_candidate}等H关欠账，但完整地图扫描"
                "没有取得可见H节点/解锁证据；未打开详情、未读取作业、未启动MAA"
            )
            log(f"⛔ {detail}", "ERROR")
            _set_mainline_run_status("navigation_failed", detail)
            return False
        if stage_name is None and stage_status == "uncertain":
            detail = f"第{ch}章地图存在节点标志定位不确定；未选择关卡，停止主线"
            log(f"⛔ {detail}", "ERROR")
            _set_mainline_run_status("navigation_failed", detail)
            return False
        if stage_name is None:
            log(f"  → 第{ch}章全部通关, 进入下一章")
            ch += 1
            need_navigate = True
            continue
        
        display_name = stage_name
        internal_name = _internal_stage_name(ch, display_name)

        if stage_status == "recorded_pending":
            recorded_check = _validate_recorded_target_before_battle(ch, display_name)
            if recorded_check == "already_perfect":
                # 进度文件已经修复；回到循环重新计算真正的下一关。
                checkpoint()
                continue
            if recorded_check == "uncertain":
                # 进度文件只提供候选。节点找不到时必须回到当前地图扫描真实
                # 前沿，不能因此把还有理智的整条主线提前送入收尾。
                fallback_name, fallback_pos, fallback_status = _find_next_stage_from_map(ch)
                if fallback_name:
                    log(
                        f"  [待办复核] {display_name}不可定位；"
                        f"改用地图真实前沿{fallback_name}({fallback_status})",
                        "WARN",
                    )
                    stage_name, stage_pos, stage_status = (
                        fallback_name,
                        fallback_pos,
                        fallback_status,
                    )
                    display_name = stage_name
                    internal_name = _internal_stage_name(ch, display_name)
                else:
                    detail = (
                        f"进度待办{display_name}战前图形复核不确定，且当前地图"
                        f"未形成可执行前沿({fallback_status or 'none'})；未启动战斗"
                    )
                    _set_mainline_run_status("navigation_failed", detail)
                    return False
            if recorded_check == "imperfect":
                stage_status = "frontier_imperfect"
        
        log(f"\n攻关: {display_name}")
        write_status(f"主线推进: 攻关 {display_name}", f"章节{ch} | 最多5次尝试")
        
        if check_stall(600):
            log(f"  ⚠️ 脚本卡住，尝试恢复", "WARN")
            goto_main_menu()
            wait(3)
            need_navigate = True
            continue
        
        # 🔴 2026-07-10: 不在循环里读理智(会退出章节地图回主页)
        # clear_stage内部的_find_and_enter_stage会检测理智不足, 返回"stamina"

        # full/mainline 与 chapter17_sandbox 必须共享同一份沙盘失败账本。
        # 旧实现只在专项入口排除历史失败作业，完整流程会重新加载同一份
        # risk_job，造成“专项已换作业、full又从第一份开始”的重复战斗。
        chapter17_failed_jobs = None
        if stage_status == "chapter17_phase_pending":
            phase_record = (
                (prog.get("chapter17_phases") or {}).get(display_name) or {}
            )
            if (
                _chapter17_phase_has_direct_evidence(
                    prog, display_name, "risk"
                )
                and not _chapter17_phase_has_direct_evidence(
                    prog, display_name, "sandbox"
                )
            ):
                chapter17_failed_jobs = _chapter17_sandbox_failed_jobs(phase_record)
                historical_attempts = _chapter17_sandbox_historical_attempts(
                    phase_record,
                )
                if historical_attempts:
                    _MAINLINE_STAGE_ATTEMPTS[display_name] = {
                        "status": "running",
                        "detail": "第17章沙盘历史失败续跑",
                        "attempt_count": len(historical_attempts),
                        "attempted_jobs": list(chapter17_failed_jobs),
                        "attempts": historical_attempts,
                        "outcome_counts": {
                            "historical_failed": len(historical_attempts)
                        },
                        "preflight_rejections": [],
                    }
                    log(
                        f"  [第17章沙盘续跑] 历史真实战败已计入五份总额度并排除: "
                        f"{chapter17_failed_jobs}"
                    )
        
        # clear_stage内部会导航回章节地图, 不需要再手动导航
        ok = clear_stage(
            ch,
            display_name,
            internal_name,
            max_attempts=5,
            force_replay=(
                stage_status == "frontier_imperfect"
                or stage_status == "chapter17_phase_pending"
                or (stage_status == "recorded_pending" and display_name in set(prog.get("imperfect", [])))
            ),
            force_enter=(
                stage_status == "uncertain_probe"
                or stage_status == "chapter17_phase_pending"
                or (
                    stage_status == "recorded_pending"
                    and display_name not in set(prog.get("cleared", []))
                )
            ),
            initial_used_ops=chapter17_failed_jobs,
        )
        checkpoint()
        if stage_status == "frontier_imperfect":
            frontier_retried.add(display_name)

        if (
            isinstance(ok, tuple)
            and len(ok) >= 2
            and ok[0] == "tr_required"
        ):
            training_stage = ok[1]
            log(
                f"↻ {display_name} 尚未解锁；先处理零理智前置教学关 "
                f"{training_stage}，完成后返回同一目标"
            )
            training_ok = clear_stage(
                ch,
                training_stage,
                _internal_stage_name(ch, training_stage),
                max_attempts=5,
                training_stage=True,
            )
            checkpoint()
            if training_ok is True:
                _set_mainline_run_status(
                    "running",
                    f"{training_stage}零理智教学已完成，恢复{display_name}",
                )
                need_navigate = True
                continue
            detail = (
                f"{training_stage}教学关未取得完成证据({training_ok})；"
                "未改换关卡，冻结后续理智"
            )
            log(f"⛔ {detail}", "ERROR")
            _set_mainline_run_status("blocked", detail)
            return False
        
        if ok == "stamina":
            log(f"⚠️ 理智不足, 停止主线推进")
            _set_mainline_run_status("stamina_exhausted", f"{display_name}前理智不足")
            return True
        if ok in ("navigation_failed", "stage_not_found"):
            detail = (
                f"{display_name}地图定位/编队入口失败；未启动MAA，"
                "未消耗任何作业重试次数"
            )
            log(f"⛔ {detail}", "ERROR")
            _set_mainline_run_status("navigation_failed", detail)
            return False
        if ok == "jobs_unavailable":
            if (
                stage_status == "chapter17_phase_pending"
                and _chapter17_phase_has_direct_evidence(
                    prog, display_name, "risk"
                )
            ):
                deferred_chapter17_phases.add(display_name)
                detail = (
                    f"{display_name}沙盘没有带明确两级假设的兼容作业；"
                    "保留沙盘待办，本轮继续其他已解锁阶段，不冻结理智链"
                )
                log(f"⏭ {detail}", "WARN")
                _MAINLINE_STAGE_ATTEMPTS.setdefault(display_name, {}).update({
                    "status": "deferred_jobs_unavailable",
                    "detail": detail,
                })
                _set_mainline_run_status("running", detail)
                need_navigate = True
                continue
            detail = f"{display_name}没有可执行作业；未启动战斗，不能记为作业失败"
            log(f"⛔ {detail}", "ERROR")
            _set_mainline_run_status("blocked", detail)
            return False
        if ok == "maa_control_failed":
            detail = f"{display_name}的MAA控件启动失败；未启动战斗，不计入作业失败"
            log(f"⛔ {detail}", "ERROR")
            _set_mainline_run_status("blocked", detail)
            return False
        if ok == "completed_navigation_failed":
            # 本关已由结算页直接证据确认并落账；仅重建下一关导航上下文。
            # 继续走下方进度更新，下一轮从已确认的下一节点开始。
            log(f"  ↻ {display_name}已通关；下一轮重新进入第{ch}章地图", "WARN")
            need_navigate = True
        if ok is False:
            if display_name.upper().startswith("H"):
                detail = f"{display_name}五份不同作业后仍未通关"
                _shelve_mainline_stage(display_name, detail)
                _set_mainline_run_status("running", f"{detail}，继续后续普通主线")
                ch += 1
                need_navigate = True
                continue
            detail = f"{display_name}五份不同作业后仍未通关并阻塞后续解锁"
            _record_decision_request(
                "普通主线阻塞关处理方案",
                f"{detail}，未执行任何资源关或难度替代",
                ["G-AUTH-001", "G-MAINLINE-001"],
                {"stage": display_name, "attempt_budget": 5},
            )
            log(f"⛔ {detail}", "ERROR")
            write_status("主线等待决策", f"{display_name} 已用尽5份不同作业")
            _set_mainline_run_status("blocked", detail)
            return False
        if ok == "imperfect":
            # 本轮五份作业已经用尽；不能让 while 再从进度文件读到同一
            # imperfect 节点并把作业清单清零后从第一份重新跑。
            detail = f"{display_name}五份不同作业后仍未完美"
            _shelve_mainline_stage(display_name, detail)
            if display_name.upper().startswith("H"):
                log(f"⏭ {detail}，继续后续普通主线", "WARN")
                _set_mainline_run_status("running", f"{detail}，继续后续普通主线")
                ch += 1
                need_navigate = True
                continue
            log(f"⏭ {detail}；该关已首通，继续本章后续关卡", "WARN")
            _set_mainline_run_status("running", f"{detail}；继续后续普通主线")
            continue
        
        # 结果处理 (update_progress在clear_stage内部已更新文件)
        prog = load_progress()
        prog["current"] = display_name
        save_progress(prog)
        _set_mainline_run_status("running", f"已处理{display_name}")
        wait(3)
    
    log(f"\n主线推进完成!")
    _set_mainline_run_status("completed", "已扫描到当前配置的最后章节")
    return True


def verify_mainline_completion(start_chapter=None):
    """主线推进完成后视觉确认: 截图验证体力消耗+关卡推进
    
    🔴 2026-06-30 用户要求: 不能脚本自己结束了就不管了
    必须回到章节地图, 截图确认:
    1. 体力确实花出去了 (理智减少)
    2. 关卡确实推进了 (六芒星填充状态)
    3. 如果验证失败, 记录警告但不阻塞cleanup
    """
    log("\n→ 主线视觉确认: 验证体力消耗和关卡推进...")
    
    # 1. 强制回到章节地图 (从当前任何界面)
    prog = load_progress()
    ch = start_chapter or 10
    for c in sorted(ALL_CHAPTERS.keys()):
        all_cleared = all(s[0] in prog.get("cleared", []) for s in ALL_CHAPTERS[c])
        if not all_cleared:
            ch = c
            break
    
    # 尝试回到章节地图 (最多15次)
    for i in range(15):
        state = get_state()
        if state == "chapter_map":
            log("  ✅ 已在章节地图")
            break
        if state == "main_menu":
            goto_chapter(ch)
            wait(3)
            continue
        if state in ("victory", "reward", "defeat"):
            tap(*POS_DISMISS)
            wait(2)
            continue
        if state == "story":
            skip_story()
            wait(3)
            continue
        if state == "formation":
            back()
            wait(2)
            continue
        if state == "stage_detail":
            back()
            wait(2)
            continue
        if state in ("exit_dialog", "announcement", "network_error"):
            handle_popups()
            wait(2)
            continue
        if state == "home_screen":
            log("  ⚠️ 在Android桌面, 游戏可能已关闭, 无法视觉确认")
            return {"ok": False, "reason": "游戏已关闭", "stamina_before": None, "stamina_after": None}
        wait(3)
    else:
        log("  ⚠️ 无法回到章节地图进行视觉确认")
        return {"ok": False, "reason": "无法回到章节地图", "stamina_before": None, "stamina_after": None}
    
    # 2. 截图验证当前关卡状态 (六芒星)
    p = shot("verify_mainline")
    text = ocr_text(p)
    
    # 3. 检查体力 (理智)
    stamina = get_stamina()
    
    # 4. 检查进度文件中的最新通关状态
    prog = load_progress()
    cleared = prog.get("cleared", [])
    last_cleared = None
    for c in sorted(ALL_CHAPTERS.keys()):
        for display, internal in ALL_CHAPTERS[c]:
            if display in cleared:
                last_cleared = display
    
    before = _MAINLINE_RUN_SNAPSHOT or {}
    before_cleared = set(before.get("cleared", []))
    before_imperfect = set(before.get("imperfect", []))
    after_cleared = set(prog.get("cleared", []))
    after_imperfect = set(prog.get("imperfect", []))
    newly_cleared = sorted(after_cleared - before_cleared)
    newly_imperfect = sorted(after_imperfect - before_imperfect)
    progressed = bool(newly_cleared or newly_imperfect)

    result = {
        "ok": progressed,
        "state": state,
        "stamina_after": stamina,
        "last_cleared": last_cleared,
        "cleared_count": len(cleared),
        "newly_cleared": newly_cleared,
        "newly_imperfect": newly_imperfect,
        "ocr_text_preview": text[:200] if text else "",
        "screenshot": p
    }
    
    log(f"  [视觉确认] 当前状态: {state}")
    log(f"  [视觉确认] 当前理智: {stamina}")
    log(f"  [视觉确认] 最新通关: {last_cleared}")
    log(f"  [视觉确认] 总通关数: {len(cleared)}")
    log(f"  [视觉确认] 本轮新增完美: {newly_cleared}")
    log(f"  [视觉确认] 本轮新增非完美: {newly_imperfect}")
    
    # 如果没有推进任何关卡, 警告
    if not progressed:
        log("  ⚠️ [视觉确认] 本轮没有检测到新增通关，不能判定主线推进成功", "WARN")
        result["ok"] = False
        result["reason"] = "本轮进度无变化"
    
    return result

# ============================================================
# 任务后清理: 关闭MAA、游戏和MuMu模拟器 (2026-06-28 用户要求)
# ============================================================

def check_and_clear_badges(claim_tasks=False):
    """cleanup前检查并清理任务/基建角标 (2026-07-08)
    
    流程: 先处理任务奖励(claim_daily_rewards) → 再处理基建待办 → 返回主界面
    在cleanup_after_task开头调用, 确保退出前所有待办已处理
    """
    log("→ 检查角标(任务/基建)...")
    
    # daily/full已由MAA Award收尾，默认禁止再点一次任务入口。
    if claim_tasks:
        claim_result = claim_daily_rewards()
        if claim_result.get("claimed"):
            log("  ✅ 任务奖励已领取")
    else:
        log("  [角标] 跳过重复任务领奖，仅检查基建")
    
    # 2. 处理基建待办 (基建角标=蓝色铃铛/红色数字)
    # 回主界面
    if get_state() != "main_menu":
        goto_main_menu()
        wait(2)
    
    # 点击基建按钮
    p = shot("main_for_base")
    items = ocr(p)
    base_pos = find_text(items, "基建") or find_text(items, "BASE")
    if not base_pos:
        log("  ⚠️ 未找到基建按钮, 跳过基建清理")
        return
    
    tap(*base_pos)
    log(f"  [基建] 点击进入 @{base_pos}")
    wait(3)
    
    # 检查基建页面是否有待办/通知/信赖
    p2 = shot("base_interior")
    t2 = ocr_text(p2)
    items2 = ocr(p2)
    
    # 检测信赖按钮(通常有红色数字角标)
    trust_pos = find_text(items2, "信赖") or find_text(items2, "干员信赖")
    if trust_pos and ("信赖" in t2 or "待办" in t2 or any(c.isdigit() for c in t2)):
        log(f"  [基建] 检测到信赖待办, 点击进入 @{trust_pos}")
        tap(*trust_pos)
        wait(3)
        
        # 信赖页面: 查找"一键信赖"或"全部收取"
        p3 = shot("trust_page")
        t3 = ocr_text(p3)
        items3 = ocr(p3)
        
        one_click = find_text(items3, "一键信赖") or find_text(items3, "全部收取") or find_text(items3, "全部")
        if one_click:
            tap(*one_click)
            log(f"  [基建] 点击一键信赖 @{one_click}")
            wait(5)
            # 处理可能的信赖提升弹窗
            for _ in range(3):
                p_d = shot("trust_dismiss")
                t_d = ocr_text(p_d)
                if "确定" in t_d or "提升" in t_d:
                    items_d = ocr(p_d)
                    ok_pos = find_text(items_d, "确定") or (1100, 780)
                    tap(*ok_pos)
                    wait(2)
                else:
                    break
            log("  ✅ 基建信赖已处理")
        else:
            log("  ℹ️ 信赖页面未找到一键信赖按钮")
    else:
        log("  ℹ️ 基建无待办事项")
    
    # 返回主界面
    goto_main_menu()
    wait(2)
    log("✅ 角标检查完成")


def cleanup_after_task(check_badges=True):
    """任务完成后关闭MAA+游戏+MuMu模拟器, 释放所有资源
    
    🔴 2026-06-28 用户要求: 模拟器窗口也要关闭, 不要留残窗
    🔴 2026-07-08 新增: cleanup前检查并清理任务/基建角标
    """
    import subprocess

    _close_maacore_screenshot_bridge()
    
    # 退出前检查角标；OCR/ADB失效不能阻止后续强制清理。
    if check_badges:
        try:
            check_and_clear_badges(claim_tasks=False)
        except Exception as e:
            log(f"  ⚠️ 角标检查失败但继续清理: {e}", "WARN")
    else:
        log("→ 本轮未执行日常收尾，跳过任务/基建角标检查")
    
    log("\n→ 任务完成, 开始清理 (关闭MAA+游戏+MuMu)")
    
    # 1. 关闭MAA
    try:
        r = subprocess.run(['taskkill', '/IM', 'MAA.exe', '/F'],
                         capture_output=True, timeout=10,
                         encoding='gbk', errors='replace')
        if r.returncode == 0:
            log("  ✅ MAA已关闭")
        else:
            remaining = _running_process_images(["MAA.exe"])
            if remaining:
                detail = (r.stderr or r.stdout or "").strip()
                log(f"  ❌ MAA关闭失败且仍在运行: {detail}", "ERROR")
            elif remaining == []:
                log("  ℹ️ MAA未运行 (无需关闭)")
            else:
                log("  ⚠️ MAA关闭命令失败，且进程状态无法核验", "WARN")
    except Exception as e:
        log(f"  ⚠️ 关闭MAA异常: {e}", "WARN")
    
    # 2. 关闭游戏 (adb force-stop, 如果ADB还连着)
    try:
        subprocess.run([ADB, "-s", DEVICE, "shell", "am", "force-stop", PKG],
                      capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        log("  ✅ 游戏已关闭")
    except Exception as e:
        log(f"  ℹ️ ADB不可用, 游戏随MuMu关闭 ({e})", "WARN")
    
    # 3. 关闭MuMu模拟器 (用户要求: 模拟器窗口也要关)
    # 🔴 2026-06-28修复: 之前只关MuMuNxDevice.exe, 漏关MuMuNxMain/Service/Player等
    # MuMu进程清单: MuMuPlayer(管理器) + MuMuNxMain(主窗口) + MuMuNxService(服务)
    #               + MuMuNxDevice(设备) + MuMuRemoteService(远程服务) + MuMuRemoteBackend(远程后端)
    mumu_closed = False
    # 方法1: mumu-cli shutdown (优雅关闭虚拟机实例)
    try:
        r = _run_mumu("control", "-v", MUMU_VM_INDEX, "shutdown", timeout=15)
        if r.returncode == 0:
            log("  ✅ MuMu模拟器已关闭(mumu-cli)")
            mumu_closed = True
    except Exception as e:
        log(f"  ⚠️ mumu-cli关闭异常: {e}", "WARN")

    # 优雅关闭后必须核对窗口/设备进程是否真的消失；返回码0不等于退出完成。
    # 这里只收尾本自动化使用的MuMu界面/设备，不停止可被其他实例共用的Windows服务。
    mumu_ui_processes = [
        "MuMuPlayer.exe",
        "MuMuNxMain.exe",
        "MuMuNxDevice.exe",
        "MuMuVMMHeadless.exe",
    ]
    remaining_mumu = None
    for attempt in range(10):
        wait(2)
        remaining_mumu = _running_process_images(mumu_ui_processes)
        if remaining_mumu == []:
            log("  ✅ MuMu窗口和设备进程已真实退出")
            break
        if remaining_mumu is None:
            break
        if attempt >= 2:
            for proc in remaining_mumu:
                subprocess.run(
                    ["taskkill", "/IM", proc, "/F"], capture_output=True, timeout=5,
                    encoding="gbk", errors="replace",
                )

    remaining_maa = _running_process_images(["MAA.exe"])
    cleanup_failures = []
    if remaining_maa:
        cleanup_failures.append("MAA.exe")
    if remaining_mumu:
        cleanup_failures.extend(remaining_mumu)

    # 默认不停止可能被其他MuMu实例共享的系统服务；用户要求关闭的游戏窗口、
    # MAA和当前模拟器实例仍必须全部消失。
    if not AGGRESSIVE_CLEANUP:
        stop_log_viewer()
        if cleanup_failures:
            raise RuntimeError(f"目标进程仍在运行: {', '.join(cleanup_failures)}")
        if remaining_maa is None or remaining_mumu is None:
            raise RuntimeError("进程状态无法核验，不能声称清理完成")
        _refresh_windows_taskbar("自动化清理完成")
        log("→ 清理完成（已关闭游戏/MAA/MuMu实例，未停止共享服务）")
        return

    # 方法2: 🔴 强制关闭所有MuMu进程 (无论mumu-cli是否成功, 都执行确保无残留)
    # 按依赖顺序关闭: 先关界面/主窗口, 再关服务
    mumu_processes = [
        "MuMuPlayer.exe",      # MuMu管理器界面
        "MuMuNxMain.exe",      # MuMu模拟器主窗口
        "MuMuNxDevice.exe",    # MuMu设备进程
        "MuMuVMMHeadless.exe", # MuMu虚拟机后台实例
        "MuMuNxService.exe",   # MuMu服务
    ]
    killed_any = False
    for proc in mumu_processes:
        try:
            r = subprocess.run(['taskkill', '/IM', proc, '/F'],
                             capture_output=True, timeout=5,
                             encoding='gbk', errors='replace')
            if r.returncode == 0:
                log(f"  ✅ {proc} 已强制关闭")
                killed_any = True
        except Exception:
            pass

    # 🔴 MuMuRemoteService是Windows服务, taskkill后会被SCM自动重启
    # 用 sc stop 停止服务 (不禁用, 下次启动MuMu时会自动恢复)
    # MuMuRemoteBackend不是服务, 直接taskkill即可
    try:
        subprocess.run(['sc', 'stop', 'MuMuRemoteService'],
                      capture_output=True, timeout=5,
                      encoding='gbk', errors='replace')
    except Exception:
        pass
    try:
        subprocess.run(['taskkill', '/IM', 'MuMuRemoteBackend.exe', '/F'],
                      capture_output=True, timeout=5,
                      encoding='gbk', errors='replace')
    except Exception:
        pass

    if killed_any or mumu_closed:
        mumu_closed = True

    # 4. 等待模拟器完全退出 (最多16s, 检查所有MuMu界面进程)
    import time as _time
    all_mumu_procs = ["MuMuPlayer.exe", "MuMuNxMain.exe", "MuMuNxDevice.exe", "MuMuNxService.exe",
                      "MuMuRemoteBackend.exe"]
    for attempt in range(8):
        _time.sleep(2)
        r = subprocess.run(['tasklist'],
                         capture_output=True, encoding='gbk', errors='replace', timeout=5,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        tasklist_output = r.stdout or ''
        remaining = [p for p in all_mumu_procs if p in tasklist_output]
        if not remaining:
            log("  ✅ MuMu进程已完全退出")
            break
        else:
            if attempt == 7:
                log(f"  ⚠️ MuMu进程仍在运行: {remaining} (可能需要手动关闭)", "WARN")
            else:
                # 还在退出中, 再强制kill一次
                for proc in remaining:
                    try:
                        subprocess.run(['taskkill', '/IM', proc, '/F'],
                                     capture_output=True, timeout=3,
                                     encoding='gbk', errors='replace')
                    except Exception:
                        pass

    stop_log_viewer()
    _refresh_windows_taskbar("自动化清理完成")
    log("→ 清理完成")

# ============================================================
# 执行报告 (用户2026-06-29要求: 每次执行完所有任务关闭游戏模拟器后, 报告今天干了什么)
# ============================================================

def claim_daily_rewards():
    """体力刷完后回到主页领取每日任务奖励
    
    🔴 2026-07-01 用户要求: 每日刷完体力后需要再回到主页把每日领取任务完全领取完成
    
    流程:
    1. 回主界面
    2. 点任务按钮进入任务页
    3. 检测"全部领取"按钮并点击
    4. 处理领取奖励弹窗(可能多个)
    5. 确认无红点后返回主界面
    
    Returns:
        dict: 领取结果
    """
    result = {"status": "unknown", "claimed": False, "items": []}
    log("→ 开始领取每日任务奖励...")
    
    # 1. 确保在主界面
    state = get_state()
    if state != "main_menu":
        log(f"  当前状态={state}, 回主界面...")
        if not goto_main_menu():
            log("  ❌ 无法回主界面, 跳过领取", "ERROR")
            result["status"] = "无法回主界面"
            return result
        wait(2)
    
    # 2. 截图主界面, 检测任务按钮是否有红点
    p = shot("main_before_claim")
    main_text = ocr_text(p)
    if "任务" not in main_text and "每日" not in main_text:
        log(f"  ⚠️ 主界面未识别到'任务'按钮, OCR: {main_text[:60]}")
        # 仍然尝试点击固定坐标
    
    # 3. 点击任务按钮进入任务页
    log(f"  点击任务按钮 {POS_TASK_BTN}")
    tap(*POS_TASK_BTN)
    wait(3)
    
    # 4. 截图任务页, 检测"领取"或"全部领取"按钮
    p = shot("task_page")
    task_text = ocr_text(p)
    items = ocr(p)
    
    log(f"  任务页OCR: {task_text[:80]}")

    # 必须先证明真的进入任务页。0713日志中固定坐标点击无效，代码却把主页当任务页，
    # 随后的back又弹出了退出游戏框。未进入时不再继续点击，也不执行back。
    task_page_markers = ["日常任务", "周常任务", "主线任务", "特勤任务"]
    if not any(k in task_text for k in task_page_markers):
        log("  ❌ 点击后未进入任务页，停止本次手动领奖（不回退、不误判已领取）", "ERROR")
        result["status"] = "任务入口未确认"
        return result
    
    # 5. 查找"全部领取"或"领取"按钮
    claim_pos = find_text(items, "全部领取") or find_text(items, "领取全部") or find_text(items, "领取")
    
    if not claim_pos:
        # 没有领取按钮, 可能任务都领完了
        log("  ℹ️ 未检测到'领取'按钮, 任务可能已全部领取")
        result["status"] = "无可领取奖励"
        # 返回主界面
        back()
        wait(2)
        return result
    
    # 6. 点击"全部领取"按钮
    log(f"  点击'全部领取' @{claim_pos}")
    tap(*claim_pos)
    wait(3)
    
    # 7. 处理领取奖励弹窗(可能有多个物品弹窗)
    for i in range(10):  # 最多处理10个弹窗
        p = shot(f"claim_{i}")
        text = ocr_text(p)
        
        # 检测奖励弹窗特征
        if "获得物资" in text or "至纯源石" in text or "合成玉" in text or "龙门币" in text:
            log(f"  [领取] 检测到奖励弹窗: {text[:40]}")
            result["items"].append(text[:40])
            # 点击"确定"或"确认"按钮
            items = ocr(p)
            confirm_pos = find_text(items, "确定") or find_text(items, "确认")
            if confirm_pos:
                tap(*confirm_pos)
                log(f"  [领取] 点击'确定' @{confirm_pos}")
            else:
                tap(*POS_DISMISS)
                log(f"  [领取] 点击空白关闭 @{POS_DISMISS}")
            wait(2)
        else:
            # 没有奖励弹窗了
            break
    
    # 8. 再次检测任务页是否还有红点/领取按钮
    wait(2)
    p = shot("task_after_claim")
    after_text = ocr_text(p)
    if "领取" in after_text:
        log(f"  ⚠️ 领取后仍有'领取'按钮, 可能还有未领奖励")
        # 再次尝试点击
        items = ocr(p)
        claim_pos2 = find_text(items, "全部领取") or find_text(items, "领取")
        if claim_pos2:
            tap(*claim_pos2)
            wait(2)
    
    # 9. 返回主界面
    back()
    wait(2)
    state = get_state()
    if state != "main_menu":
        goto_main_menu()
        wait(2)
    
    result["status"] = "领取完成"
    result["claimed"] = True
    log(f"  ✅ 每日任务奖励领取完成 (共{len(result['items'])}个弹窗)")
    return result

def verify_daily_completion():
    """MAA完成后截图验证日常是否真的清理 (用户2026-06-29要求)
    
    🔴 严格的真实性验证:
    - 不只信MAA日志, 必须截图+OCR交叉验证
    - 验证项: 主界面状态/任务页红点/基建入口/招募页/商店信用
    - 结果存入_LAST_VERIFICATION供报告使用
    
    Returns:
        dict: 各项验证结果
    """
    global _LAST_VERIFICATION
    result = {}

    log("→ 开始截图验证日常完成情况...")

    # 1. 验证当前是否在主界面
    try:
        state = get_state()
        result["当前状态"] = state
        if state != "main_menu":
            log(f"  ⚠️ 当前不在主界面(state={state}), 验证可能不准")
            # 尝试回主界面
            goto_main_menu()
            wait(2)
    except Exception as e:
        result["状态检测"] = f"异常: {e}"

    # 2. 截图主界面, OCR检查
    try:
        p = shot("verify_main")
        text = ocr_text(p)
        # 主界面特征词: 作战/基建/招募/商店/任务
        main_keywords = ["作战", "基建", "招募", "商店", "任务", "采购", "终端"]
        matched_main = sum(1 for k in main_keywords if k in text)
        result["主界面识别"] = f"匹配{matched_main}/{len(main_keywords)}个特征词"
        if matched_main >= 3:
            result["主界面确认"] = "✅ 在主界面"
        else:
            result["主界面确认"] = "⚠️ 可能不在主界面"
            log(f"  [验证] 主界面OCR: {text[:80]}")
    except Exception as e:
        result["主界面截图"] = f"异常: {e}"

    # 3. 验证任务页是否有未领取红点 (Award任务)
    # 明日方舟任务页入口: 主界面左侧"任务"按钮, 完成后有红点
    try:
        # 点任务按钮(左侧栏), 截图看有无"前往"或红点
        # 不主动点击避免干扰, 只在主界面截图分析
        # 实际验证靠MAA日志的TaskChainCompleted更可靠
        result["任务领取"] = "依赖MAA日志Award:TaskChainCompleted"
    except:
        pass

    # 4. 验证MAA日志中每个任务链的完成状态 (最可靠的验证)
    try:
        run_log = _get_current_maa_run_log()

        for chain in ["StartUp", "Fight", "Infrast", "Recruit", "Mall", "Award"]:
            status = _taskchain_status(run_log, chain)
            if status["ok"]:
                result[f"{chain}链"] = "✅ 完成"
            elif status["errored"]:
                result[f"{chain}链"] = "❌ 出错"
            elif status["started"]:
                result[f"{chain}链"] = "⚠️ 启动未完成"
            else:
                result[f"{chain}链"] = "⏸ 未执行"

        # AllTasksCompleted是最终判据
        if "AllTasksCompleted" in run_log:
            result["MAA最终状态"] = "✅ AllTasksCompleted"
        else:
            result["MAA最终状态"] = "⚠️ 未触发AllTasksCompleted"
    except Exception as e:
        result["日志验证"] = f"异常: {e}"

    # 5. 进程状态
    try:
        tl = _tasklist_snapshot()
        if "MAA.exe" not in tl:
            result["截图验证时MAA进程"] = "✅ 已关闭"
        else:
            result["截图验证时MAA进程"] = "ℹ️ 队列已结束，等待总清理关闭"
    except Exception as e:
        result["截图验证时MAA进程"] = f"⚠️ 无法核验: {e}"

    log(f"  [验证] 结果: {result}")
    _LAST_VERIFICATION = result
    return result

# ============================================================
# 完成通知 (用户2026-06-29要求: 任务完成后必须主动弹出通知, 不让用户追问)
# ============================================================


def push_to_phone(title, content):
    """通过 PushPlus 推送消息到手机微信 (非阻塞, 失败不影响主流程)"""
    if not PUSHPLUS_TOKEN:
        return
    try:
        import json as _json, urllib.request as _ur
        data = _json.dumps({"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "txt"})
        req = _ur.Request("http://www.pushplus.plus/send", data=data.encode(), 
                          headers={"Content-Type": "application/json"})
        resp = _ur.urlopen(req, timeout=5).read()
        log(f"  [手机推送] PushPlus: {resp.decode('utf-8')[:80]}...")
    except Exception as e:
        log(f"  [手机推送] 失败: {e}", "WARN")

_NOTIFY_SENT = type('obj', (object,), {'sent': False})()


def _load_priority_task_records():
    """读取关卡闭环结果。这里的 completed 必须由战后节点 ROI 验证写入。"""
    path = os.path.join(BASE, "outputs", "priority_tasks_0712.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        tasks = data.get("tasks", {})
        return tasks if isinstance(tasks, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log(f"  [通知] 读取关卡验证记录失败: {e}", "WARN")
        return {}


def _truthful_completion_summary(report):
    """只根据本次可核验的证据生成结论，不从历史进度或体力消耗推断成功。"""
    mode = report.get("mode", "unknown")
    chain_status = report.get("chain_status", {}) or {}
    intended_chains = report.get("intended_chains")
    if intended_chains is None:
        if mode in ("daily", "daily_rerun", "full"):
            intended_chains = ["StartUp", "Infrast", "Recruit", "Mall", "Award"]
        elif mode == "annihilation":
            intended_chains = ["StartUp", "Fight"]
        elif mode == "reclamation":
            # Reclamation is intentionally stopped at a cycle budget; it is not
            # expected to emit TaskChainCompleted/AllTasksCompleted.
            intended_chains = []
        else:
            intended_chains = []

    task_records = report.get("stage_task_records")
    if not isinstance(task_records, dict):
        task_records = _load_priority_task_records()
    intended_stages = report.get("intended_stages")
    game_day_mainline = report.get("game_day_mainline") or {}
    if intended_stages is None:
        # 普通日常弹窗不应把旧的章节专项记录冒充为本次结果。
        intended_stages = list(task_records) if mode in ("mainline", "chapter", "priority") else []

    stage_groups = {"completed": [], "running": [], "pending": [], "failed": [], "unknown": []}
    failure_states = {"failed", "error", "needs_retry", "blocked", "imperfect"}
    for stage in intended_stages:
        state = task_records.get(stage, {}) if isinstance(task_records.get(stage, {}), dict) else {}
        status = state.get("status", "unknown")
        if status == "completed":
            stage_groups["completed"].append(stage)
        elif status == "running":
            stage_groups["running"].append(stage)
        elif status in ("pending", "queued", "not_started"):
            stage_groups["pending"].append(stage)
        elif status in failure_states:
            stage_groups["failed"].append(stage)
        else:
            stage_groups["unknown"].append(stage)

    chain_groups = {"completed": [], "running": [], "failed": [], "not_run": []}
    for chain in intended_chains:
        state = chain_status.get(chain, {}) or {}
        if state.get("errored"):
            chain_groups["failed"].append(chain)
        elif state.get("completed") and state.get("ok", True):
            chain_groups["completed"].append(chain)
        elif state.get("started"):
            chain_groups["running"].append(chain)
        else:
            chain_groups["not_run"].append(chain)

    run_summary = report.get("run_summary") or {}
    run_success = []
    run_failed = []
    run_unconfirmed = []
    decision_requests = list(
        report.get("decision_requests") or run_summary.get("decision_requests") or []
    )
    flow_target = run_summary.get("flow_target") or {}
    ann = run_summary.get("annihilation") or {}
    if ann:
        if ann.get("status") == "completed_weekly":
            run_success.append(
                f"剿灭周进度{ann.get('jade_earned', '?')}/{ann.get('jade_max', '?')}"
            )
        elif ann.get("status") == "skipped_weekly_complete":
            pass
        elif ann.get("status") in ("failed", "error", "maa_start_failed", "incomplete_weekly"):
            run_failed.append("剿灭")
        else:
            run_unconfirmed.append("剿灭")
    reclamation = run_summary.get("reclamation") or {}
    if reclamation:
        reclamation_status = reclamation.get("status")
        if reclamation_status in (
            "completed", "completed_at_deadline", "completed_at_prosperity_cap",
        ):
            cycles = reclamation.get("completed_cycles", reclamation.get("target_cycles", "?"))
            suffix = {
                "completed_at_deadline": "（已按截止时间停止）",
                "completed_at_prosperity_cap": "（已达繁荣度上限）",
            }.get(reclamation_status, "")
            run_success.append(f"沙洲遗闻无存档刷繁荣点{cycles}轮{suffix}")
        elif reclamation_status in ("failed", "navigation_failed"):
            run_failed.append("沙洲遗闻生息演算")
        else:
            run_unconfirmed.append("沙洲遗闻生息演算")
    event_summary = run_summary.get("event") or {}
    if flow_target.get("type") == "event" and not event_summary:
        run_unconfirmed.append(f"活动{flow_target.get('name', '')}未产生执行记录")
    navigation = event_summary.get("navigation") or {}
    if navigation:
        if navigation.get("status") == "failed":
            run_failed.append("活动导航")
        elif navigation.get("status") != "verified":
            run_unconfirmed.append("活动导航")
    event_stages = event_summary.get("stages") or {}
    for stage, state in event_stages.items():
        status = (state or {}).get("status")
        modes = (state or {}).get("modes") or {}
        if not modes:
            if status == "cleared":
                run_success.append(stage)
            elif status in (
                "failed", "imperfect", "locked", "challenge_locked",
                "challenge_unavailable", "no_job", "maa_control_failed", "stamina", "error",
            ):
                run_failed.append(stage)
            else:
                run_unconfirmed.append(stage)
            continue
        for mode, label in (("normal", "普通"), ("challenge", "突袭")):
            if mode not in modes:
                continue
            mode_status = (modes.get(mode) or {}).get("status")
            item = f"{stage}{label}"
            if mode_status == "cleared":
                run_success.append(item)
            elif mode_status in (
                "failed", "imperfect", "locked", "challenge_locked",
                "challenge_unavailable", "no_job", "maa_control_failed", "stamina", "error",
            ):
                run_failed.append(item)
            else:
                run_unconfirmed.append(item)
    farm = event_summary.get("farm") or {}
    if farm:
        farm_label = f"{farm.get('stage', '活动关')}速刷"
        if farm.get("status") == "completed":
            run_success.append(farm_label)
        elif farm.get("status") in ("failed", "error", "maa_start_failed"):
            run_failed.append(farm_label)
        else:
            run_unconfirmed.append(farm_label)
    elif flow_target.get("type") == "event":
        run_unconfirmed.append("活动连续代理未执行")
    pending_challenges = (
        (event_summary.get("task_replay") or {}).get("pending_required_challenges") or []
    )
    for item in pending_challenges:
        stage = item.get("stage", "活动突袭")
        reason = item.get("reason") or "未闭环"
        if reason == "today_retry_budget_exhausted":
            reason = "本游戏日不同作业重试预算已耗尽"
        run_unconfirmed.append(f"{stage}突袭待补（{reason}）")
    historical_event_failures = []
    event_progress = report.get("event_progress") or {}
    for event_name, event_record in (event_progress.get("events") or {}).items():
        for stage, stage_record in ((event_record or {}).get("stages") or {}).items():
            for mode, mode_record in ((stage_record or {}).get("modes") or {}).items():
                if (mode_record or {}).get("status") not in failure_states:
                    continue
                mode_label = {"normal": "普通", "challenge": "突袭"}.get(mode, mode)
                historical_event_failures.append(f"{event_name} {stage}{mode_label}")
    if historical_event_failures:
        run_failed.append(
            "历史活动未闭环（当前可能已结束）：" + "、".join(historical_event_failures)
        )
    mainline = run_summary.get("mainline") or {}
    if flow_target.get("type") == "mainline" or (
        report.get("mode") in ("mainline", "chapter17_sandbox") and mainline
    ):
        mainline_status = mainline.get("status")
        progressed_stages = list(mainline.get("newly_cleared") or []) + list(mainline.get("newly_imperfect") or [])
        if progressed_stages:
            run_success.append(f"主线推进{','.join(progressed_stages)}")
        if mainline_status in ("navigation_failed", "failed", "blocked"):
            run_failed.append(f"主线{mainline.get('detail') or mainline_status}")
        elif mainline_status == "stamina_exhausted":
            run_success.append("主线已运行至理智不足")
        elif mainline_status == "completed" and not progressed_stages:
            if mainline.get("starting_target") or mainline.get("next_target"):
                run_unconfirmed.append("主线本轮未推进关卡")
            else:
                run_success.append("主线已扫描至当前配置末端，无待推进关卡")
        elif mainline_status not in ("completed", "running"):
            run_unconfirmed.append(f"主线状态{mainline_status or '未记录'}")
        remaining_sanity_use = run_summary.get("remaining_sanity_use") or {}
        if remaining_sanity_use:
            if remaining_sanity_use.get("status") == "completed":
                run_success.append(f"剩余理智用于{remaining_sanity_use.get('stage', '资源关')}")
            elif remaining_sanity_use.get("status") == "failed":
                run_failed.append("剩余理智刷取失败")
    flow_control = run_summary.get("flow_control") or {}
    if flow_control.get("status") == "paused":
        run_failed.append(f"流程已暂停：{flow_control.get('reason', '未说明原因')}")
    elif flow_control.get("status") == "decision_required":
        run_unconfirmed.append(f"流程等待决定：{flow_control.get('reason', '未说明原因')}")
    stamina_control = run_summary.get("stamina_flow_control") or {}
    if stamina_control.get("status") == "blocked":
        run_failed.append(
            f"理智流程已冻结：{stamina_control.get('reason', '未说明原因')}"
        )
    same_day_security = report.get("game_day_security") or {}
    if same_day_security.get("reward_capped") is True:
        counts = same_day_security.get("reward_counts") or {}
        run_success.append(
            f"保全派驻奖励已封顶{counts.get('strip')}/60、{counts.get('device')}/24"
        )
    security = run_summary.get("security") or {}
    if security:
        security_status = security.get("status")
        if security_status != "completed":
            counts = security.get("reward_counts") or {}
            reason = security.get("reason") or security_status or "状态未确认"
            run_failed.append(
                "保全派驻奖励未闭环"
                f"（{counts.get('strip', '未确认')}/60、"
                f"{counts.get('device', '未确认')}/24；{reason}）"
            )
    same_day_chapter17 = report.get("game_day_chapter17") or {}
    if same_day_chapter17.get("status") == "completed":
        stages = "、".join(same_day_chapter17.get("stages") or [])
        cost = int(same_day_chapter17.get("sanity_consumed", 0) or 0)
        cost_note = f"（险地消耗{cost}理智，沙盘0理智）" if cost else ""
        run_success.append(f"17章{stages}险地作战与沙盘推演均完成{cost_note}")
    unspent_stamina = report.get("unspent_stamina") or {}
    if unspent_stamina:
        run_unconfirmed.append(
            f"收尾仍有{unspent_stamina.get('balance')}/210理智；"
            f"{unspent_stamina.get('reason', '尚未用完')}"
        )
    prior_incomplete = report.get("same_day_prior_incomplete_flow") or {}
    if prior_incomplete:
        if prior_incomplete.get("recovered_by_current_daily_tail") is True:
            resolved = prior_incomplete.get("resolved_chains") or []
            resolved_text = "、".join(resolved) if resolved else "缺失日常任务链"
            run_success.append(f"已补齐同日较早流程的{resolved_text}")
        else:
            prior_stamina = prior_incomplete.get("stamina_flow_control") or {}
            prior_flow = prior_incomplete.get("flow_control") or {}
            prior_security = prior_incomplete.get("security") or {}
            prior_reason = (
                prior_stamina.get("reason")
                or (
                    "保全派驻未闭环："
                    + str(prior_security.get("reason") or prior_security.get("status"))
                    if prior_security and prior_security.get("status") != "completed"
                    else ""
                )
                or prior_flow.get("reason")
                or "同日较早的完整自动化流程未闭环"
            )
            prior_final_stamina = prior_incomplete.get("final_stamina")
            stamina_suffix = (
                f"，当时收尾理智{prior_final_stamina}/210"
                if isinstance(prior_final_stamina, int)
                else ""
            )
            run_failed.append(
                f"同日日常补跑后仍有较早流程未闭环：{prior_reason}{stamina_suffix}"
            )
    if report.get("all_cleaned") is False:
        remaining = list((report.get("processes_remaining") or {}).keys())
        detail = "、".join(remaining) if remaining else "状态未确认"
        run_failed.append(f"进程清理未完成（{detail}）")

    has_success = bool(stage_groups["completed"] or chain_groups["completed"] or run_success)
    has_failure = bool(stage_groups["failed"] or chain_groups["failed"] or run_failed or report.get("has_error"))
    has_unconfirmed = bool(
        stage_groups["running"] or stage_groups["pending"] or stage_groups["unknown"]
        or chain_groups["running"] or chain_groups["not_run"] or run_unconfirmed
        or decision_requests
    )
    has_intended = bool(intended_stages or intended_chains or run_summary)
    if has_failure:
        outcome = "partial" if has_success else "attention"
    elif has_unconfirmed:
        outcome = "partial" if has_success else "unconfirmed"
    elif has_intended and has_success:
        outcome = "verified"
    else:
        outcome = "unconfirmed"

    titles = {
        "verified": "明日方舟自动化完成（已验证）",
        "partial": "明日方舟自动化部分完成",
        "attention": "明日方舟自动化需要处理",
        "unconfirmed": "明日方舟自动化结果未确认",
    }
    lines = [titles[outcome]]
    date_str = report.get("date", "")
    time_str = report.get("generated_at", "")
    if date_str or time_str:
        lines.append(f"时间: {date_str} {time_str}".rstrip())

    if intended_stages:
        lines.append("")
        lines.append("今日主线推进（作业执行 + 地图节点复核）:")
        if stage_groups["completed"]:
            lines.append(f"  已确认完美: {', '.join(stage_groups['completed'])}")
        if stage_groups["running"]:
            lines.append(f"  仍在运行: {', '.join(stage_groups['running'])}")
        if stage_groups["pending"]:
            lines.append(f"  尚未执行: {', '.join(stage_groups['pending'])}")
        if stage_groups["failed"]:
            lines.append(f"  未完成/需处理: {', '.join(stage_groups['failed'])}")
        if stage_groups["unknown"]:
            lines.append(f"  无可靠结果: {', '.join(stage_groups['unknown'])}")
        for stage in intended_stages:
            state = task_records.get(stage, {}) if isinstance(task_records.get(stage, {}), dict) else {}
            attempt_count = int(state.get("attempt_count", 0) or 0)
            outcomes = state.get("outcome_counts") or {}
            leaked = int(outcomes.get("leaked", 0) or 0)
            if attempt_count:
                if leaked == attempt_count:
                    lines.append(
                        f"  {stage}实测: 已换{attempt_count}份不同作业，"
                        f"{leaked}份均漏怪并立即止损，未通关"
                    )
                else:
                    lines.append(f"  {stage}实测: 已运行{attempt_count}份不同作业，结果未通关")
            detail = str(state.get("detail") or "").strip()
            if detail and (not attempt_count or detail not in (f"{attempt_count}份不同作业后仍未通关",)):
                lines.append(f"  原因/证据: {detail}")
            blocked_next = state.get("blocked_next_stage")
            if blocked_next:
                lines.append(f"  后续影响: {blocked_next}尚未解锁，主线仍停在{stage}")

    if intended_chains:
        lines.append("")
        lines.append("今日日常任务链（同一游戏日直接证据）:")
        chain_labels = {
            "StartUp": "启动/签到",
            "Infrast": "基建换班",
            "Recruit": "公开招募",
            "Mall": "信用商店",
            "Award": "任务奖励领取",
            "Fight": "理智作战",
            "Reclamation": "生息演算",
        }
        show_chains = lambda names: ", ".join(chain_labels.get(name, name) for name in names)
        if chain_groups["completed"]:
            lines.append(f"  已完成: {show_chains(chain_groups['completed'])}")
        if chain_groups["running"]:
            lines.append(f"  启动但未结束: {show_chains(chain_groups['running'])}")
        if chain_groups["failed"]:
            lines.append(f"  报错: {show_chains(chain_groups['failed'])}")
        if chain_groups["not_run"]:
            lines.append(f"  本次未执行/无证据: {show_chains(chain_groups['not_run'])}")

    if run_summary or run_success or run_failed or run_unconfirmed:
        lines.append("")
        lines.append("专项流程与收尾（仅列本轮闭环证据）:")
        if run_success:
            lines.append(f"  已确认: {', '.join(run_success)}")
        if run_failed:
            lines.append(f"  未完成/需处理: {', '.join(run_failed)}")
        if run_unconfirmed:
            lines.append(f"  尚无最终证据: {', '.join(run_unconfirmed)}")
        if farm:
            lines.append(
                f"  速刷结果: {farm.get('stage')}真实{farm.get('actual_runs', 0)}次，"
                f"请求上限={farm.get('requested_runs')}，连续代理={farm.get('series')}，"
                f"消耗理智={farm.get('sanity_consumed', '未识别')}"
            )

    if decision_requests:
        lines.append("")
        lines.append("待你确认（建议尚未执行）:")
        for request in decision_requests:
            action = request.get("action") or "未命名建议"
            reason = request.get("reason") or "未说明原因"
            lines.append(f"  - {action}: {reason}")

    game_day_activity = report.get("game_day_activity") or {}
    game_day_replay = report.get("game_day_event_replay") or {}
    game_day_annihilation = report.get("game_day_annihilation") or {}
    if game_day_annihilation:
        lines.append("")
        lines.append("今日剿灭（同一游戏日直接证据）:")
        lines.append(
            f"  剿灭委托{game_day_annihilation.get('runs')}次，"
            f"消耗{game_day_annihilation.get('sanity_consumed')}理智，"
            f"合成玉{game_day_annihilation.get('jade_earned')}/"
            f"{game_day_annihilation.get('jade_max')}"
        )
    if game_day_replay:
        stage_names = [item.get("stage") for item in game_day_replay.get("stages", [])]
        lines.append("")
        lines.append("今日复刻任务重打（同一游戏日直接证据）:")
        lines.append(
            f"  已完成{game_day_replay.get('completed_count')}项: "
            f"{', '.join(stage_names)}；"
            f"另有{game_day_replay.get('failed_runs', 0)}次失败作业实际扣理智；"
            f"合计消耗{game_day_replay.get('sanity_consumed')}理智"
        )
    if game_day_activity:
        lines.append("")
        lines.append("今日体力用途（同一游戏日直接证据）:")
        lines.append(
            f"  {game_day_activity.get('stage')} 连续代理 "
            f"{game_day_activity.get('runs')}次 × {game_day_activity.get('sanity_cost_each')}理智"
            f" = 消耗{game_day_activity.get('sanity_consumed')}理智"
        )

    mainline_stages = (game_day_mainline.get("stages") or {}) if game_day_mainline else {}
    failed_mainline_attempts = [
        (stage, state) for stage, state in mainline_stages.items()
        if isinstance(state, dict)
        and int(state.get("attempt_count", 0) or 0) > 0
        and state.get("status") in ("failed", "blocked", "imperfect")
    ]
    if failed_mainline_attempts and not game_day_activity:
        lines.append("")
        lines.append("今日理智用途（同一游戏日直接证据）:")
        for stage, state in failed_mainline_attempts:
            attempts = int(state.get("attempt_count", 0) or 0)
            lines.append(
                f"  用于尝试主线{stage}（{attempts}份不同作业均未通关；"
                "没有成功通关理智消耗证据）"
            )

    sanity = report.get("sanity") or {}
    final_stamina = report.get("final_stamina")
    if isinstance(final_stamina, int):
        lines.append("")
        if game_day_activity and final_stamina < int(game_day_activity.get("sanity_cost_each", 0) or 0):
            stamina_note = f"（已不足一次{game_day_activity.get('stage', '目标关')}）"
        else:
            stamina_note = ""
        lines.append(f"最终理智: {final_stamina}/210{stamina_note}")
    elif sanity.get("first") is not None and sanity.get("last") is not None:
        lines.append("")
        lines.append(f"理智记录: {sanity['first']} -> {sanity['last']}（消耗 {sanity.get('consumed', 0)}）")
    elif sanity.get("consumed"):
        lines.append("")
        lines.append(f"理智: 日志估算消耗 {sanity['consumed']}（未读取到首尾值）")
    else:
        lines.append("")
        lines.append("理智: 未确认（不据此判断任务成败）")

    lines.append("")
    if report.get("all_cleaned") is True:
        lines.append("收尾: 游戏、MAA、MuMu和实时日志窗均已关闭；仅保留本结果弹窗。")
    else:
        remaining = "、".join((report.get("processes_remaining") or {}).keys()) or "状态无法确认"
        lines.append(f"收尾: 未完成，仍有残留或无法确认：{remaining}。")

    conclusions = {
        "verified": "结论: 本次计划内项目均有完成证据。",
        "partial": "结论: 仅上面列出的项目已确认，其余不能算完成。",
        "attention": "结论: 本次没有可确认的完整成果，请查看失败项。",
        "unconfirmed": "结论: 没有足够证据证明本次任务已完成。",
    }
    lines.extend(["", conclusions[outcome]])
    return titles[outcome], "\n".join(lines), outcome


def notify_verified_stage_summary(stages, mode="chapter"):
    """章节专项运行结束时使用，避免把不在本次计划内的历史记录算进去。"""
    now = datetime.now()
    report = {
        "date": now.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%H:%M:%S"),
        "mode": mode,
        "intended_stages": list(stages),
        "intended_chains": [],
        "stage_task_records": _load_priority_task_records(),
    }
    notify_completion(report)


def _close_existing_summary_popups(silent=False):
    """关闭所有旧版/新版结果弹窗，避免多轮运行后堆叠多个MessageBox。"""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    WM_CLOSE = 0x0010
    closed = []
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc_type
    def enum_proc(hwnd, _lparam):
        try:
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            # 覆盖旧版“完成”、新版“部分完成/需要处理/结果未确认”等全部标题。
            if title.startswith("明日方舟自动化"):
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                closed.append(title)
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(enum_proc, 0)
    except Exception as e:
        log(f"  [通知] 枚举旧弹窗失败: {e}", "WARN")
    if closed and not silent:
        log(f"  [通知] 已关闭{len(closed)}个旧结果弹窗")
    if closed:
        wait(0.5)
    return len(closed)

def notify_completion(report=None, final=False):
    """弹出最终通知；只有总控收尾或显式查看报告可以传final=True。"""
    global _NOTIFY_SENT
    if not final:
        log("  [通知] 非最终流程无弹窗权限，仅保留报告", "WARN")
        return
    if getattr(_NOTIFY_SENT, 'sent', False):
        log("  [通知] 本次进程已弹过, 跳过")
        return
    _NOTIFY_SENT.sent = True
    """任务完成后主动弹出Windows通知 + 手机推送"""
    import ctypes

    # 构造通知内容
    if report is None:
        report = {}

    date_str = report.get("date", "")
    time_str = report.get("generated_at", "")
    from special_run_reporting_v1 import (
        is_special_report, special_completion_summary, completion_marker_path,
    )
    if is_special_report(report):
        title, msg, outcome = special_completion_summary(report)
    else:
        title, msg, outcome = _truthful_completion_summary(report)

    # 写入一个完成标记文件 (供外部检测)
    try:
        done_path = completion_marker_path(BASE, report)
        with open(done_path, 'w', encoding='utf-8') as f:
            f.write(f"{date_str} {time_str}\n{report.get('mode', 'unknown')}\n{outcome.upper()}\n")
    except:
        pass

    # 在独立pythonw进程中显示结果。主自动化进程可正常退出，弹窗仍保留供事后查看。
    try:
        # 第一层：直接按窗口标题关闭所有历史弹窗，兼容没有PID记录的旧版本。
        _close_existing_summary_popups()
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        popup_pid_path = os.path.join(BASE, "outputs", "summary_popup.pid")
        popup_payload_path = os.path.join(BASE, "outputs", "summary_popup_payload.json")
        popup_error_path = os.path.splitext(popup_payload_path)[0] + ".error.log"
        try:
            if os.path.exists(popup_pid_path):
                old_pid = int(open(popup_pid_path, "r", encoding="ascii").read().strip())
                subprocess.run(
                    ["taskkill", "/PID", str(old_pid), "/F"],
                    capture_output=True,
                    timeout=5,
                )
        except Exception:
            pass
        _atomic_write_json(
            popup_payload_path,
            {"title": title, "message": msg, "generated_at": datetime.now().isoformat()},
        )
        try:
            if os.path.exists(popup_error_path):
                os.unlink(popup_error_path)
        except OSError:
            pass
        popup_proc = subprocess.Popen(
            [pythonw, os.path.join(SCRIPT_DIR, "show_summary_popup.py"), popup_payload_path],
            cwd=SCRIPT_DIR,
            creationflags=(
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            ),
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with open(popup_pid_path, "w", encoding="ascii") as f:
            f.write(str(popup_proc.pid))
        wait(0.8)
        if popup_proc.poll() is not None:
            error_detail = ""
            if os.path.exists(popup_error_path):
                try:
                    error_detail = open(popup_error_path, "r", encoding="utf-8").read()[-500:]
                except OSError:
                    pass
            raise RuntimeError(
                f"结果弹窗子进程提前退出(code={popup_proc.returncode}) {error_detail}"
            )
        if is_special_report(report):
            log("  [通知] 专项结果弹窗已启动；专项回执与每日报告分别核验")
        else:
            log("  [通知] 已确认结果弹窗子进程存活 (报告见 outputs/daily_report_*.md)")
    except Exception as e:
        _NOTIFY_SENT.sent = False
        log(f"  [通知] MessageBox失败: {e}", "WARN")

    # 自动打开.md报告 (已禁用: 用户系统无Markdown阅读器,会触发MarkdownPad安装弹窗)
    # 报告文件已保存到 outputs/daily_report_YYYY-MM-DD.md, 请手动查看
    # try:
    #     from datetime import datetime as _dt
    #     md_path = os.path.join(BASE, "outputs", f"daily_report_{_dt.now().strftime('%Y-%m-%d')}.md")
    #     if os.path.exists(md_path):
    #         os.startfile(md_path)
    # except Exception as e:
    #     log(f"  [通知] 打开报告失败: {e}", "WARN")

    # 手机推送 (非阻塞, token为空则跳过)
    push_to_phone(title, msg)
    
def generate_security_report():
    """生成独立保全派驻报告，不读写或合并每日自动化总账。"""
    now = datetime.now()
    security = deepcopy(_RUN_SUMMARY.get("security") or {})
    process_check_error = None
    remaining = {}
    try:
        snapshot = _tasklist_snapshot()
        for label, process_name in (
            ("MAA", "MAA.exe"),
            ("MuMu主窗口", "MuMuNxMain.exe"),
            ("MuMu设备", "MuMuNxDevice.exe"),
            ("MuMu管理器", "MuMuPlayer.exe"),
        ):
            if process_name in snapshot:
                remaining[label] = True
        if os.path.exists(os.path.join(BASE, "outputs", "log_viewer.pid")):
            remaining["实时日志窗"] = True
    except Exception as exc:
        process_check_error = str(exc)
        remaining = {"状态检查失败": True}

    report = {
        "date": now.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%H:%M:%S"),
        "mode": "security",
        "security": security,
        "run_summary": deepcopy(_RUN_SUMMARY),
        "all_cleaned": not any(remaining.values()),
        "processes_remaining": remaining,
        "process_check_error": process_check_error,
        "workflow_completed": security.get("status") == "completed" and not any(remaining.values()),
    }
    stem = f"security_report_{now:%Y-%m-%d_%H%M%S}"
    json_path = os.path.join(BASE, "outputs", f"{stem}.json")
    md_path = os.path.join(BASE, "outputs", f"{stem}.md")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    active = security.get("active_regions") or []
    completed = security.get("completed_regions") or []
    blocked = security.get("blocked_regions") or []
    lines = [
        "# 明日方舟保全派驻执行报告",
        "",
        f"- 区域期：{security.get('period') or '未确认'}",
        f"- 奖励周期：{security.get('reward_cycle') or '未确认'}",
        f"- 数据增补条：{(security.get('reward_counts') or {}).get('strip', '未确认')}/60",
        f"- 数据增补仪：{(security.get('reward_counts') or {}).get('device', '未确认')}/24",
        f"- 本次有效完整清理：{security.get('successful_clears', 0)}轮",
        f"- 本期平台：{', '.join(active) if active else '未确认'}",
        f"- 已完成：{', '.join(completed) if completed else '无直接完成证据'}",
        f"- 状态：{security.get('status') or 'unknown'}",
    ]
    for item in blocked:
        lines.append(f"- 未完成：{item.get('region')}（{item.get('reason')}）")
    lines.extend([
        f"- 相关进程已清理：{'是' if report['all_cleaned'] else '否'}",
        "",
        "只有游戏结算/全权委托与当前页面证据闭环的平台才计入已完成。",
    ])
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    report["json_path"] = json_path
    report["md_path"] = md_path
    return report


def generate_daily_report(mode="unknown"):
    """生成每日执行报告 (人类可读中文叙述 + JSON结构化数据)
    
    🔴 2026-06-29 严格验证重写:
    - 只解析本次run的日志 (从_LAST_MAA_RUN_START_LINE开始)
    - 每个任务链必须有 TaskChainCompleted 才算真完成 (不只是出现taskchain字段)
    - 输出 .md 人类可读报告 (中文叙述)
    - 输出 .json 结构化数据
    - 包含截图验证结果 (_LAST_VERIFICATION)
    """
    import re as _re
    from datetime import datetime as _dt

    global _LAST_MAA_RUN_START_LINE, _LAST_VERIFICATION

    now = _dt.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    prior_incomplete_full_report = None
    if mode in ("daily", "daily_rerun"):
        prior_path = os.path.join(BASE, "outputs", f"daily_report_{date_str}.json")
        try:
            with open(prior_path, "r", encoding="utf-8") as f:
                prior_candidate = json.load(f)
            if (
                prior_candidate.get("mode") in ("full", "event_today")
                and prior_candidate.get("workflow_completed") is not True
            ):
                prior_incomplete_full_report = prior_candidate
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            prior_incomplete_full_report = None

    # 1. 读取本次run的MAA日志 (只看新增部分!)
    maa_content = ""
    try:
        maa_content = _get_current_maa_run_log()
        # 🔴 防御检查G06: 确认使用了_LAST_MAA_RUN_START_LINE
        _guard_check("G06", context="generate_daily_report使用本次run日志边界",
                     condition=bool(maa_content),
                     expected="本轮MAA日志快照非空",
                     actual=f"chars={len(maa_content)}, start={_LAST_MAA_RUN_START_LINE}")
    except Exception as e:
        maa_content = ""

    # 2. 严格解析任务链状态 (TaskChainStart + TaskChainCompleted 配对)
    chain_status = {}
    report_chains = ["StartUp", "Fight", "Infrast", "Recruit", "Mall", "Award", "Reclamation"]
    for chain in report_chains:
        chain_status[chain] = _taskchain_status(maa_content, chain)

    maa_queue_completed = "AllTasksCompleted" in maa_content
    recovered_daily = None
    flow_was_paused = ((_RUN_SUMMARY.get("flow_control") or {}).get("status") == "paused")
    # 最终弹窗是“同一游戏日总账”，不受最后一个接管进程的mode限制。
    # 例如日常由full完成、主线由独立mainline接管，mainline弹窗也必须补回
    # 早先五条日常的直接完成证据。
    if not flow_was_paused:
        required_daily = ("StartUp", "Infrast", "Recruit", "Mall", "Award")
        if not all(chain_status[name]["ok"] for name in required_daily):
            try:
                with open(MAA_GUI_LOG, "r", encoding="utf-8") as f:
                    recovered_daily = _parse_completed_daily_gui_log(f.read(), now=now)
            except Exception:
                recovered_daily = None
            if recovered_daily:
                synthetic = []
                for name in recovered_daily["chains"]:
                    synthetic.append(f'TaskChainStart {{"taskchain":"{name}"}}')
                    synthetic.append(f'TaskChainCompleted {{"taskchain":"{name}"}}')
                synthetic.append('AllTasksCompleted {"taskchain":"Award"}')
                recovered_text = "\n".join(synthetic)
                for name in recovered_daily["chains"]:
                    chain_status[name] = _taskchain_status(recovered_text, name)
                maa_queue_completed = True
    # 只把最后终态仍失败的链算作未解决错误；补跑成功可覆盖首轮失败。
    has_any_error = any(state["errored"] for state in chain_status.values())

    # 3. 理智变化 (本次run)
    sanity_info = None
    sanity_matches = _re.findall(r'Current Sanity: (\d+) , Max Sanity: (\d+)', maa_content)
    if sanity_matches:
        sanity_info = {
            "first": int(sanity_matches[0][0]),
            "last": int(sanity_matches[-1][0]),
            "max": int(sanity_matches[0][1]),
            "consumed": int(sanity_matches[0][0]) - int(sanity_matches[-1][0]),
        }
    
    # 3b. 从脚本日志解析理智消耗 (主线模式Copilot战斗MAA日志不记录)
    script_sanity_info = None
    script_content = ""
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            script_content = f.read()
        script_stamina_matches = _re.findall(
            r'\[STAMINA\] (?:战斗|险地作战|沙盘推演): ([^,]+), 消耗: (\d+)',
            script_content,
        )
        if script_stamina_matches:
            total_script_cost = sum(int(m[1]) for m in script_stamina_matches)
            script_sanity_info = {
                "consumed": total_script_cost,
                "fights": len(script_stamina_matches),
                "stages": [m[0] for m in script_stamina_matches],
            }
    except Exception as e:
        pass
    
    # 合并理智信息: MAA日志优先, 脚本日志补充
    if sanity_info is None and script_sanity_info is not None:
        sanity_info = {
            "first": None,
            "last": None,
            "max": 210,
            "consumed": script_sanity_info["consumed"],
            "fights": script_sanity_info["fights"],
            "stages": script_sanity_info["stages"],
        }
    elif sanity_info is not None and script_sanity_info is not None:
        # MAA日志 + 脚本日志都有: 合并(取较大值)
        sanity_info["consumed"] = max(sanity_info.get("consumed", 0), script_sanity_info["consumed"])
        sanity_info["fights"] = script_sanity_info["fights"]
        sanity_info["stages"] = script_sanity_info["stages"]

    # 4. 战斗次数和理智消耗 (Fight任务)
    fight_info = None
    fight_evidence = _parse_fight_times_evidence(maa_content)
    if fight_evidence:
        fight_info = {
            "fights": fight_evidence["runs"],
            "total_cost": fight_evidence["sanity_cost"],
            "times_finished": fight_evidence["runs"],
            "series_batches": fight_evidence["series_batches"],
        }

    # Fight and final daily are intentionally separate processes so the idle
    # MAA instance can be restarted and reload its restored task queue.  Carry
    # the directly observed Fight result across that boundary; otherwise the
    # final popup would truthfully see only the daily queue but misleadingly
    # claim that stamina usage was unconfirmed.
    fight_handoff = _load_fight_handoff(now)
    if fight_handoff and mode in ("daily", "daily_rerun", "full", "event_today"):
        fight_info = {
            "fights": int(fight_handoff.get("runs", 0) or 0),
            "total_cost": int(fight_handoff.get("sanity_consumed", 0) or 0),
            "times_finished": int(fight_handoff.get("runs", 0) or 0),
            "series_batches": list(fight_handoff.get("series_batches") or []),
            "stage": fight_handoff.get("stage"),
            "evidence": fight_handoff.get("evidence"),
        }
        sanity_info = {
            "first": fight_handoff.get("sanity_first"),
            "last": fight_handoff.get("sanity_last"),
            "max": 210,
            "consumed": int(fight_handoff.get("sanity_consumed", 0) or 0),
            "fights": int(fight_handoff.get("runs", 0) or 0),
            "stages": [fight_handoff.get("stage")],
        }

    # 点名主线/H关由Copilot执行，MAA没有FightTimes，但脚本已有本轮真实
    # STAMINA记录。必须先把它写入本轮fight；否则后面的同游戏日17章旧汇总
    # 会填充fight_info，把本轮H关10理智错误显示成较早险地的21理智。
    if fight_info is None and script_sanity_info is not None:
        fight_info = {
            "fights": script_sanity_info["fights"],
            "total_cost": script_sanity_info["consumed"],
            "times_finished": script_sanity_info["fights"],
            "series_batches": [],
            "stage": ",".join(script_sanity_info["stages"]),
            "evidence": "本轮主线Copilot的STAMINA直接日志",
        }

    # 5. 掉落物品 (本次run)。StageDrops同时包含累计drops和带增量的stats，
    # 只能汇总stats.addQuantity，否则多批连续代理会把前一批重复计算。
    drops_list = _parse_stage_drops_evidence(maa_content)

    # 6. 剿灭信息 (本次run)
    ann_info = None
    ann = _re.findall(r'annihilation_weekly_process":\[(\d+),(\d+)\]', maa_content)
    if ann:
        ann_info = {"jade_earned": int(ann[-1][0]), "jade_max": int(ann[-1][1])}

    # 7. 进程关闭状态
    import subprocess as _sp
    procs_remaining = {}
    all_cleaned = False
    process_check_error = None
    try:
        tl = _tasklist_snapshot()
        procs_remaining = {
            "MAA": "MAA.exe" in tl,
            "MuMu主窗口": "MuMuNxMain.exe" in tl,
            "MuMu设备": "MuMuNxDevice.exe" in tl,
            "MuMu管理器": "MuMuPlayer.exe" in tl,
        }
        procs_remaining = {k: v for k, v in procs_remaining.items() if v}
        if os.path.exists(os.path.join(BASE, "outputs", "log_viewer.pid")):
            procs_remaining["实时日志窗"] = True
        all_cleaned = not any(procs_remaining.values())
    except Exception as e:
        process_check_error = str(e)
        procs_remaining = {"状态检查失败": True}

    # 8. 截图验证结果
    verification = dict(_LAST_VERIFICATION) if _LAST_VERIFICATION else {}
    if script_sanity_info and "未执行" in str(verification.get("Fight链", "")):
        verification["Fight链"] = (
            f"➖ 日常Fight未安排；主线Copilot已完成"
            f"{script_sanity_info['fights']}战，"
            f"消耗{script_sanity_info['consumed']}理智"
        )

    # 9. 综合判定: 日常是否真的做完
    daily_chains = ["Infrast", "Recruit", "Mall", "Award"]
    daily_all_ok = all(chain_status[c]["ok"] for c in daily_chains)
    startup_ok = chain_status["StartUp"]["ok"]
    fight_ran = chain_status["Fight"]["started"]

    # 10. 生成JSON报告。AllTasksCompleted只表示“当前MAA队列已结束”，Fight
    # 队列结束不能冒充完整流程的最终日常完成；完整/日常模式始终要求五条链。
    # 理智可能在战前读取日志中写成“当前理智”，也可能只在统一收尾时
    # 由主界面终端卡片读到。两者都是游戏画面直接证据；必须取日志中
    # 最后出现的一条，避免真实收尾理智被报告成“未确认”。
    current_stamina_matches = _re.findall(
        r"(?:当前理智:|主界面终端卡片读取:)\s*(\d+)\s*/\s*210",
        script_content,
    )
    final_stamina = int(current_stamina_matches[-1]) if current_stamina_matches else None

    # 游戏界面实时读数是日报理智的最高权威。MAA与脚本战斗日志只用于
    # 解释用途/次数，不能在实时余额缺失或冲突时替代游戏画面。
    stamina_observations = deepcopy(_RUN_SUMMARY.get("stamina_observations") or {})
    start_observation = stamina_observations.get("start") or {}
    final_observation = stamina_observations.get("final") or {}
    direct_start = start_observation.get("value") if start_observation.get("verified") else None
    direct_final = final_observation.get("value") if final_observation.get("verified") else None
    stamina_validation_required = (
        mode in (
            "daily", "daily_rerun", "full", "event_today", "mainline",
            "annihilation", "resource", "event",
        )
        and (
            _CURRENT_RUN_EVIDENCE_BOUNDARY_READY
            or "stamina_observations" in _RUN_SUMMARY
        )
    )
    conflicts = []
    maa_sanity_info = deepcopy(sanity_info)
    # daily补跑的实时起止只描述本次补跑；fight_handoff描述同游戏日更早、
    # 已独立闭环的战斗。二者不能直接做差，否则自然回复会被误报为冲突。
    historical_fight_before_tail = bool(
        mode in ("daily", "daily_rerun")
        and fight_handoff
        and isinstance(direct_start, int)
        and isinstance(direct_final, int)
    )
    sanity_comparison_scope = (
        "current_tail_realtime_plus_prior_verified_fight_handoff"
        if historical_fight_before_tail else "current_run"
    )
    if isinstance(direct_final, int):
        final_stamina = direct_final
    if isinstance(direct_start, int) and isinstance(direct_final, int):
        direct_consumed = max(0, direct_start - direct_final)
        if (
            not historical_fight_before_tail
            and sanity_info
            and isinstance(sanity_info.get("consumed"), int)
        ):
            logged_consumed = int(sanity_info.get("consumed") or 0)
            if logged_consumed != direct_consumed:
                conflicts.append(
                    f"日志消耗{logged_consumed}与游戏实时差值{direct_consumed}不一致"
                )
        sanity_info = {
            "first": direct_start,
            "last": direct_final,
            "max": 210,
            "consumed": direct_consumed,
            "source": "game_screen_ocr",
        }
        if script_sanity_info:
            sanity_info["fights"] = script_sanity_info.get("fights")
            sanity_info["stages"] = script_sanity_info.get("stages")
    stamina_validation = {
        "required": stamina_validation_required,
        "start": start_observation or None,
        "final": final_observation or None,
        "verified": (
            isinstance(direct_start, int) and isinstance(direct_final, int)
            if stamina_validation_required else True
        ),
        "conflicts": conflicts,
        "authority": "game_screen_ocr",
        "comparison_scope": sanity_comparison_scope,
        "maa_log_sanity": maa_sanity_info,
    }
    game_day_activity = _game_day_activity_summary(now)
    game_day_event_replay = _game_day_event_replay_summary(now=now)
    game_day_annihilation = _game_day_annihilation_summary(now=now)
    game_day_mainline = _load_mainline_handoff(now)
    game_day_security = _game_day_security_summary(now=now)
    game_day_chapter17 = _game_day_chapter17_summary(now=now)
    # 同游戏日较早完成的17章专项只进入 game_day_chapter17 历史小节。
    # 它不能补写本进程的 sanity/fight，否则一次未战斗的收尾会谎报本轮消耗。
    if game_day_activity and not chain_status["Fight"]["ok"]:
        # 最终日常由新的MAA进程执行，最后一段日志本来不含前一段Fight。
        # 同游戏日活动断点已由FightTimes闭环写入，可在总账中恢复真实Fight链。
        chain_status["Fight"] = {
            "started": True, "completed": True, "errored": False, "ok": True,
        }
        if fight_info is None:
            fight_info = {
                "fights": game_day_activity["runs"],
                "total_cost": game_day_activity["sanity_consumed"],
                "times_finished": game_day_activity["runs"],
                "series_batches": [],
                "stage": game_day_activity["stage"],
                "evidence": game_day_activity.get(
                    "evidence", "同游戏日活动FightTimes完成断点"
                ),
            }
        verification["Fight链"] = "✅ 完成（同游戏日活动FightTimes断点）"
    if final_stamina is None and game_day_activity:
        # 当前主界面皮肤可能让理智OCR失败；活动Fight完成日志中的终态理智是
        # 同游戏日直接证据，可补足余额，但不从“请求次数”反推。
        logged_balance = game_day_activity.get("sanity_after_farm")
        if isinstance(logged_balance, int):
            final_stamina = logged_balance
    if final_stamina is None and fight_handoff:
        handed_balance = fight_handoff.get("sanity_last")
        if isinstance(handed_balance, int):
            final_stamina = handed_balance

    # The final daily process is only the tail of the same game-day workflow.
    # If a named mainline attempt updated progress today and ended failed, the
    # final popup must include it instead of declaring the whole day verified
    # merely because all five daily chains succeeded.
    recent_mainline_records = {}
    for stage, state in ((game_day_mainline or {}).get("stages") or {}).items():
        if not isinstance(state, dict):
            continue
        recent_mainline_records[stage] = {
            **deepcopy(state),
            "updated_at": (game_day_mainline or {}).get("recorded_at"),
        }
    flow_paused = ((_RUN_SUMMARY.get("flow_control") or {}).get("status") == "paused")

    requested_daily = list(_RUN_SUMMARY.get("daily_requested_chains") or [])
    full_daily_set = {"StartUp", "Infrast", "Recruit", "Mall", "Award"}
    if mode == "daily" and requested_daily and set(requested_daily) != full_daily_set:
        intended_chains = requested_daily
    elif mode in ("daily", "daily_rerun", "full", "event_today") or recovered_daily:
        intended_chains = ["StartUp", "Infrast", "Recruit", "Mall", "Award"]
    elif mode in ("annihilation", "resource", "event"):
        intended_chains = ["Fight"]
    elif mode == "reclamation":
        intended_chains = []
    else:
        intended_chains = [chain for chain in report_chains if chain_status[chain]["started"]]
    flow_target = (_RUN_SUMMARY.get("flow_target") or {}).get("type")
    mainline_state = _RUN_SUMMARY.get("mainline") or {}
    if mode in ("full", "event_today") and flow_target == "mainline":
        flow_ok = mainline_state.get("status") in ("completed", "stamina_exhausted")
    elif mode in ("full", "event_today") and flow_target == "event":
        event_state = _RUN_SUMMARY.get("event") or {}
        pending_challenges = (
            (event_state.get("task_replay") or {}).get("pending_required_challenges") or []
        )
        flow_ok = (
            (event_state.get("navigation") or {}).get("status") == "verified"
            and (event_state.get("farm") or {}).get("status") == "completed"
            and not pending_challenges
        )
    else:
        flow_ok = True
    flow_ok = flow_ok and not flow_paused
    all_tasks_completed = bool(maa_queue_completed) and flow_ok and all(
        chain_status[chain]["ok"] for chain in intended_chains
    )

    run_summary_for_report = deepcopy(_RUN_SUMMARY)
    if game_day_security:
        # 最后的full进程可能只因入口导航失败而没有重新进入保全；同一游戏日
        # 更早的60/60、24/24实时奖励页断点才是最终事实，不能被后一次失败覆盖。
        run_summary_for_report["security"] = deepcopy(game_day_security)
    if game_day_chapter17:
        run_summary_for_report["chapter17"] = deepcopy(game_day_chapter17)
    security_for_report = run_summary_for_report.get("security") or {}
    security_flow_ok = not (
        mode == "full"
        and security_for_report
        and security_for_report.get("status") != "completed"
    )

    unspent_stamina = None
    if (
        mode in ("full", "event_today")
        and isinstance(final_stamina, int)
        and final_stamina >= 21
        and flow_target == "mainline"
        and mainline_state.get("status") == "completed"
        and not mainline_state.get("starting_target")
        and not mainline_state.get("next_target")
    ):
        remaining_use = _RUN_SUMMARY.get("remaining_sanity_use") or {}
        stamina_control = _RUN_SUMMARY.get("stamina_flow_control") or {}
        reason = (
            remaining_use.get("detail")
            or remaining_use.get("reason")
            or stamina_control.get("reason")
            or "主线已闭环，但资源兜底未消耗完剩余理智"
        )
        unspent_stamina = {
            "balance": final_stamina,
            "reason": reason,
        }

    report = {
        "date": date_str,
        "generated_at": time_str,
        "mode": mode,
        "chain_status": chain_status,
        "all_tasks_completed": all_tasks_completed,
        "maa_queue_completed": maa_queue_completed,
        "daily_gui_recovery": recovered_daily,
        "has_error": has_any_error,
        "sanity": sanity_info,
        "start_stamina": direct_start,
        "final_stamina": final_stamina,
        "stamina_validation": stamina_validation,
        "game_day_activity": game_day_activity,
        "game_day_event_replay": game_day_event_replay,
        "game_day_annihilation": game_day_annihilation,
        "game_day_mainline": game_day_mainline,
        "game_day_security": game_day_security,
        "game_day_chapter17": game_day_chapter17,
        "unspent_stamina": unspent_stamina,
        "fight": fight_info,
        "fight_handoff": fight_handoff,
        "drops": drops_list,
        "annihilation": ann_info,
        "verification": verification,
        "processes_remaining": procs_remaining,
        "process_check_error": process_check_error,
        "all_cleaned": all_cleaned,
        "daily_all_ok": daily_all_ok and startup_ok,
        "workflow_completed": (
            all_tasks_completed
            and security_flow_ok
            and not recent_mainline_records
            and not unspent_stamina
            and stamina_validation.get("verified") is True
            and not stamina_validation.get("conflicts")
            and not (_RUN_SUMMARY.get("decision_requests") or [])
            and ((_RUN_SUMMARY.get("stamina_flow_control") or {}).get("status") != "blocked")
            and ((_RUN_SUMMARY.get("flow_control") or {}).get("status") not in ("paused", "decision_required"))
        ),
        "run_summary": run_summary_for_report,
        "decision_requests": deepcopy(_RUN_SUMMARY.get("decision_requests") or []),
        "event_progress": _expire_closed_event_progress(now=now, persist=False),
        "intended_chains": intended_chains,
        "intended_stages": list(recent_mainline_records),
        "stage_task_records": recent_mainline_records,
    }

    # 同日补跑日常只能证明五条日常链完成，不能把更早的活动/主线/理智失败
    # 改写成“今天全部完成”。保留原 full 总账，并让补跑报告明确继承未完成态。
    if prior_incomplete_full_report:
        prior_summary = prior_incomplete_full_report.get("run_summary") or {}
        prior_chain_status = prior_incomplete_full_report.get("chain_status") or {}
        prior_missing_daily = [
            chain for chain in ("StartUp", "Infrast", "Recruit", "Mall", "Award")
            if not (prior_chain_status.get(chain) or {}).get("ok")
        ]
        prior_pause_reason = str((prior_summary.get("flow_control") or {}).get("reason") or "")
        prior_target = (prior_summary.get("flow_target") or {}).get("type")
        prior_mainline = prior_summary.get("mainline") or {}
        prior_event = prior_summary.get("event") or {}
        prior_non_daily_flow_ok = (
            (
                prior_target == "mainline"
                and prior_mainline.get("status") in ("completed", "stamina_exhausted")
            )
            or (
                prior_target == "event"
                and (prior_event.get("navigation") or {}).get("status") == "verified"
                and (prior_event.get("farm") or {}).get("status") == "completed"
                and not (
                    (prior_event.get("task_replay") or {})
                    .get("pending_required_challenges")
                )
            )
        )
        prior_security = prior_summary.get("security") or {}
        prior_security_ok = (
            not prior_security
            or prior_security.get("status") in ("completed", "skipped", "skipped_disabled")
        )
        recovered_only_daily_tail = (
            bool(prior_missing_daily)
            and all(chain_status[chain]["ok"] for chain in prior_missing_daily)
            and "最终日常" in prior_pause_reason
            and (prior_summary.get("annihilation") or {}).get("status")
                in ("completed_weekly", "skipped_weekly_complete")
            and prior_non_daily_flow_ok
            and prior_security_ok
            and (prior_summary.get("stamina_flow_control") or {}).get("status") != "blocked"
            and not (prior_incomplete_full_report.get("decision_requests") or [])
        )
        prior_base_333 = deepcopy(prior_summary.get("base_333") or {})
        if prior_security and not (report.get("run_summary") or {}).get("security"):
            report["run_summary"]["security"] = deepcopy(prior_security)
        if prior_base_333 and not (report.get("run_summary") or {}).get("base_333"):
            if (
                chain_status.get("Infrast", {}).get("ok")
                and prior_base_333.get("status") == "configured"
            ):
                prior_base_333["status"] = "applied_verified"
                prior_base_333["application_evidence"] = (
                    "同游戏日后续MAA Infrast链完成；MaaCore参数含动态333配置与plan_index"
                )
            report["run_summary"]["base_333"] = deepcopy(prior_base_333)
        prior_start_observation = (
            ((prior_summary.get("stamina_observations") or {}).get("start") or {})
        )
        prior_day_start = (
            prior_start_observation.get("value")
            if prior_start_observation.get("verified") else None
        )
        if isinstance(prior_day_start, int) and isinstance(final_stamina, int):
            report["day_stamina"] = {
                "start": prior_day_start,
                "final": final_stamina,
                "authority": "game_screen_ocr",
                "verified_fight_cost": int((fight_info or {}).get("total_cost", 0) or 0),
                "note": "全天战斗消耗按已验证FightTimes；起止余额差受期间自然回复影响",
            }
        report["same_day_prior_incomplete_flow"] = {
            "mode": prior_incomplete_full_report.get("mode"),
            "generated_at": prior_incomplete_full_report.get("generated_at"),
            "final_stamina": prior_incomplete_full_report.get("final_stamina"),
            "flow_target": prior_summary.get("flow_target"),
            "stamina_flow_control": prior_summary.get("stamina_flow_control"),
            "flow_control": prior_summary.get("flow_control"),
            "security": deepcopy(prior_security) if prior_security else None,
            "base_333": deepcopy(prior_base_333) if prior_base_333 else None,
            "recovered_by_current_daily_tail": recovered_only_daily_tail,
        }
        if prior_missing_daily and all(
            chain_status[chain]["ok"] for chain in prior_missing_daily
        ):
            report["same_day_prior_incomplete_flow"]["resolved_chains"] = prior_missing_daily
        if recovered_only_daily_tail:
            report["workflow_completed"] = bool(
                report["all_tasks_completed"]
                and stamina_validation.get("verified") is True
                and not stamina_validation.get("conflicts")
            )
            report["same_day_prior_incomplete_flow"]["resolved_chains"] = prior_missing_daily
        else:
            report["workflow_completed"] = False

    # 同一游戏日的显式主线/沙盘恢复不能覆盖12:00完整日报；恢复报告单独留档。
    report_stem = (
        f"mainline_resume_report_{date_str}_{now.strftime('%H%M%S')}"
        if mode in ("mainline", "chapter17_sandbox")
        else (
            f"daily_tail_report_{date_str}_{now.strftime('%H%M%S')}"
            if prior_incomplete_full_report
            else f"daily_report_{date_str}"
        )
    )
    json_path = os.path.join(BASE, "outputs", f"{report_stem}.json")
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except:
        pass

    # 11. 生成人类可读的中文叙述报告 (.md)
    md_lines = []
    md_lines.append(f"# 明日方舟自动化执行报告")
    md_lines.append(f"")
    md_lines.append(f"**日期**: {date_str}")
    md_lines.append(f"**生成时间**: {time_str}")
    md_lines.append(f"**模式**: {mode}")
    md_lines.append(f"")
    md_lines.append(f"---")
    md_lines.append(f"")
    md_lines.append(f"## 一、任务执行结果")
    md_lines.append(f"")
    md_lines.append(f"| 任务 | 启动 | 完成 | 状态 |")
    md_lines.append(f"|------|------|------|------|")
    for chain in report_chains:
        s = chain_status[chain]
        started_mark = "✓" if s["started"] else "✗"
        completed_mark = "✓" if s["completed"] else "✗"
        if chain == "Fight" and not s["started"] and script_sanity_info:
            started_mark = "—"
            completed_mark = "—"
            status = (
                f"➖ 日常Fight未安排；主线Copilot已完成"
                f"{script_sanity_info['fights']}战"
            )
        elif s["errored"]:
            status = "❌ 出错"
        elif s["completed"]:
            status = "✅ 完成"
        elif s["started"]:
            status = "⚠️ 启动但未完成"
        else:
            status = "⏸️ 未执行"
        md_lines.append(f"| {chain} | {started_mark} | {completed_mark} | {status} |")
    md_lines.append(f"")
    mainline_report = (
        (_RUN_SUMMARY.get("mainline") or {})
        if mode in ("mainline", "chapter17_sandbox")
        else {}
    )
    mainline_report_incomplete = bool(
        mode in ("mainline", "chapter17_sandbox")
        and mainline_report.get("status")
        in ("navigation_failed", "failed", "blocked", "jobs_unavailable")
    )
    if report["workflow_completed"] and not mainline_report_incomplete:
        md_lines.append(f"**✅ 本流程计划任务均已完成（MAA队列已结束）**")
    elif maa_queue_completed or mainline_report_incomplete:
        missing_intended = [chain for chain in intended_chains if not chain_status[chain]["ok"]]
        if mainline_report_incomplete:
            md_lines.append(
                f"**⚠️ MAA当前队列已结束，但主线目标未闭环"
                f"（{mainline_report.get('detail') or mainline_report.get('status')}）**"
            )
        else:
            md_lines.append(
                f"**⚠️ MAA当前队列已结束，但本流程计划任务未全部完成"
                f"（缺少: {', '.join(missing_intended) or '完成证据'}）**"
            )
    else:
        md_lines.append(f"**⚠️ MAA未触发AllTasksCompleted事件**")
    if has_any_error:
        md_lines.append(f"**⚠️ 本次执行包含TaskChainError**")
    md_lines.append(f"")

    md_lines.append(f"## 二、资源消耗")
    md_lines.append(f"")
    if stamina_validation.get("verified"):
        md_lines.append("- **理智核验来源**: 游戏界面实时OCR（运行前 + 清理前）")
    elif stamina_validation.get("required"):
        md_lines.append("- **理智核验**: ⚠️ 前后实时读数未闭环，本次不得宣称已耗尽理智")
    for conflict in stamina_validation.get("conflicts") or []:
        md_lines.append(f"- **理智证据冲突**: ❌ {conflict}")
    if sanity_info:
        if sanity_info.get('first') is not None and sanity_info.get('last') is not None:
            md_lines.append(f"- **理智**: {sanity_info['first']} → {sanity_info['last']} (上限{sanity_info['max']}, 消耗{sanity_info['consumed']})")
        else:
            # 主线模式: 从脚本日志获取
            consumed = sanity_info.get('consumed', 0)
            fights = sanity_info.get('fights', 0)
            stages = sanity_info.get('stages', [])
            stages_str = ', '.join(stages[:5]) + ('...' if len(stages) > 5 else '') if stages else '无'
            md_lines.append(f"- **理智**: 消耗{consumed} (战斗{fights}次: {stages_str})")
    elif not game_day_activity:
        md_lines.append(f"- **理智**: 未识别到")
    if fight_info:
        md_lines.append(f"- **战斗次数**: {fight_info['fights']}次, 消耗{fight_info['total_cost']}理智, 完成{fight_info['times_finished']}次")
    elif script_sanity_info:
        md_lines.append(f"- **战斗次数**: {script_sanity_info['fights']}次 (主线Copilot), 消耗{script_sanity_info['consumed']}理智")
    if game_day_activity:
        md_lines.append(
            f"- **今日体力用途**: {game_day_activity['stage']} 连续代理 "
            f"{game_day_activity['runs']}次 × {game_day_activity['sanity_cost_each']}理智"
            f" = 消耗{game_day_activity['sanity_consumed']}理智"
        )
    if game_day_event_replay:
        replay_names = ", ".join(item["stage"] for item in game_day_event_replay["stages"])
        md_lines.append(
            f"- **复刻任务重打**: {replay_names}；"
            f"合计消耗{game_day_event_replay['sanity_consumed']}理智"
        )
    if game_day_annihilation:
        md_lines.append(
            f"- **今日剿灭委托**: {game_day_annihilation['runs']}次，"
            f"消耗{game_day_annihilation['sanity_consumed']}理智，"
            f"合成玉{game_day_annihilation['jade_earned']}/{game_day_annihilation['jade_max']}"
        )
    if isinstance(final_stamina, int):
        md_lines.append(f"- **收尾时理智**: {final_stamina}/210")
    if ann_info:
        md_lines.append(f"- **剿灭合成玉**: {ann_info['jade_earned']} / {ann_info['jade_max']} (本周)")
    md_lines.append(f"")

    md_lines.append(f"## 三、获得物品")
    md_lines.append(f"")
    if drops_list:
        for d in drops_list:
            md_lines.append(f"- {d['item']} ×{d['qty']}")
    else:
        md_lines.append(f"- 本次未识别到掉落")
    md_lines.append(f"")

    md_lines.append(f"## 四、专项流程")
    md_lines.append(f"")
    if _RUN_SUMMARY:
        flow_target = _RUN_SUMMARY.get("flow_target") or {}
        if flow_target:
            target_label = flow_target.get("name") or ("主线" if flow_target.get("type") == "mainline" else "未知")
            md_lines.append(f"- **本轮路线**: {flow_target.get('type')} / {target_label}")
        ann_run = _RUN_SUMMARY.get("annihilation") or {}
        if ann_run:
            md_lines.append(
                f"- **剿灭**: {ann_run.get('status')}，目标{ann_run.get('requested_times', 1)}次"
            )
        event_run = _RUN_SUMMARY.get("event") or {}
        for stage, state in (event_run.get("stages") or {}).items():
            md_lines.append(f"- **{stage}**: {(state or {}).get('status', 'unknown')}")
        farm_run = event_run.get("farm") or {}
        if farm_run:
            md_lines.append(
                f"- **活动速刷**: {farm_run.get('stage')}，请求上限{farm_run.get('requested_runs')}次，"
                f"真实完成{farm_run.get('actual_runs', 0)}次，"
                f"消耗理智{farm_run.get('sanity_consumed', '未识别')}，"
                f"Series={farm_run.get('series')}，状态={farm_run.get('status')}"
            )
        pending_challenges = (
            (event_run.get("task_replay") or {}).get("pending_required_challenges") or []
        )
        for item in pending_challenges:
            reason = item.get("reason") or "未闭环"
            if reason == "today_retry_budget_exhausted":
                reason = "本游戏日不同作业重试预算已耗尽"
            md_lines.append(
                f"- **待补活动目标**: {item.get('stage', '未知关卡')}突袭；{reason}"
            )
        reclamation_run = _RUN_SUMMARY.get("reclamation") or {}
        if reclamation_run:
            md_lines.append(
                f"- **沙洲遗闻生息演算**: 模式={reclamation_run.get('mode')}，"
                f"目标轮数={reclamation_run.get('target_cycles')}，"
                f"完成轮数={reclamation_run.get('completed_cycles', 0)}，"
                f"状态={reclamation_run.get('status')}"
            )
        security_run = run_summary_for_report.get("security") or {}
        if security_run:
            security_counts = security_run.get("reward_counts") or {}
            md_lines.append(
                f"- **保全派驻**: 奖励周期={security_run.get('reward_cycle') or '未确认'}，"
                f"数据增补条={security_counts.get('strip', '未确认')}/60，"
                f"数据增补仪={security_counts.get('device', '未确认')}/24，"
                f"有效完整清理={security_run.get('successful_clears', 0)}轮，"
                f"状态={security_run.get('status', 'unknown')}"
            )
        chapter17_run = report.get("game_day_chapter17") or {}
        if chapter17_run.get("status") == "completed":
            chapter17_stages = "、".join(chapter17_run.get("stages") or [])
            chapter17_cost = int(chapter17_run.get("sanity_consumed", 0) or 0)
            md_lines.append(
                f"- **第17章阶段**: {chapter17_stages}险地作战与沙盘推演均完成；"
                f"险地消耗{chapter17_cost}理智，沙盘推演0理智"
            )
        decision_requests = _RUN_SUMMARY.get("decision_requests") or []
        if decision_requests:
            md_lines.append("- **待你确认（均未执行）**:")
            for request in decision_requests:
                md_lines.append(
                    f"  - {request.get('action', '未命名建议')}: "
                    f"{request.get('reason', '未说明原因')}"
                )
    else:
        md_lines.append("- 本次无专项流程")
    md_lines.append(f"")

    md_lines.append(f"## 五、截图验证")
    md_lines.append(f"")
    if verification:
        for k, v in verification.items():
            if k == "Fight链" and script_sanity_info and "未执行" in str(v):
                v = (
                    f"➖ 日常Fight未安排；主线Copilot已完成"
                    f"{script_sanity_info['fights']}战，"
                    f"消耗{script_sanity_info['consumed']}理智"
                )
            md_lines.append(f"- **{k}**: {v}")
    else:
        md_lines.append(f"- (本次未执行截图验证)")
    md_lines.append(f"")

    md_lines.append(f"## 六、进程清理")
    md_lines.append(f"")
    if all_cleaned:
        md_lines.append(f"**✅ MAA + MuMu模拟器 已全部关闭**")
    else:
        md_lines.append(f"**⚠️ 仍有进程未关闭**: {list(procs_remaining.keys())}")
    md_lines.append(f"")

    md_lines.append(f"## 七、综合结论")
    md_lines.append(f"")
    # 🔴 2026-07-01 修复: 报告必须诚实, 体力没花不能说"全部完成"
    # 检查体力是否消耗 (MAA Fight + 脚本Copilot战斗)
    stamina_consumed = (fight_info is not None and fight_info.get("fights", 0) > 0) or (script_sanity_info is not None and script_sanity_info.get("fights", 0) > 0)
    # 检查主线是否推进 (mode=full/mainline时)
    mainline_run = _RUN_SUMMARY.get("mainline") or {}
    mainline_advanced = bool(mainline_run.get("progressed"))
    
    if mode == "daily":
        if report["workflow_completed"] and daily_all_ok and startup_ok:
            md_lines.append(f"**✅ 今日整体流程完成**: 最终日常五链及全部专项均有完成证据")
        elif daily_all_ok and startup_ok:
            md_lines.append(f"**⚠️ 最终日常五链已完成，但今日整体仍有未闭环专项**")
            security_run = run_summary_for_report.get("security") or {}
            if security_run and security_run.get("status") != "completed":
                md_lines.append(
                    f"- 保全派驻未闭环: {security_run.get('reason') or security_run.get('status') or '未确认'}"
                )
            prior_flow = report.get("same_day_prior_incomplete_flow") or {}
            if prior_flow and prior_flow.get("recovered_by_current_daily_tail") is False:
                md_lines.append("- 同游戏日较早流程仍有未被本次尾部五链覆盖的失败证据")
        else:
            failed = [c for c in daily_chains if not chain_status[c]["ok"]]
            md_lines.append(f"**❌ 今日日常未完成**: {', '.join(failed)} 需要重新执行")
    elif mode in ("full", "event_today"):
        # full模式在活动开放期检查活动闭环；无活动时才检查主线。
        # 🔴 2026-07-08 修复: 显示主线未完成的/下一步, 不显示已通关的历史列表
        prog = load_progress()
        imperfect_all = prog.get("imperfect", [])
        next_target = prog.get("current", "")
        total = len(prog.get("通关顺序", []))
        cleared_all = prog.get("cleared", [])
        
        flow_target = _RUN_SUMMARY.get("flow_target") or {}
        target_type = flow_target.get("type")
        event_run = (_RUN_SUMMARY.get("event") or {})
        if target_type == "mainline" and (imperfect_all or next_target):
            md_lines.append(f"**主线进度**:")
            if imperfect_all:
                md_lines.append(f"- ⚠️ 需重打(非完美): {', '.join(sorted(imperfect_all))}")
            if next_target:
                md_lines.append(f"- ▶ 下一步: {next_target}")
            md_lines.append(f"- 已通关: {len(cleared_all)} / {total}关")
            md_lines.append(f"")
        
        issues = []
        ann_run = _RUN_SUMMARY.get("annihilation") or {}
        ann_status = ann_run.get("status")
        if mode == "full" and ann_status not in ("completed_weekly", "skipped_weekly_complete"):
            issues.append(f"本周剿灭未闭环: {ann_status or '未执行'}")
        security_run = run_summary_for_report.get("security") or {}
        if mode == "full" and security_run and security_run.get("status") != "completed":
            counts = security_run.get("reward_counts") or {}
            issues.append(
                "保全派驻奖励未封顶: "
                f"{counts.get('strip', '未确认')}/60、{counts.get('device', '未确认')}/24"
            )
        flow_paused = ((_RUN_SUMMARY.get("flow_control") or {}).get("status") == "paused")
        if not flow_paused and not (daily_all_ok and startup_ok):
            failed = [c for c in daily_chains if not chain_status[c]["ok"]]
            issues.append(f"日常未完成: {', '.join(failed)}")
        if flow_paused:
            reason = (_RUN_SUMMARY.get("flow_control") or {}).get("reason", "未说明原因")
            issues.append(f"流程已暂停: {reason}；最终日常未重复执行")
        stamina_control = _RUN_SUMMARY.get("stamina_flow_control") or {}
        if stamina_control.get("status") == "blocked":
            issues.append(
                f"理智流程已冻结: {stamina_control.get('reason', '未说明原因')}"
            )
        if unspent_stamina:
            issues.append(
                f"收尾理智仍为{unspent_stamina.get('balance')}/210；"
                f"{unspent_stamina.get('reason')}"
            )
        if target_type == "mainline":
            mainline_status = mainline_run.get("status")
            if mainline_status in ("navigation_failed", "failed", "blocked"):
                issues.append(f"主线未闭环: {mainline_run.get('detail') or mainline_status}")
            elif (
                not mainline_advanced
                and mainline_status != "stamina_exhausted"
                and (mainline_run.get("starting_target") or mainline_run.get("next_target"))
            ):
                issues.append("本轮选择主线，但未推进任何关卡")
        if target_type == "event":
            if not event_run:
                issues.append(f"本轮选择活动{flow_target.get('name', '')}，但没有活动执行记录")
            nav_status = (event_run.get("navigation") or {}).get("status")
            if nav_status != "verified":
                issues.append(f"活动导航未验证: {nav_status or '未执行'}")
            bad_event_stages = [
                stage for stage, state in (event_run.get("stages") or {}).items()
                if (state or {}).get("status") != "cleared"
            ]
            if bad_event_stages:
                issues.append(f"活动关未完成: {', '.join(bad_event_stages)}")
            farm_status = (event_run.get("farm") or {}).get("status")
            if farm_status != "completed":
                issues.append(f"活动速刷未完成: {farm_status or '未执行'}")
        elif target_type == "mainline" and not stamina_consumed and not unspent_stamina:
            if isinstance(final_stamina, int):
                issues.append(
                    f"收尾理智仍为{final_stamina}/210；当前无待推进主线且未配置资源兜底关"
                )
            else:
                issues.append("理智用途与收尾余额均未确认")
        if issues:
            md_lines.append(f"**⚠️ 今日执行有问题**:")
            for iss in issues:
                md_lines.append(f"- {iss}")
            md_lines.append(f"- 请检查脚本日志: outputs/auto_run.log")
        else:
            completed_scope = "日常+活动首通/速刷" if target_type == "event" else "日常+主线+体力消耗"
            md_lines.append(f"**✅ 今日全部完成**: {completed_scope}均有完成证据")
    elif mode == "mainline":
        prog = load_progress()
        cleared_all = prog.get("cleared", [])
        imperfect_all = prog.get("imperfect", [])
        total = len(prog.get("通关顺序", []))
        next_target = prog.get("current", "")
        
        md_lines.append(f"**主线推进情况**:")
        md_lines.append(f"- 权威进度文件已记录完成节点: {len(set(cleared_all))}个")
        
        if imperfect_all:
            md_lines.append(f"- ⚠️ 需重打(非完美): {', '.join(sorted(imperfect_all))}")
        
        if next_target:
            md_lines.append(f"- ▶ 下一步目标: {next_target}")
        else:
            md_lines.append(f"- ▶ 下一步目标: 查找中...")
        
        # 不显示全部已通关列表(用户已看过), 只显示数量
        md_lines.append(f"- 完美通关: {len(cleared_all)}关")
        
        if not stamina_consumed:
            md_lines.append(f"- ⚠️ 体力0消耗(理智未花)")
        md_lines.append(f"- 详见: outputs/主线通关进度.json")
    elif mode == "annihilation":
        if ann_info:
            md_lines.append(f"**剿灭执行**: 合成玉{ann_info['jade_earned']}/{ann_info['jade_max']}")
        else:
            md_lines.append(f"**⚠️ 剿灭未识别到合成玉信息**")
    md_lines.append(f"")
    md_lines.append(f"---")
    md_lines.append(f"")
    md_lines.append(f"*报告文件: {json_path}*")

    md_path = os.path.join(BASE, "outputs", f"{report_stem}.md")
    try:
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(md_lines))
    except:
        pass

    # 12. 控制台打印摘要
    log("")
    log("=" * 60)
    log("  📊 今日执行报告 (人类可读)")
    log("=" * 60)
    log(f"  日期: {date_str}  时间: {time_str}  模式: {mode}")
    log("")
    log("  任务链执行:")
    for chain in report_chains:
        s = chain_status[chain]
        if chain == "Fight" and not s["started"] and script_sanity_info:
            status = f"➖日常未安排；主线Copilot完成{script_sanity_info['fights']}战"
        elif s["errored"]:
            status = "❌出错"
        elif s["completed"]:
            status = "✅完成"
        elif s["started"]:
            status = "⚠️未完成"
        else:
            status = "⏸未执行"
        log(f"    {chain:10s}: {status}")
    log("")
    if sanity_info:
        if sanity_info.get("first") is not None and sanity_info.get("last") is not None:
            log(
                f"  理智: {sanity_info['first']}→{sanity_info['last']} "
                f"(消耗{sanity_info['consumed']})"
            )
        else:
            log(f"  理智: 已确认消耗{sanity_info.get('consumed', 0)}，首尾余额不完整")
    if fight_info:
        log(f"  战斗: {fight_info['fights']}次, 消耗{fight_info['total_cost']}理智")
    if game_day_activity:
        log(
            f"  今日体力用途: {game_day_activity['stage']}连续代理"
            f"{game_day_activity['runs']}次 × {game_day_activity['sanity_cost_each']}"
            f" = 消耗{game_day_activity['sanity_consumed']}理智"
        )
    if game_day_event_replay:
        log(
            f"  复刻任务重打: {game_day_event_replay['completed_count']}项，"
            f"失败作业{game_day_event_replay.get('failed_runs', 0)}次，"
            f"消耗{game_day_event_replay['sanity_consumed']}理智"
        )
    if game_day_annihilation:
        log(
            f"  今日剿灭: {game_day_annihilation['runs']}次，"
            f"消耗{game_day_annihilation['sanity_consumed']}理智，"
            f"合成玉{game_day_annihilation['jade_earned']}/{game_day_annihilation['jade_max']}"
        )
    if isinstance(final_stamina, int):
        log(f"  收尾时理智: {final_stamina}/210")
    if ann_info:
        log(f"  剿灭合成玉: {ann_info['jade_earned']}/{ann_info['jade_max']}")
    if drops_list:
        log("  获得物品:")
        for d in drops_list[:5]:
            log(f"    - {d['item']} ×{d['qty']}")
    log("")
    if verification:
        log("  截图验证:")
        for k, v in verification.items():
            log(f"    {k}: {v}")
    log("")
    if all_cleaned:
        log("  ✅ MAA+MuMu已全部关闭")
    else:
        log(f"  ⚠️ 进程未关: {list(procs_remaining.keys())}")
    log("")
    if mode in ("daily", "full"):
        summary_title, _summary_text, summary_outcome = _truthful_completion_summary(report)
        icon = "✅" if summary_outcome == "verified" else "⚠️"
        log(f"  {icon} 综合结论: {summary_title}")
    log("")
    log(f"  📄 人类可读报告: {md_path}")
    log(f"  📄 JSON数据: {json_path}")
    log("=" * 60)

    # 重置全局验证状态
    _LAST_VERIFICATION = {}

    return report

# ============================================================
# 场景模式: 完整流程
# ============================================================

def _block_stamina_flow(reason, source=""):
    """冻结本轮后续理智消耗，但不阻止最终不耗理智的日常链。"""
    detail = str(reason or "理智战斗流程未闭环")
    _RUN_SUMMARY["stamina_flow_control"] = {
        "status": "blocked",
        "reason": detail,
        "source": source,
        "blocked_at": datetime.now().isoformat(timespec="seconds"),
    }
    log(f"⛔ 后续理智消耗已冻结: {detail}", "ERROR")
    return False

def _run_full_annihilation_step(force=False, times=None):
    """周任务步骤；只负责剿灭，不推断后续目标。"""
    if not _plan_allows("annihilation"):
        _record_decision_request(
            "完整流程加入剿灭",
            "本轮执行契约未授权剿灭动作",
            ["G-AUTH-001", "G-WEEKLY-001"],
        )
        return False
    if force or annihilation_due():
        log("\n>>> 第1步: 本周剿灭未确认完成，优先补齐")
        # 只有明确True才算闭环。历史代码把None也当成功，导致启动超时后
        # 仍放行主线，直接违背“剿灭优先”的项目契约。
        return mode_annihilation(force=force, times=times) is True
    log("\n>>> 第1步: 本周剿灭已有完成证据，跳过")
    _RUN_SUMMARY["annihilation"] = {
        "week": _annihilation_week_key(),
        "requested_times": 0,
        "status": "skipped_weekly_complete",
    }
    return True


def _run_full_event_steps(active_event):
    """活动路线：真实导航和首通闭环成功后，才允许刷契约指定活动关。"""
    replay_action = "event_task_replay" if active_event.get("kind") == "rerun" else "event_first_clear"
    if not (_plan_allows(replay_action) and _plan_allows("event_farm")):
        _record_decision_request(
            "活动首通与速刷",
            "本轮执行契约没有同时授权活动首通和活动刷取",
            ["G-AUTH-001", "G-EVENT-001"],
        )
        return False, False
    reload_maa_after_config_switch("剿灭阶段结束，释放控制并恢复到活动导航起点")
    if not goto_main_menu():
        event_run = _RUN_SUMMARY.setdefault(
            "event", {"name": active_event["name"], "stages": {}}
        )
        event_run.setdefault("navigation", {}).update({
            "status": "failed",
            "detail": "剿灭结束后未能恢复到主界面",
        })
        log("⛔ 剿灭→活动阶段交接失败，拒绝盲点活动入口", "ERROR")
        first_clear_ok = False
    else:
        first_clear_ok = None
    if active_event.get("kind") == "rerun":
        log(f"\n>>> 第2步: {active_event['name']}复刻任务关逐关代理重打")
        write_status("第2步: 复刻活动任务重打", active_event["name"])
    else:
        log(f"\n>>> 第2步: {active_event['name']}普通→突袭逐关首通（活动优先）")
        write_status("第2步: 活动首通", active_event["name"])
    if first_clear_ok is None:
        if active_event.get("kind") == "rerun":
            first_clear_ok = mode_event_rerun_tasks(active_event)
        else:
            first_clear_ok = mode_event_first_clear(active_event)
    if first_clear_ok == "automation_unavailable":
        event_run = _RUN_SUMMARY.setdefault(
            "event", {"name": active_event["name"], "stages": {}}
        )
        event_run["status"] = "automation_unavailable"
        event_run["detail"] = (
            "本期已开放关卡与在线作业已确认，但MAA最新资源尚不支持内部关卡；"
            "依据本轮用户指令转主线，不消耗活动失败次数"
        )
        log(
            "⏭ 活动作业已出现但MAA资源尚未开放执行支持；"
            "按本轮明确指令转主线推进",
            "WARN",
        )
        return "fallback_mainline", True
    deferred_event_job = first_clear_ok in ("deferred_ex_job", "deferred_event_job")
    if deferred_event_job:
        log(
            "⏭ EX关已无普通成功作业或其他兼容作业可用：保留为次日待办，"
            "不把无作业当成战败或技术故障，继续执行活动收益关刷取",
            "WARN",
        )
    if (
        isinstance(first_clear_ok, tuple)
        and len(first_clear_ok) >= 2
        and first_clear_ok[0] == "manual_required"
    ):
        prerequisite = first_clear_ok[1]
        target = (
            (_RUN_SUMMARY.get("event") or {}).get("manual_prerequisite") or {}
        ).get("target_stage", "后续活动关")
        reason = f"{prerequisite}教学关阻挡；需手动完成后继续{target}"
        _RUN_SUMMARY["flow_control"] = {
            "status": "paused",
            "reason": reason,
        }
        _block_stamina_flow(reason, source="event_manual_prerequisite")
        log(f"⏸ {reason}；已停止后续理智消耗并转最终日常", "WARN")
        return False, True
    if first_clear_ok == "stamina_exhausted":
        event_run = _RUN_SUMMARY.setdefault("event", {})
        event_run["status"] = "stamina_exhausted_during_task_replay"
        event_run["detail"] = "复刻任务按顺序代理至理智不足；剩余关卡已保留断点"
        log("ℹ️ 复刻任务已用完本轮可用理智；不再启动收益关，转最终日常")
        return False, True
    if not first_clear_ok:
        _block_stamina_flow("活动任务重打/首通或导航未闭环", source="event_progress")
        log("⛔ 活动前置目标未闭环，拒绝启动后续收益关刷取", "ERROR")
        return False, True

    reward_claim_ok = True
    task_claim_enabled = active_event.get("task_claim_enabled", True)
    if not task_claim_enabled:
        rewards = _RUN_SUMMARY.setdefault("event", {}).setdefault("task_rewards", {})
        rewards["status"] = "skipped_by_user"
        rewards["detail"] = active_event.get(
            "task_claim_skip_reason",
            "用户明确要求本期不自动领取活动任务奖励",
        )
        log(f"⏭ 活动任务奖励本期暂不自动领取：{rewards['detail']}")
    elif _plan_allows("event_task_claim"):
        reward_claim_ok = claim_event_task_rewards(active_event) is True
        if not reward_claim_ok:
            rewards = _RUN_SUMMARY.setdefault("event", {}).setdefault("task_rewards", {})
            rewards["status"] = "deferred"
            rewards["detail"] = (
                "活动任务页暂未确认；不属于耗理智战斗故障，先按授权目标刷活动关，刷完再重试"
            )
            log(
                "⚠️ 活动任务奖励暂未确认；该零理智步骤不得冻结活动刷取，"
                "先继续消耗理智并在战后重试",
                "WARN",
            )

    runs = 99  # 仅是已授权活动关的安全上限；理智不足即结束
    log(
        f"\n>>> 第3步: 从当前活动地图刷取 {active_event['farm_stage']} "
        f"直至理智不足（Series=AUTO速刷多次）"
    )
    write_status("第3步: 活动速刷", f"{active_event['farm_stage']} 至理智不足")
    if mode_event(stage_code=active_event["farm_stage"], times=runs) is False:
        _block_stamina_flow("活动收益关连续代理未确认完成", source="event_farm")
        log("⏸ 活动速刷失败，停止后续理智消耗并转最终日常", "ERROR")
        return False, True
    if task_claim_enabled and _plan_allows("event_task_claim") and not reward_claim_ok:
        log("→ 活动收益关刷取结束，第二次检查活动任务奖励")
        reward_claim_ok = claim_event_task_rewards(active_event) is True
        if not reward_claim_ok:
            rewards = _RUN_SUMMARY.setdefault("event", {}).setdefault("task_rewards", {})
            rewards["status"] = "deferred"
            rewards["detail"] = "刷取前后两次均未确认活动任务页；保留为待领并如实汇报"
            log("⚠️ 活动奖励仍未确认领取，保留为待办；不改写战斗和理智使用结果", "WARN")
    pending_challenges = (
        _RUN_SUMMARY.get("event", {}).get("task_replay", {})
        .get("pending_required_challenges", [])
    )
    return (
        not deferred_event_job
        and not bool(pending_challenges)
        and reward_claim_ok,
        True,
    )


def _run_full_mainline_step(start_chapter=None):
    """主线路线；失败转移只能来自项目契约，绝不自动创造资源关目标。"""
    if not _plan_allows("mainline"):
        _record_decision_request(
            "完整流程加入主线",
            "本轮执行契约未授权主线动作",
            ["G-AUTH-001", "G-MAINLINE-001"],
        )
        return False, True
    log("\n>>> 第2步: 主线推进(当前无活动)")
    write_status("第2步: 主线推进", "进入章节地图检测关卡")
    stamina = _check_stamina_confirmed()
    if stamina is not None and stamina < 21:
        _RUN_SUMMARY.setdefault("mainline", {}).update({
            "status": "stamina_exhausted",
            "detail": f"理智{stamina}不足当前最难主线关；未选择替代资源关",
            "progressed": False,
        })
        log(f"理智不足当前最难主线({stamina})，进入最终日常；未自动选择资源关")
        return True, True

    try:
        mainline_ok = mode_mainline(start_chapter=start_chapter)
    except Exception as exc:
        log(f"  ⚠️ 主线推进异常，停止后续操作并进入默认清理: {exc}", "WARN")
        _block_stamina_flow(f"主线推进异常: {exc}", source="mainline")
        return False, True
    if mainline_ok is not False:
        state = _RUN_SUMMARY.get("mainline") or {}
        # 只有完整地图扫描到配置末端，且没有搁置/非完美/H关或17章阶段
        # 待办，才可进入资源兜底。理智不足结束的主线不再启动第二条理智链。
        if state.get("status") == "completed":
            progress = load_progress()
            pending_hard = _next_pending_hard_stage(progress)
            pending_phase = _chapter17_pending_phase_target(progress)
            if (
                not progress.get("imperfect")
                and not progress.get("shelved")
                and not pending_hard
                and not pending_phase
            ):
                log("\n>>> 第3步: 主线/隐藏关已闭环，启动1-7固源岩搓玉兜底")
                resource_ok = mode_orundum_rock_fallback()
                if not resource_ok:
                    _block_stamina_flow(
                        "1-7固源岩搓玉兜底未闭环",
                        source="orundum_rock_fallback",
                    )
                return resource_ok, True
            detail = (
                f"仍有主线扩展待办: imperfect={progress.get('imperfect') or []}, "
                f"shelved={progress.get('shelved') or []}, "
                f"hard={pending_hard}, chapter17={pending_phase}"
            )
            log(f"⏸ {detail}；不启动资源兜底", "WARN")
        return True, True

    state = _RUN_SUMMARY.get("mainline") or {}
    if state.get("status") == "blocked" and _RUN_SUMMARY.get("decision_requests"):
        _RUN_SUMMARY["flow_control"] = {
            "status": "decision_required",
            "reason": state.get("detail") or "普通主线阻塞关需要用户决定",
        }
        log("⏭ 主线目标等待用户决定；不执行替代关，但继续独立的最终日常", "WARN")
        return False, True

    _block_stamina_flow(
        state.get("detail") or "主线基础设施未闭环", source="mainline"
    )
    log("⏸ 主线导航或控制链失败，停止后续理智消耗并转最终日常", "WARN")
    return False, True


def _run_full_optional_sss_step():
    """理智路线之后、最终日常之前执行的独立月中刷新任务。"""
    if not ENABLE_SSS_IN_FULL:
        log("\n>>> 第4步: 显式禁用保全派驻(ARKNIGHTS_ENABLE_SSS=0)")
        return True
    if not _plan_allows("security"):
        _record_decision_request(
            "保全派驻周期任务",
            "本轮执行契约未授权保全派驻",
            ["G-AUTH-001", "G-SSS-001"],
        )
        return False
    log("\n>>> 第4步: 保全派驻(SSS)")
    write_status("第4步: 保全派驻SSS")
    goto_main_menu()
    wait(2)
    try:
        return mode_security() is not False
    except Exception as exc:
        log(f"   ⚠️ SSS失败: {exc}", "WARN")
        return False


def _set_final_daily_completion_boundary():
    """最终日常只能复用晚于本轮最后一次理智战斗的完成证据。"""
    global _DAILY_COMPLETION_NOT_BEFORE
    parsed_fight_boundary = None
    try:
        with open(MAA_GUI_LOG, "r", encoding="utf-8") as f:
            parsed_fight_boundary = _latest_completed_fight_at_from_gui_log(f.read())
    except Exception:
        parsed_fight_boundary = None
    candidates = [
        value for value in (parsed_fight_boundary, _CURRENT_RUN_LAST_STAMINA_BATTLE_AT)
        if value is not None
    ]
    _DAILY_COMPLETION_NOT_BEFORE = max(candidates) if candidates else None
    if _DAILY_COMPLETION_NOT_BEFORE:
        log(
            "→ 最终日常刷新边界：只接受晚于最后一次理智作战 "
            f"{_DAILY_COMPLETION_NOT_BEFORE.isoformat(timespec='seconds')} 的五链完成记录"
        )
    return _DAILY_COMPLETION_NOT_BEFORE


def _run_full_final_daily_step():
    """只在前序边界允许时执行一次最终五链。"""
    if not _plan_allows("daily"):
        _record_decision_request(
            "完整流程最终日常",
            "本轮执行契约未授权最终日常",
            ["G-AUTH-001", "G-DAILY-001"],
        )
        return False
    log("\n>>> 第5步: MAA日常收尾")
    write_status("第5步: MAA日常收尾", "基建/招募/商店/任务奖励")
    if not _recover_current_run_battle_for_final_daily():
        _RUN_SUMMARY["flow_control"] = {
            "status": "paused",
            "reason": "本轮理智战斗残留未能安全恢复，最终日常未启动",
        }
        return False
    if (_RUN_SUMMARY.get("daily_battle_recovery") or {}).get("status") == (
        "current_run_cold_restart_started"
    ):
        wait(8)
        if not goto_main_menu():
            _RUN_SUMMARY["flow_control"] = {
                "status": "paused",
                "reason": "本轮战斗冷启动后未能确认主界面，最终日常未启动",
            }
            return False
        _RUN_SUMMARY["daily_battle_recovery"]["status"] = "main_menu_confirmed"
    _set_final_daily_completion_boundary()
    if not prepare_dynamic_333_base():
        log("⚠️ 动态333未形成新鲜库存闭环；保留当前基建产品并继续最终日常", "WARN")
        if (_RUN_SUMMARY.get("base_333") or {}).get("home_return") == "failed":
            _RUN_SUMMARY["flow_control"] = {
                "status": "paused",
                "reason": "动态333仓库刷新后未能返回主界面，最终日常未启动",
            }
            return False
    _prepare_daily_maa_boundary("活动/剿灭Fight结束，切回日常TaskQueue")
    if mode_daily() is True:
        return True
    _RUN_SUMMARY["flow_control"] = {
        "status": "paused",
        "reason": "最终日常任务链未全部完成（含Award）",
    }
    log("⏸ 最终日常未闭环；停止后续操作，进入默认清理并如实弹窗", "ERROR")
    return False


def mode_full(start_chapter=None, force_annihilation=False, annihilation_times=None):
    """把获准目标编排为：剿灭 → 活动或主线 → 单次最终日常。"""
    if _ensure_execution_plan("full") is None:
        log("⛔ 无法从项目契约编译完整流程，未启动任何子步骤", "ERROR")
        return False
    log("=" * 60)
    log("  场景: 完整流程 (项目契约编排)")
    log("=" * 60)
    write_status("启动完整流程", "周一剿灭核对→活动优先/主线→保全刷新核对→单次最终日常")

    # 长期任务若异常退出，可能把游戏留在战斗页面。活动检测之前必须先
    # 依据长期任务的终态交接证据接管；否则后续“无法进入终端”只会冻结
    # 理智，却没有解决真正的启动边界。未知归属或仍在运行的战斗继续拒绝。
    startup_handoff = _load_daily_long_term_handoff()
    startup_state = get_state() if startup_handoff else None
    if startup_handoff and startup_state == "battle":
        log("→ full启动检测到战斗残留，先核对长期任务终态交接")
        if not _recover_terminal_long_term_battle_for_daily():
            _block_stamina_flow(
                "启动时战斗仍在运行或缺少长期任务终态交接证据",
                source="startup_battle_recovery",
            )
            _run_full_final_daily_step()
            return False
        wait(8)
        if not goto_main_menu():
            _block_stamina_flow(
                "已取得旧战斗接管权，但冷启动后无法确认主界面",
                source="startup_battle_recovery",
            )
            _run_full_final_daily_step()
            return False
        recovery_summary = _RUN_SUMMARY.setdefault("daily_battle_recovery", {})
        recovery_summary["status"] = "main_menu_confirmed"
        recovery_summary["main_menu_confirmed_at"] = (
            datetime.now().isoformat(timespec="seconds")
        )
        log("✅ full启动已清理长期任务战斗残留并确认主界面")

    _expire_closed_event_progress()

    # 玩家真实决策顺序：周一先核对剿灭周奖励。若已经达到上限，记录后
    # 继续决定今天理智去向；若未达到上限则先补剿灭。终端活动卡片无权
    # 抢在剿灭之前冻结整条理智链。
    annihilation_ok = _run_full_annihilation_step(
        force=force_annihilation, times=annihilation_times
    )
    if not annihilation_ok:
        _block_stamina_flow(
            "本周剿灭未闭环，禁止活动/主线/资源关等后续理智消耗",
            source="annihilation",
        )
        log(
            "⛔ 剿灭未闭环；阻断活动/主线/资源关等理智消耗，"
            "继续执行不耗理智的最终日常",
            "ERROR",
        )
        _run_full_optional_sss_step()
        _run_full_final_daily_step()
        return False

    # 复制 MAA 的 StageManager/GetStageTips 数据链，在脚本内先读取活动日历。
    # 终端左下卡片可能只显示最后入口或因美术字漏 OCR；日历只能决定“去核验
    # 哪个活动”，不能代替进入活动地图后对本期关卡族的真实图形确认。
    try:
        daily_tip = save_maa_daily_stage_tip()
    except Exception as exc:
        daily_tip = {
            "status": "error",
            "active_side_stories": [],
            "lines": [],
            "depot": {"fresh": False, "note": f"提示生成失败: {exc}"},
        }
        log(f"⚠️ 脚本今日关卡小提示生成失败: {exc}", "WARN")
    _RUN_SUMMARY["daily_stage_tip"] = deepcopy(daily_tip)
    if daily_tip.get("lines"):
        log("\n>>> 今日关卡小提示（脚本直接读取 MAA 数据，不打开 MAA）")
        for line in daily_tip["lines"]:
            log(f"  {line}")
        log(f"  {daily_tip.get('depot', {}).get('note', '')}")

    calendar_event, calendar_story = _configured_event_from_maa_tip(daily_tip)
    unknown_calendar_stories = [
        story for story in (daily_tip.get("active_side_stories") or [])
        if _configured_event_from_name(story.get("name")) is None
    ]
    event_detection = detect_terminal_limited_event()
    event_detection["maa_calendar"] = {
        "status": daily_tip.get("status"),
        "active_side_stories": deepcopy(daily_tip.get("active_side_stories") or []),
        "matched_configured_event": (calendar_event or {}).get("name"),
    }
    _RUN_SUMMARY["terminal_event_detection"] = deepcopy(event_detection)
    if event_detection.get("status") == "open":
        active_event = _configured_event_from_name(event_detection.get("name"))
        if not active_event:
            ignored_activity = _non_stamina_activity_from_name(event_detection.get("name"))
            if ignored_activity:
                event_detection.update({
                    "classification": "non_stamina_web_activity",
                    "ignored_for_stamina_routing": True,
                    "canonical_name": ignored_activity["name"],
                })
                _RUN_SUMMARY["terminal_event_detection"] = dict(event_detection)
                active_event = calendar_event
                log(
                    f"ℹ️ 终端卡片“{event_detection.get('name')}”已识别为非理智活动；"
                    "不阻断剿灭后的体力路线"
                )
                if active_event:
                    log(
                        f"→ MAA活动日历仍显示理智活动开放，转入真实地图核验: "
                        f"{active_event['name']}"
                    )
            else:
                reason = f"终端发现未知开放活动: {event_detection.get('name')}"
                _record_decision_request(
                    "未知限时活动的体力路线",
                    reason,
                    ["G-AUTH-001", "G-EVENT-001", "G-STAMINA-SAFETY-001"],
                )
                _block_stamina_flow(reason, source="terminal_event_detection")
                _run_full_optional_sss_step()
                _run_full_final_daily_step()
                return False
    elif event_detection.get("status") == "none":
        terminal_none_confirmed = bool(str(event_detection.get("evidence") or "").strip())
        if calendar_event and terminal_none_confirmed:
            active_event = calendar_event
            event_detection.update({
                "status": "open",
                "name": calendar_event["name"],
                "remaining_days": (calendar_story or {}).get("remaining_days_text"),
                "source": "maa_stage_activity_cache_fallback",
                "terminal_direct_result": "none",
                "requires_event_map_visual_verification": True,
                "evidence": (
                    f"{event_detection.get('evidence', '')}; MAA StageActivityV2 显示"
                    f"{calendar_event['name']}开放至{(calendar_story or {}).get('expire_utc')}"
                ),
            })
            _RUN_SUMMARY["terminal_event_detection"] = deepcopy(event_detection)
            log(
                f"⚠️ 终端左下未显示开放标记，但 MAA 活动日历确认"
                f"“{calendar_event['name']}”仍开放；改走活动地图真实核验，不进入主线",
                "WARN",
            )
        elif unknown_calendar_stories and terminal_none_confirmed:
            reason = (
                "MAA活动日历发现未配置的开放活动: "
                + "、".join(story.get("name", "未知活动") for story in unknown_calendar_stories)
            )
            _record_decision_request(
                "补充未知活动导航与体力路线", reason,
                ["G-AUTH-001", "G-EVENT-001", "G-STAMINA-SAFETY-001"],
            )
            _block_stamina_flow(reason, source="maa_stage_activity_cache")
            _run_full_optional_sss_step()
            _run_full_final_daily_step()
            return False
        else:
            active_event = None
    else:
        if calendar_event:
            active_event = calendar_event
            event_detection.update({
                "status": "open",
                "name": calendar_event["name"],
                "remaining_days": (calendar_story or {}).get("remaining_days_text"),
                "source": "maa_stage_activity_cache_recovery",
                "terminal_direct_result": "uncertain",
                "requires_event_map_visual_verification": True,
            })
            _RUN_SUMMARY["terminal_event_detection"] = deepcopy(event_detection)
            log(
                f"⚠️ 终端活动 OCR 不确定；MAA 活动日历把路线恢复为"
                f"“{calendar_event['name']}”，后续仍须活动地图图形闭环",
                "WARN",
            )
        else:
            reason = event_detection.get("evidence") or "终端限时活动状态无法确认"
            _block_stamina_flow(reason, source="terminal_event_detection")
            _run_full_optional_sss_step()
            _run_full_final_daily_step()
            return False

    if active_event:
        _RUN_SUMMARY["flow_target"] = {
            "type": "event",
            "name": active_event["name"],
            "decided_at": datetime.now().isoformat(timespec="seconds"),
        }
        _RUN_SUMMARY.setdefault(
            "event",
            {"name": active_event["name"], "stages": {}, "navigation": {"status": "pending"}},
        )
    else:
        _RUN_SUMMARY["flow_target"] = {
            "type": "mainline",
            "decided_at": datetime.now().isoformat(timespec="seconds"),
        }

    if active_event:
        route_ok, allow_daily = _run_full_event_steps(active_event)
        if route_ok == "fallback_mainline":
            _RUN_SUMMARY["flow_target"]["fallback"] = {
                "type": "mainline",
                "reason": "活动MAA资源尚未支持",
                "decided_at": datetime.now().isoformat(timespec="seconds"),
            }
            route_ok, allow_daily = _run_full_mainline_step(
                start_chapter=start_chapter,
            )
    else:
        route_ok, allow_daily = _run_full_mainline_step(start_chapter=start_chapter)

    if not allow_daily:
        return False
    # 保全派驻不消耗理智，且有独立的奖励周期；即使活动/主线路线本轮冻结，
    # 只要仍允许进入最终日常，也要独立核对本周期是否到期。
    sss_ok = _run_full_optional_sss_step()
    daily_ok = _run_full_final_daily_step()
    if annihilation_ok and route_ok and sss_ok and daily_ok:
        log("\n✅ 完整流程计划内目标均已闭环")
        return True
    log("\n⚠️ 完整流程仅部分完成；详见失败项和待确认建议", "WARN")
    return False

# ============================================================
# 环境启动
# ============================================================

def detect_mumu_adb_port():
    """从mumu-cli info自动检测MuMu的ADB端口 (端口可能每次启动变化)"""
    global DEVICE
    try:
        if resolve_mumu_instance() is None:
            return False
        r = _run_mumu("info", "-v", MUMU_VM_INDEX, timeout=10)
        import json as _json
        if r.returncode != 0 or not (r.stdout or "").strip():
            return False
        info = _json.loads(r.stdout)
        port = info.get("adb_port", 0)
        if port > 0:
            old = DEVICE
            DEVICE = f"127.0.0.1:{port}"
            if old != DEVICE:
                log(f"  [ADB] MuMu端口变化: {old} → {DEVICE}")
                _close_maacore_screenshot_bridge()
            # connect到新端口
            subprocess.run([ADB, "connect", DEVICE],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
            # 🔴 同步更新MAA gui.json连接地址 (2026-06-29: MAA用固定端口, MuMu端口变化时连不上)
            try:
                # MAA v6.14.1 的连接信息仍保存在gui.json；gui.new.json只保存TaskQueue。
                gui_json_path = os.path.join(MAA_CONFIG, "gui.json")
                with open(gui_json_path, 'r', encoding='utf-8') as f:
                    gcfg = json.load(f)
                cur_addr = gcfg["Configurations"]["Default"].get("Connect.Address", "")
                if cur_addr != DEVICE:
                    gcfg["Configurations"]["Default"]["Connect.Address"] = DEVICE
                    _atomic_write_json(gui_json_path, gcfg)
                    log(f"  [MAA] 连接地址已同步: {cur_addr} → {DEVICE}")
            except Exception as e:
                log(f"  ⚠️ 同步MAA连接地址失败: {e}", "WARN")
            return True
    except Exception as e:
        log(f"  ⚠️ 检测MuMu端口失败: {e}", "WARN")
    return False


def _foreground_mumu_display():
    """显示并前置既有MuMu VM；只重启显示外壳，不触碰游戏VM。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32

        def visible_mumu_windows():
            handles = []
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            @callback_type
            def collect(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                title = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title, length + 1)
                if "MuMu" in title.value or "模拟器" in title.value:
                    handles.append(int(hwnd))
                return True

            user32.EnumWindows(collect, 0)
            return handles

        mumu_handles = visible_mumu_windows()
        if not mumu_handles and os.path.exists(MUMU_PLAYER):
            # 实机验证：裸启动MuMuNxMain.exe只会留下“有进程、无窗口”的
            # 显示外壳；桌面快捷方式实际带--from-shortcut。先只清理这个
            # 无窗口外壳（不动MuMuVMMHeadless/游戏VM），再按快捷方式参数
            # 重开，才能把既有后台VM附着为可见窗口。
            subprocess.run(
                ["taskkill", "/f", "/im", "MuMuNxMain.exe"],
                capture_output=True,
                timeout=5,
            )
            subprocess.Popen(
                [MUMU_PLAYER, "--from-shortcut"],
                cwd=os.path.dirname(MUMU_PLAYER),
            )
            log("  [前台] 后台VM已运行，按桌面快捷方式参数补开MuMu显示窗口")
            for _ in range(10):
                wait(1)
                mumu_handles = visible_mumu_windows()
                if mumu_handles:
                    break
        if not mumu_handles:
            log("  [前台] 未发现可见MuMu窗口；保留后台VM，不伪报已前置", "WARN")
            return False
        mumu_hwnd = mumu_handles[0]
        user32.ShowWindow(mumu_hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(mumu_hwnd)
        log("  [前台] MuMu游戏画面已前置")
        return True
    except Exception as e:
        log(f"  [前台] MuMu窗口置顶失败: {e}", "WARN")
        return False


def ensure_env():
    """确保环境就绪: MuMu+ADB+游戏"""
    if not acquire_single_instance():
        return False
    # 更新/安装完整性必须在启动MuMu和进入任何战斗之前闭环。修复成功
    # 后仍由当前full/mainline模式继续，不得降级另起daily子流程。
    if not ensure_maa_install_ready(allow_recovery=True):
        log("❌ MAA环境自检未通过，未启动游戏、未消耗理智", "ERROR")
        return False
    # MAA进程存在不等于残留。任务队列仍在运行时必须保留并由mode_daily接管；
    # 只有GUI日志确认idle才可清理，以便下一阶段重载配置。
    if _maa_task_queue_running():
        log("  [环境恢复] 检测到MAA任务队列仍在运行，禁止清理进程")
    else:
        try:
            subprocess.run(["taskkill", "/f", "/im", "MAA.exe"], capture_output=True, timeout=5)
            log("  → 已清理空闲/残留MAA进程")
        except Exception:
            pass
    
    # 🔴 防御检查G01: 确认使用mumu-cli launch而非MuMuNxMain.exe
    detect_mumu_adb_port()
    
    # 检查ADB连接
    r = subprocess.run([ADB, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if DEVICE not in r.stdout:
        # 🔴 2026-06-30 严重bug修复: 用mumu-cli启动VM, 不是MuMuNxMain.exe!
        # 旧代码 subprocess.Popen([MUMU_PLAYER]) 只启动播放器窗口进程,
        # 但VM(is_android_started)不会启动, 导致ADB永远连不上, mainline/full模式全部失败
        # mode_daily用mumu-cli launch是正确的, ensure_env却用错了
        log("→ 启动MuMu VM (mumu-cli control launch)")
        try:
            _run_mumu("control", "-v", MUMU_VM_INDEX, "launch", timeout=30)
        except Exception as e:
            log(f"  ⚠️ mumu-cli launch失败: {e}, 回退到播放器窗口")
            subprocess.Popen([MUMU_PLAYER], cwd=os.path.dirname(MUMU_PLAYER))
        # 等待VM启动 (最多120s)
        for i in range(24):
            wait(5)
            # 每次重试前重新检测端口
            detect_mumu_adb_port()
            r = subprocess.run([ADB, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            # 检查设备是否连接且不是offline
            if DEVICE in r.stdout and "offline" not in r.stdout:
                log("✅ ADB已连接")
                break
            if i % 4 == 3:
                log(f"  等待MuMu启动... ({(i+1)*5}s)")
        else:
            log("❌ ADB连接超时(120s)", "ERROR")
            return False
    else:
        # 设备存在但可能offline
        if "offline" in r.stdout:
            log("⚠️ ADB设备offline, 重启ADB连接")
            subprocess.run([ADB, "disconnect", DEVICE], capture_output=True, timeout=5)
            wait(2)
            detect_mumu_adb_port()
            r = subprocess.run([ADB, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if DEVICE not in r.stdout or "offline" in r.stdout:
                log("→ ADB仍offline, 启动MuMu VM")
                try:
                    _run_mumu("control", "-v", MUMU_VM_INDEX, "launch", timeout=30)
                except Exception as e:
                    log(f"  ⚠️ mumu-cli launch失败: {e}")
                    subprocess.Popen([MUMU_PLAYER], cwd=os.path.dirname(MUMU_PLAYER))
                for i in range(20):
                    wait(5)
                    detect_mumu_adb_port()
                    r = subprocess.run([ADB, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace")
                    if DEVICE in r.stdout and "offline" not in r.stdout:
                        log("✅ ADB已连接")
                        break
                else:
                    log("❌ ADB仍offline", "ERROR")
                    return False
    
    # 检查游戏运行
    r = subprocess.run([ADB, "-s", DEVICE, "shell", "pidof", PKG], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not r.stdout.strip():
        log("→ 启动游戏")
        # 🔴 重试游戏启动 (最多3次), 处理device offline等临时问题
        for launch_attempt in range(3):
            # 重新检测端口
            detect_mumu_adb_port()
            lr = subprocess.run([ADB, "-s", DEVICE, "shell", "monkey", "-p", PKG, "-c",
                                "android.intent.category.LAUNCHER", "1"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            if "device offline" in lr.stderr or "error" in lr.stderr.lower():
                log(f"  ⚠️ 游戏启动失败(第{launch_attempt+1}次): {lr.stderr.strip()}")
                wait(5)  # 等待ADB恢复
                continue
            break  # 启动命令执行成功

        # 🔴 等待游戏加载 (增加到10次, 原来只有6次不够)
        for i in range(10):
            wait(15)
            try:
                state = get_state()
            except Exception:
                state = "unknown"
            if state == "announcement":
                # START 后经常先进入活动/系统公告覆盖层。get_state 已能明确
                # 识别该状态，启动循环必须立即处理；旧逻辑只在 unknown 时
                # 调 handle_popups，导致公告页每 15 秒空等一次直至整轮超时。
                log("  → 登录后检测到公告覆盖层，立即关闭")
                if handle_popups():
                    wait(3)
                    continue
                log("  ⚠️ 公告覆盖层未能关闭，保留本轮重试", "WARN")
            if state == "monthly_sign_in":
                log("  → 登录后检测到月度签到页，立即关闭")
                if _dismiss_reward_overlay_for_main_menu():
                    wait(3)
                    continue
                log("  ⚠️ 月度签到页未能关闭，保留本轮重试", "WARN")
            if state == "login":
                # 🔴 2026-07-05 修复: 在登录界面需要点击START按钮才能进入主界面
                log("  → 游戏在登录界面, 点击START按钮")
                tap(961, 1028)  # 黄色菱形START按钮
                wait(15)
                continue
            if state == "unknown" and handle_popups():
                # 今日配给/公告等首次登录弹窗处理后，立即重新判断，避免空等数分钟。
                wait(3)
                continue
            if state in ("main_menu", "home_screen"):
                if state == "home_screen":
                    log("  ⚠️ 游戏在桌面, 可能启动不完全, 再试一次")
                    subprocess.run([ADB, "-s", DEVICE, "shell", "monkey", "-p", PKG, "-c",
                                    "android.intent.category.LAUNCHER", "1"],
                                   capture_output=True, timeout=10)
                    continue
                break
            log(f"  [启动等待] 第{i + 1}/10次页面状态: {state}")
        else:
            log("⚠️ 游戏未完全启动, 继续执行(由_force_to_chapter_map处理)")
    
    handle_popups()
    
    # VM由mumu-cli启动后可能只有后台设备、没有播放器外壳。用户看不到游戏
    # 时，仅补开显示外壳（不是用它启动VM），再枚举真实MuMu窗口置前。
    _foreground_mumu_display()
    
    return True

# ============================================================
# 主入口
# ============================================================

def show_help():
    """显示帮助"""
    print("""
明日方舟全场景自动化引擎 v3.0
================================

用法:
  python arknights_auto.py --mode <模式> [选项]

模式:
  daily          每日日常任务 (StartUp+Infrast+Recruit+Mall+Award)
  mainline       主线推进 (磨难优先, 单核失败→多核)
  chapter17_sandbox 第17章沙盘补做 (仅沙盘，禁止回退普通/险地战斗)
  annihilation   每周剿灭闭环 (未确认达到周上限则优先)
  resource       资源关刷取
  event          活动刷取 (自动检测当前活动)
  event_verify   用户明确手动完成后，只读复核指定活动突袭并同步断点
  event_today    当前活动普通/突袭断点→BD-8用完理智→日常/基建收尾
  roguelike      肉鸽
  reclamation    生息演算-沙洲遗闻 (按预算轮数无存档刷繁荣点)
  security       保全派驻 (SSS, 每周期执行一次, 不消耗理智)
  full           完整流程 (每周剿灭→活动优先/主线→日常收尾)

选项:
  --stage <代码>    指定关卡 (资源关/活动)
  --times <次数>    刷取次数 (资源关/活动)
  --chapter <章号>  起始章节 (主线)
  --theme <主题>    肉鸽主题 (phantom/mizuki/sami/sarkaz/jiegarden；garden兼容界园)
  --force-annihilation      即使本周已有完成记录也重新核验剿灭
  --annihilation-times <次> 单次运行安全上限，自动流程默认5
  --daily-chain <链>       仅恢复指定日常链，可重复（仅daily；如Award）
  --reclamation-cycles <轮> 生息演算刷点轮数，当前清空馈赠预算默认440

示例:
  python arknights_auto.py --mode daily
  python arknights_auto.py --mode daily --daily-chain Award
  python arknights_auto.py --mode mainline --chapter 10
  python arknights_auto.py --mode chapter17_sandbox --stage 17-3
  python arknights_auto.py --mode resource --stage AP-5 --times 5
  python arknights_auto.py --mode event --stage act24side_09 --times 10
  python arknights_auto.py --mode event_verify --stage AD-EX-8
  python arknights_auto.py --mode roguelike --theme garden
  python arknights_auto.py --mode reclamation --reclamation-cycles 440
  python arknights_auto.py --mode reclamation --reclamation-cycles 9999 --reclamation-stop-at 11:15
  python arknights_auto.py --mode full

资源关代码:
  AP-5/AP-6  采购凭证    LS-6/LS-7  经验卡
  SK-5       技能书      CE-6       龙门币
  CA-5       技巧概要    PR-x-x     芯片
""")


def parse_cli_options(argv):
    """Parse CLI without silently swallowing unknown goal-changing options."""
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument("--mode", default="daily")
    parser.add_argument("--stage")
    parser.add_argument("--times", type=int, default=5)
    parser.add_argument("--chapter", type=int)
    parser.add_argument("--theme", default="garden")
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--force-annihilation", action="store_true")
    parser.add_argument("--annihilation-times", type=int)
    parser.add_argument("--daily-chain", action="append", default=[])
    parser.add_argument("--reclamation-cycles", type=int)
    parser.add_argument("--reclamation-stop-at")
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--exclude-job", action="append", default=[])
    try:
        options, unknown = parser.parse_known_args(list(argv or []))
    except (argparse.ArgumentError, SystemExit) as exc:
        return None, [str(exc)]
    if options.times < 1:
        unknown.append("--times必须大于0")
    if options.max_attempts < 1:
        unknown.append("--max-attempts必须大于0")
    if options.annihilation_times is not None and options.annihilation_times < 1:
        unknown.append("--annihilation-times必须大于0")
    if options.reclamation_cycles is not None and options.reclamation_cycles < 1:
        unknown.append("--reclamation-cycles必须大于0")
    allowed_daily_chains = {"StartUp", "Infrast", "Recruit", "Mall", "Award"}
    invalid_daily_chains = set(options.daily_chain) - allowed_daily_chains
    if invalid_daily_chains:
        unknown.append(f"--daily-chain无效: {sorted(invalid_daily_chains)}")
    if options.daily_chain and options.mode != "daily":
        unknown.append("--daily-chain仅适用于daily模式")
    if options.reclamation_stop_at:
        if options.mode != "reclamation":
            unknown.append("--reclamation-stop-at仅适用于reclamation模式")
        else:
            try:
                _next_daily_deadline(options.reclamation_stop_at)
            except ValueError as exc:
                unknown.append(f"--reclamation-stop-at无效: {exc}")
    return options, unknown


def _runtime_dependencies_ready():
    """Fail before opening MuMu when the selected Python lacks live-control deps."""
    missing = []
    for module_name in ("rapidocr_onnxruntime", "uiautomation"):
        try:
            __import__(module_name)
        except Exception as exc:
            missing.append(f"{module_name}({exc})")
    if missing:
        log(
            "❌ 当前Python运行环境缺少自动化组件，未启动MuMu: "
            + "、".join(missing),
            "ERROR",
        )
        return False
    log("✅ OCR/UIA运行依赖检查通过")
    return True

def main():
    global _RUN_SUMMARY, _LAST_MAA_RUN_LOG, _LAST_MAA_RUN_START_LINE, _LAST_VERIFICATION
    global _CURRENT_RUN_STARTED_AT, _CURRENT_RUN_EVIDENCE_BOUNDARY_READY
    global _DAILY_COMPLETION_NOT_BEFORE
    global _ACTIVE_EXECUTION_PLAN
    global LOG_FILE

    if len(sys.argv) < 2 or "--help" in sys.argv:
        show_help()
        return

    # 单实例锁必须早于任何共享状态变更：竞争失败的第二个进程不能关闭
    # 现有弹窗、清空活动实例的日志，亦不能启动日志窗或进入清理流程。
    if not acquire_single_instance():
        return

    # 单实例确认后、启动任何 GUI/模拟器之前清理历史截图。清理失败不阻断任务。
    _prune_nav_debug(force=True)

    _RUN_SUMMARY = {}
    _LAST_MAA_RUN_LOG = ""
    _LAST_MAA_RUN_START_LINE = 0
    _CURRENT_RUN_STARTED_AT = None
    _CURRENT_RUN_EVIDENCE_BOUNDARY_READY = False
    _LAST_VERIFICATION = {}
    _DAILY_COMPLETION_NOT_BEFORE = None
    _ACTIVE_EXECUTION_PLAN = None
    _NOTIFY_SENT.sent = False
    # 上一轮结果弹窗允许保留给用户查看，但新一轮启动必须先关闭它。
    # 否则旧pythonw在部分Windows环境会继续持有日志句柄，使日志无法重建。
    _close_existing_summary_popups(silent=True)
    # 🔴 2026-07-12: 每次运行清空日志, 避免报告读到上次运行的旧STAMINA记录
    preferred_log = LOG_FILE
    try:
        with open(preferred_log, 'w', encoding='utf-8') as f:
            f.write("")
    except PermissionError:
        # Windows上的旧日志查看器可能以拒绝写入的共享方式占用auto_run.log。
        # 日志展示故障不应阻断游戏任务，切到本轮独立日志并让后续报告、
        # 实时日志窗和证据解析统一跟随新路径。
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        LOG_FILE = os.path.join(BASE, "outputs", f"auto_run_{stamp}.log")
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("")
        log(f"⚠️ 标准日志被外部程序占用，本轮改用独立日志: {LOG_FILE}", "WARN")

    # 必须早于MAA更新/环境恢复。即使后续预检失败，日报也只能看到本轮日志。
    _initialize_current_run_evidence_boundary()

    options, unknown_args = parse_cli_options(sys.argv[1:])
    if options is None:
        log(f"❌ 命令行解析失败: {'; '.join(unknown_args)}", "ERROR")
        return
    mode = options.mode
    stage = options.stage
    times = options.times
    chapter = options.chapter
    theme = options.theme
    no_cleanup = options.no_cleanup
    force_annihilation = options.force_annihilation
    annihilation_times = options.annihilation_times
    reclamation_cycles = options.reclamation_cycles
    reclamation_stop_at = options.reclamation_stop_at
    daily_chains = set(options.daily_chain) if options.daily_chain else None
    target_max_attempts = options.max_attempts
    target_excluded_jobs = options.exclude_job
    
    log(f"启动模式: {mode}")

    plan = compile_execution_plan(
        mode,
        stage=stage,
        max_attempts=target_max_attempts,
        theme=theme,
        reclamation_cycles=reclamation_cycles,
        reclamation_stop_at=reclamation_stop_at,
        unknown_args=unknown_args,
    )
    if plan is None:
        log("❌ 本轮执行计划与项目契约冲突，未启动模拟器", "ERROR")
        return
    if not _runtime_dependencies_ready():
        return
    
    # 🔴 2026-06-30 防御检查第零层: 静态源码自检 (扫描自身代码防残留bug)
    guard_ok = _guard_static_scan()
    
    # 🔴 2026-06-30 Pre-Flight Checklist: 跨对话业务规则强制检查
    # 读取 BUSINESS_RULES.json, 验证所有用户反馈的业务逻辑错误不会复现
    preflight_ok = preflight_check()
    if not guard_ok or not preflight_ok:
        log("❌ 启动前安全检查存在致命失败，本轮已阻止执行", "ERROR")
        return

    start_log_viewer()

    # 执行对应模式 (任务完成后自动清理MAA+游戏)
    try:
        # 环境启动也属于自动化流程，必须放在默认清理保护区内；即使启动
        # 半途失败，也要关闭已打开的游戏/MAA/MuMu和实时日志窗。
        # daily 以前完全跳过 ensure_env；在上一流程已正常关闭 MuMu 后定向
        # 补跑 Award 会只对离线 ADB 连续发 monkey，白等 240 秒。只有确有
        # MAA 日常队列正在运行时才不触碰环境、直接由 mode_daily 接管日志。
        resume_running_daily = mode == "daily" and _maa_daily_queue_running()
        if not resume_running_daily and not ensure_env():
            log("❌ 环境就绪失败", "ERROR")
            return
        if not resume_running_daily and mode in (
            "daily", "full", "event_today", "mainline", "annihilation", "resource", "event"
        ):
            _capture_stamina_observation("start", navigate=True)

        if mode == "daily":
            mode_daily(enabled_tasks=daily_chains)
        elif mode == "mainline":
            mode_mainline(
                start_chapter=chapter,
                target_stage=stage,
                target_max_attempts=target_max_attempts,
                target_excluded_jobs=target_excluded_jobs,
            )
        elif mode == "chapter17_sandbox":
            mode_chapter17_sandbox(stage, max_attempts=target_max_attempts)
        elif mode == "annihilation":
            mode_annihilation()
        elif mode == "resource":
            mode_resource(stage_code=stage, times=times)
        elif mode == "event":
            mode_event(stage_code=stage, times=times)
        elif mode == "event_verify":
            mode_event_verify(stage_code=stage)
        elif mode == "event_today":
            mode_event_today()
        elif mode == "event_first_clear":
            mode_event_first_clear()
        elif mode == "roguelike":
            mode_roguelike(theme=theme)
        elif mode == "reclamation":
            mode_reclamation(
                target_cycles=reclamation_cycles,
                stop_at=reclamation_stop_at,
            )
        elif mode == "security":
            mode_security()
        elif mode == "full":
            mode_full(
                start_chapter=chapter,
                force_annihilation=force_annihilation,
                annihilation_times=annihilation_times,
            )
        else:
            log(f"❌ 未知模式: {mode}", "ERROR")
            show_help()
            return
    finally:
        # 🔴 任务完成(或异常退出)后关闭MAA和游戏, 释放资源
        # --no-cleanup: 组合执行时(剿灭→日常)中间步骤不cleanup, 保留MuMu给下一步
        # _SSS_NEED_MANUAL: 保全派驻需要手动编队, 不关游戏让用户操作
        if _SSS_NEED_MANUAL:
            log("→ ⚠️ 保全派驻需手动编队, 保留游戏和MuMu(不执行cleanup)")
            log("  用户手动编队完成后, 脚本会自动检测并启动MAA")
            log("  如需手动退出, 请关闭MuMu窗口即可")
        elif no_cleanup and mode in ("mainline", "chapter17_sandbox", "full", "annihilation", "resource", "event", "event_verify", "event_first_clear", "event_today", "roguelike", "reclamation", "security"):
            log("→ --no-cleanup: 保留MuMu和游戏(供后续步骤使用)")
        else:
            flow_paused = ((_RUN_SUMMARY.get("flow_control") or {}).get("status") == "paused")
            daily_tail_expected = mode in ("daily", "full", "event_today") and not flow_paused
            # 🔴 2026-06-30 主线视觉确认: mainline模式必须先验证体力消耗+关卡推进
            if mode == "mainline":
                _guard_check("G07", context="主线模式:cleanup前执行视觉确认",
                             condition=True)
                try:
                    verify_mainline_completion(start_chapter=chapter)
                    _guard_check("G07", context="主线视觉确认完成",
                                 condition=True)
                except Exception as e:
                    log(f"⚠️ 主线视觉确认异常: {e}", "WARN")
                    _guard_check("G07", context=f"视觉确认异常:{e}",
                                 condition=False)
            
            # 总收尾顺序固定：必要时领奖 → 截图验证 → cleanup → 报告 → 唯一弹窗。
            # 任何子步骤都无权弹窗；只有总控在所有工作结束后通知一次。
            
            # 1. daily/full 的最后一步已经是 MAA Award，不能再用失效坐标重复点两次。
            # 独立战斗模式才保留一次手动补领，并且 claim_daily_rewards 会严格验证任务页。
            try:
                if mode in ("mainline", "resource", "event"):
                    log(">>> 独立战斗模式：补领一次每日任务奖励...")
                    claim_daily_rewards()
                elif daily_tail_expected:
                    log(">>> MAA Award已作为日常收尾，跳过重复手动领奖")
                elif mode == "full" and flow_paused:
                    log(">>> 专项流程已暂停，跳过已执行过的最终日常与重复领奖")
            except Exception as e:
                log(f"⚠️ 领取每日任务异常: {e}", "WARN")
            
            # 2. 截图验证必须在游戏关闭前完成。
            if daily_tail_expected:
                try:
                    verify_daily_completion()
                except Exception as e:
                    log(f"⚠️ 截图验证异常: {e}", "WARN")
            else:
                log(">>> 本轮未执行最终日常，跳过日常完成截图验证")

            # 无论专项链是否暂停，游戏关闭前都必须读取一次实时理智。若失败，
            # 报告明确标为未核验，禁止用历史MAA日志或请求次数反推。
            if mode in (
                "daily", "full", "event_today", "mainline", "annihilation", "resource", "event"
            ):
                _capture_stamina_observation("final", navigate=True)

            # 3. 关闭全部自动化相关窗口和进程。生息演算遇到未经解释的
            # 暂停状态时必须保留现场；不能一边声称保留，一边由总控关窗。
            cleanup_error = None
            preserve_environment = bool(_RUN_SUMMARY.get("preserve_environment"))
            if mode == "reclamation" and flow_paused and preserve_environment:
                log("→ 生息演算异常现场已保留：不关闭游戏/MAA/MuMu，等待诊断或恢复")
            else:
                try:
                    cleanup_after_task(check_badges=daily_tail_expected)
                except Exception as e:
                    cleanup_error = str(e)
                    log(f"⚠️ 最终清理异常: {e}", "ERROR")

            # 4. cleanup后生成报告，进程状态才是最终真实状态。
            rep = generate_security_report() if mode == "security" else generate_daily_report(mode=mode)
            if cleanup_error:
                rep["has_error"] = True
                rep["cleanup_error"] = cleanup_error

            # 5. 整条日常任务链唯一允许出现弹窗的位置。沙盘补偿模式是内部
            # 零理智恢复子流程，只留独立报告，避免技术验证反复弹窗冒充日报。
            if mode not in ("chapter17_sandbox", "security"):
                try:
                    notify_completion(rep, final=True)
                except Exception as e:
                    log(f"⚠️ 弹出最终通知失败: {e}", "WARN")
            elif mode == "chapter17_sandbox":
                log("  [通知] 沙盘补偿模式不弹日报窗口，结果仅写入独立报告")
            else:
                log("  [通知] 保全派驻使用独立报告，不弹出日常完成窗口")

            # 6. 输出本轮防御检查总结报告
            _guard_report()

if __name__ == "__main__":
    main()




