"""V12 activity dispatch candidate. Metadata selects targets, never proves clears."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re


class CopilotLookupUnverified(RuntimeError):
    """A failed search/download is not evidence that no job exists."""


def transient_game_login_error(text):
    compact = re.sub(r'\s+', '', str(text or ''))
    return ('登入时发生错误' in compact and '请重新尝试' in compact
            and re.search(r'错误号[:：]?0(?!\d)', compact) is not None)


def exact_name(value):
    return re.sub(r'[<>《》〈〉「」『』\s]', '', str(value or ''))


def discover_event(name, stories, maa_root, now=None):
    """Read current MAA calendar/navigation/tile metadata; no UI or downloads.

    Discover only normal chapters actually declared by MAA. Never infer EX open
    dates, challenge availability, farming priorities, or copied coordinates.
    Unsupported layouts return a developer-owned diagnostic, not a user choice.
    """
    normalized = exact_name(name)
    if not normalized:
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('timezone-aware time required')
    matches = []
    for story in stories or []:
        if exact_name(story.get('name')) != normalized:
            continue
        try:
            start = datetime.fromisoformat(story['start_utc'])
            end = datetime.fromisoformat(story['expire_utc'])
            if not start <= now < end:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        matches.append(story)
    result = {'name': name, 'kind': 'new', 'stages': [],
              '_discovery_status': 'metadata_unverified',
              '_discovery_reason': '没有唯一且当前有效的MAA活动日历匹配'}
    if len(matches) != 1:
        return result
    story = matches[0]
    prefix = str(story.get('key', ''))
    # Reruns have task-specific replay requirements: do not treat as first-clear.
    if not re.fullmatch(r'[A-Z]{1,6}', prefix):
        result['_discovery_reason'] = '活动类型/复刻任务表需要技术适配，不套用首通'
        return result
    root = Path(maa_root) / 'resource'
    try:
        tasks = json.loads((root / 'tasks' / 'Stages' / f'{prefix}.json').read_text(encoding='utf-8-sig'))
        overview = json.loads((root / 'Arknights-Tile-Pos' / 'overview.json').read_text(encoding='utf-8-sig'))
        entries = tasks[f'{prefix}-OpenOcr']['text']
        section = tasks[f'{prefix}ChapterTo{prefix}']['text']
        if not entries or not section or normalized not in {exact_name(x) for x in entries}:
            raise ValueError('MAA活动入口名称/篇章文字未闭环')
        by_code = {}
        tutorials = {}
        for row in overview.values():
            code = str(row.get('code', ''))
            is_tutorial = bool(re.fullmatch(re.escape(prefix) + r'-TR-[1-9]\d*', code))
            if not is_tutorial and not re.fullmatch(re.escape(prefix) + r'-[1-9]\d*', code):
                continue
            internal = row.get('stageId')
            filename = row.get('filename', '')
            tile = (root / 'Arknights-Tile-Pos' / filename).resolve()
            if not filename or not tile.is_relative_to((root / 'Arknights-Tile-Pos').resolve()):
                raise ValueError('invalid tile path')
            if not internal or not tile.is_file():
                raise ValueError(f'{code}缺少实际MaaCore地图文件')
            destination = tutorials if is_tutorial else by_code
            if code in destination and destination[code]['internal'] != internal:
                raise ValueError(f'{code}内部关卡映射冲突')
            destination[code] = {'display': code, 'internal': internal, 'modes': ['normal']}
        if not by_code:
            raise ValueError('MAA未提供可确认的普通战斗地图')
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result['_discovery_reason'] = str(exc)
        return result
    result.update({
        'start': datetime.fromisoformat(story['start_utc']).astimezone().replace(tzinfo=None).isoformat(),
        'end': datetime.fromisoformat(story['expire_utc']).astimezone().replace(tzinfo=None).isoformat(),
        'entry_keywords': list(entries), 'combat_keywords': list(section),
        'section_keywords': {'normal': list(section)}, 'stage_prefix': prefix,
        'stages': sorted(by_code.values(), key=lambda row: int(row['display'].split('-')[-1])),
        'first_clear_modes': ['normal'], 'farm_stage': None,
        'tutorial_stages': list(tutorials.values()),
        # Farming and reward-page targets remain independently verified inputs.
        '_discovery_status': 'ready_for_visual_navigation',
        '_discovery_reason': 'MAA元数据已匹配；尚不代表图形验证或通关',
        '_source': 'MAA StageActivityV2 + Stages + Arknights-Tile-Pos',
    })
    # Only this prerequisite order is supported by today's actual SR map.
    # Other events retain discoverable tutorial nodes without inventing order.
    if prefix == 'SR' and 'SR-TR-1' in tutorials and 'SR-1' in by_code:
        result['prerequisite_stages'] = [dict(tutorials['SR-TR-1'], before='SR-1', kind='tutorial')]
    if prefix == 'SR':
        # 2026-09-05实机：旅行计划的一键领取后货币170→320、前三关待领消失。
        result['task_keywords'] = ['旅行计划']
    return result


def after_first_clear(result, farm_verified=None):
    """Classify availability separately from errors; always allow final daily.

    None means farming has not been visually checked; False means directly
    confirmed not cleared. A failed navigation must be handled as an error by
    the caller, never passed here as a confirmed negative.
    """
    if result == 'automation_unavailable':
        return 'fallback_mainline'
    if result in ('deferred_ex_job', 'deferred_event_job'):
        if farm_verified is True:
            return 'event_farm'
        if farm_verified is False:
            return 'fallback_mainline'
        return 'verify_farm'
    if result is True:
        return 'event_farm'
    if result == 'stamina_exhausted':
        return 'final_daily'
    return 'technical_stop'


def choose_activity_material(event, tip):
    """User policy: current activity's lowest fresh stock, never guessed stock."""
    if not (tip or {}).get('depot', {}).get('fresh'):
        return None
    matching = [s for s in tip.get('active_side_stories', [])
                if exact_name(s.get('name')) == exact_name(event.get('name'))]
    if len(matching) != 1:
        return None
    configured = {s['display'] for s in event.get('stages', [])}
    options = [s for s in matching[0].get('stages', [])
               if s.get('stage') in configured and s.get('drop_id')
               and type(s.get('inventory')) is int and s['inventory'] >= 0]
    return min(options, key=lambda s: (s['inventory'], s['stage'])) if options else None
