"""Current SSS cycles, reward domains and local MAA region candidates.

Calendar information invalidates old progress, never the daily entry itself.
MAA jobs provide candidate names only; a current game page must show a region
before it can be selected. This module does not start battles or spend cards.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

CST = timezone(timedelta(hours=8))
RULE_SOURCES = {
    'cycle': 'https://prts.wiki/w/保全派驻',
    'current_season': 'https://ak.hypergryph.com/news/6246',
    'maa': 'https://docs.maa.plus/zh-cn/protocol/sss-schema.html',
}


def reward_window(now=None):
    now = now or datetime.now(CST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=CST)  # project/game timestamps are CST
    now = now.astimezone(CST)
    start = now.replace(day=16, hour=4, minute=0, second=0, microsecond=0)
    if now < start:
        previous = now.replace(day=1)-timedelta(days=1)
        start = previous.replace(day=16, hour=4, minute=0, second=0, microsecond=0)
    end = (start.replace(day=28)+timedelta(days=4)).replace(day=16)
    return {'id': f'reward-{start:%Y-%m-%dT%H:%M}',
            'start': start.isoformat(), 'end': end.isoformat(),
            'refresh_day': 16, 'refresh_hour': 4, 'timezone': 'Asia/Shanghai'}


def reconcile_cycles(previous, current, now=None):
    """Keep historical clears, but never inherit current-cycle completion."""
    cycle = reward_window(now)
    area = current.get('area_period')
    area_verified = bool(area and not area.startswith('unverified-'))
    return {
        'reward_cycle': cycle['id'], 'next_reward_refresh': cycle['end'],
        'reward_cycle_changed': previous.get('reward_cycle') != cycle['id'],
        'area_period': area if area_verified else None,
        'area_period_changed': area_verified and previous.get('area_period') != area,
        'reward_counts': current.get('reward_counts', {}),
        'historical_regions': list(previous.get('completed_regions') or []),
        'must_inspect_tasks': True, 'must_inspect_region_records': True,
        'daily_entry_expired': False,
    }


def summarize(counts, tasks, records, regions):
    """Capped monthly drops do not imply task/record reward completion."""
    capped = counts.get('strip') == 60 and counts.get('device') == 24
    tasks_verified = tasks.get('verified') is True and tasks.get('claimable') == 0
    records_verified = bool(regions) and all(
        (records.get(region) or {}).get('verified') is True
        and (records.get(region) or {}).get('claimable') == 0 for region in regions)
    objectives_complete = tasks.get('incomplete') == 0 if tasks_verified else False
    record_objectives_remaining=[name for name in regions if any(
        row.get('state')=='incomplete' for row in (records.get(name) or {}).get('rows',{}).values())]
    return {'monthly_capped': capped, 'task_rewards_checked': tasks_verified,
            'region_rewards_checked': records_verified,
            'available_rewards_serviced': tasks_verified and records_verified,
            'complete': capped and tasks_verified and records_verified and objectives_complete and not record_objectives_remaining,
            'record_objectives_remaining':record_objectives_remaining,
            'tasks_remaining': tasks.get('incomplete'),
            'task_objectives_complete': objectives_complete}


def normalize_name(value):
    return re.sub(r'[\s_\-－—·]', '', str(value)).casefold()


def matching_visible_regions(items, catalog):
    """Exact OCR candidate names; exclude the top/right equipment overlay."""
    found = []
    for text, x, y in items:
        if not (100 <= x <= 1380 and 180 <= y <= 900):
            continue
        key = normalize_name(text)
        for name, info in catalog.items():
            if key in {normalize_name(name), *(normalize_name(a) for a in info.get('aliases', []))}:
                if name not in found:
                    found.append(name)
    return found


def local_job_catalog(copilot_root):
    """Read current MAA data, including re-runs in old/, without executing it."""
    root = Path(copilot_root)
    catalog = {}
    if not root.is_dir():
        return catalog
    for path in sorted(root.rglob('*.json'), key=lambda p: ('old' in p.parts, str(p))):
        try:
            if path.stat().st_size > 5_000_000:
                continue
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        except (ValueError, OSError):
            continue
        if not isinstance(data, dict) or data.get('type') != 'SSS':
            continue
        name = str(data.get('stage_name') or '').strip()
        stages = data.get('stages')
        if not name or len(name) > 100 or not isinstance(stages,list) or len(stages) != 6:
            continue
        info = catalog.setdefault(name, {'dir': '', 'aliases': [], 'jobs': [],
                                         'source': 'maa_local_candidate_only'})
        info['jobs'].append(path.relative_to(root).as_posix())
    return catalog


def merged_catalog(existing, discovered):
    """Prefer real local paths, retaining curated aliases and online fallbacks."""
    result={name:dict(info) for name,info in existing.items()}
    for name, info in discovered.items():
        old=result.get(name,{})
        fallback=[(Path(old.get('dir',''))/p).as_posix() for p in old.get('jobs',[])]
        result[name]={**old, **info, 'aliases': list(old.get('aliases',[])),
                      'jobs':list(dict.fromkeys(info['jobs']+fallback))}
    return result


def task_rows(items):
    """Return explicit claim buttons only, never click 已领取 or 未完成."""
    claim = []
    claimed = []
    incomplete = []
    for text, x, y in items:
        token = re.sub(r'\s+', '', text)
        if token in ('领取', '领取奖励', '领取报酬', '一键领取', '全部领取'):
            claim.append((text, x, y))
        elif token in ('已领取', '报酬已领取'):
            claimed.append((text, x, y))
        elif token in ('未完成', '进行中', '未达成'):
            incomplete.append((text, x, y))
    return {'buttons': claim, 'claimed': claimed, 'incomplete': incomplete}


def task_cards(items):
    """Read fully visible #12 cards, retaining unmet objectives separately.

    Card bounds come from each REWARD caption, not fixed screen positions.
    Partial edge cards are excluded and covered by the overlapping next view.
    """
    cards=[]
    anchors=[(x,y) for t,x,y in items if str(t).upper().startswith('REWAR') and 770<y<860]
    for ax,ay in anchors:
        left,right=ax-110,ax+390
        if left<35 or right>1890:
            continue
        rows=[(t,x,y) for t,x,y in items if left<x<right and 460<y<720]
        title=''.join(t for t,x,y in sorted(rows,key=lambda r:r[2])
                      if 590<y<710 and t not in ('已领取','领取','领取奖励'))
        state='unknown'
        if any(t=='已领取' for t,x,y in rows):
            state='claimed'
        elif task_rows(rows)['buttons']:
            state='claimable'
        else:
            for t,x,y in rows:
                m=re.fullmatch(r'(\d+)\s*/\s*(\d+)',t)
                if m and int(m[1])<int(m[2]):
                    state='incomplete'
        cards.append({'title':title,'state':state,'bounds':[left,right]})
    return cards


def view_fingerprint(items, box):
    """Semantic viewport identity, excluding animated artwork and timers."""
    x1,y1,x2,y2=box
    return tuple(sorted((re.sub(r'\s+','',t),round(x/25),round(y/25))
                        for t,x,y in items if x1<x<x2 and y1<y<y2))
