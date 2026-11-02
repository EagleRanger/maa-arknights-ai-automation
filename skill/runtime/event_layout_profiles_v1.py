"""Activity detail observations. Readers never navigate, spend or certify clears."""
from dataclasses import dataclass
import re
import unicodedata
from typing import Callable

from PIL import Image
from arknights_daily_runtime_v12 import _event_normal_badges_ratio as ordinary_badges
from stage_sanity_cost_router_v1 import normal_cost
from stage_sanity_cost_yw_v3 import read_cost as yw_cost
from run_yw_stage_v1 import yw_badge_ratio

CODE = re.compile(r'(?:[A-Z0-9]+-){1,3}[0-9]+')
NORMAL = re.compile(r'[A-Z][A-Z0-9]*-[0-9]+')


@dataclass(frozen=True)
class Panel:
    header: tuple = (1200, 90, 1680, 230)
    start: tuple = (1550, 930, 1920, 1030)
    proxy: tuple = (1550, 840, 1900, 930)


@dataclass(frozen=True)
class Profile:
    key: str
    cost: Callable
    badges: Callable
    panel: Panel = Panel()
    stage_pattern: str = ''  # empty = shared standard panel
    catalog_prefix: str = ''
    activity: str = ''


ORDINARY = Profile('normal_right_panel_v1', normal_cost, ordinary_badges)
YW = Profile('normal_right_panel_yw_consensus_v3', yw_cost, yw_badge_ratio,
             stage_pattern=r'YW-[1-8]', catalog_prefix='act52side_', activity='昨日海')
PROFILES = {p.key: p for p in (ORDINARY, YW)}


def clean(value):
    return unicodedata.normalize('NFKC', str(value)).strip().upper()


def labels(rows, box):
    left, top, right, bottom = box
    return [clean(t) for t,x,y in rows if left <= x <= right and top <= y <= bottom]


def identify(items, *, expected=None, event=None):
    rows = list(items)
    # Reserve specialized readers before trying the default. A known stage with
    # a new instance or missing visual evidence cannot downgrade to the default.
    candidates = set()
    for profile in PROFILES.values():
        candidates.update(t for t in labels(rows, profile.panel.header)
                          if CODE.fullmatch(t) and (not profile.stage_pattern or
                                                      re.fullmatch(profile.stage_pattern, t)))
    codes = sorted(candidates)
    obs = dict(profile=None, header_codes=codes)
    def reject(reason):
        return dict(obs, reason=reason)
    if len(codes) != 1:
        return reject('ambiguous_or_missing_detail_header')
    code = codes[0]
    obs['stage'] = code
    if expected and code != clean(expected):
        return reject('target_mismatch')
    event = event or {}
    if expected and not NORMAL.fullmatch(code):
        return reject('not_normal_farm_mode')
    if (event.get('zero_sanity') or event.get('classification')=='zero_sanity_special_event'
            or str(event.get('kind', '')).startswith('zero_sanity')):
        return reject('special_activity_outside_normal_farm')
    if event.get('stage_prefix') and code.split('-')[0] != clean(event['stage_prefix']):
        return reject('activity_mismatch')
    catalog = event.get('stages')
    entries = [r for r in catalog or [] if r.get('display') == code]
    if catalog is not None and (len(entries) != 1 or
            ('modes' in entries[0] and 'normal' not in entries[0]['modes'])):
        return reject('activity_stage_not_unique_or_not_normal')
    special = [p for p in PROFILES.values() if p.stage_pattern and re.fullmatch(p.stage_pattern, code)]
    if len(special) > 1:
        return reject('ambiguous_layout_profile')
    p = special[0] if special else ORDINARY
    if special and event:
        sid = entries[0].get('internal') if entries else None
        if not (str(sid).startswith(p.catalog_prefix) if sid and p.catalog_prefix
                else p.activity and p.activity == event.get('name')):
            return reject('unverified_special_instance')
    header = [s for s in labels(rows, p.panel.header) if CODE.fullmatch(s)]
    starts = labels(rows, p.panel.start).count('开始行动')
    proxies = [s for s in labels(rows, p.panel.proxy) if s in ('代理指挥', '代理指挥+')]
    challenge = any('附加条件' in str(t) or '开始突袭' in str(t) for t,x,y in rows if x >= 1200)
    obs.update(candidate=p.key, normal_start=starts, proxy_labels=proxies, challenge=challenge)
    if challenge:
        return reject('not_normal_farm_mode')
    if header != [code] or starts != 1 or len(proxies) != 1:
        return reject('unmatched_detail_controls')
    return dict(obs, profile=p.key, reason='anchors_matched')


def price(observation, path, items, recognizer):
    p = PROFILES.get(observation.get('profile'))
    if not p:
        return None
    if not recognizer and any('+' in s for s in observation['proxy_labels']):
        return None
    # If the full frame already exposes a multiplier, a crop must not silently
    # override a contradiction or turn the batch total into a unit price.
    batch = p is ORDINARY and '+' in observation['proxy_labels'][0]
    factors = {int(t.lstrip('×X').strip()) for t in labels(items,(1480,860,1560,920))
               if re.fullmatch(r'[×X]?\s*\d{1,2}',t)} if batch else set()
    totals = {int(s[1:].strip()) for s in labels(items,(1600,1000,1920,1080))
              if re.fullmatch(r'[-−–]\s*\d{1,4}',s)} if factors else set()
    if factors and (len(factors)!=1 or len(totals)!=1 or not 1<=min(factors)<=99 or
                    min(totals)%min(factors)):
        return None
    reading = p.cost(path, items, recognizer)
    if reading and factors and reading['multiplier'] not in factors:
        return None
    return dict(reading, stage=observation['stage'], layout_profile=p.key) if reading else None


def inspect_frame(path, items, event, expected):
    obs = identify(items, expected=expected, event=event)
    try:
        with Image.open(path) as frame:
            obs['frame_size'] = list(frame.size)
            if frame.size != (1920, 1080):
                obs.update(profile=None, reason='unsupported_frame_geometry')
    except (OSError, ValueError):
        obs.update(profile=None, reason='frame_unreadable')
    return obs
