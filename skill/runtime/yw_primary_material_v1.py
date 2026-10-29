"""Current-stock choice across all inspected YW normal primary drops."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "outputs/yw_20261009/candidates/catalog.json"
CATALOG_SHA = "F0BE6E6663C6C75B08549FAEC9FEFD37A08475FF2B9AFC68EEFF0B838516E264"

RANK = {"ALWAYS": 5, "ALMOST": 4, "USUAL": 3, "OFTEN": 2, "SOMETIMES": 1, "RARE": 0}
NAMES = {"30011": "源岩", "30012": "固源岩", "30022": "聚酸酯", "30052": "糖",
         "30063": "全新装置", "31063": "转质盐组", "31103": "液化高能气体"}


def primary_candidates(catalog):
    candidates = []
    for stage in catalog["stages"]:
        if not re.fullmatch(r"YW-[1-8]", stage["code"]):
            continue
        drops = [r for r in stage["stageDropInfo"]["displayDetailRewards"]
                 if r["type"] == "MATERIAL" and r["dropType"] == "NORMAL"]
        if not drops:
            continue
        highest = max(RANK.get(r["occPercent"], -1) for r in drops)
        primary = [r for r in drops if RANK.get(r["occPercent"], -1) == highest]
        if highest < RANK["USUAL"] or len(primary) != 1:
            continue  # Do not call occasional or ambiguous byproducts primary.
        drop = primary[0]
        candidates.append(dict(stage=stage["code"], drop_id=drop["id"],
                               drop=NAMES.get(drop["id"], drop["id"]),
                               primary_frequency=drop["occPercent"], cost=stage["apCost"]))
    return candidates


def choose(catalog, tip):
    depot = (tip or {}).get("depot") or {}
    if depot.get("fresh") is not True:
        return None
    candidates = primary_candidates(catalog)
    counts = depot.get("counts") or {}
    if not candidates or any(type(counts.get(r["drop_id"])) is not int or counts[r["drop_id"]] < 0
                             for r in candidates):
        return None  # Missing is unknown; it is not a false zero or excluded need.
    options = [dict(row, inventory=counts[row["drop_id"]]) for row in candidates]
    selected = min(options, key=lambda r: (r["inventory"], r["cost"], r["stage"]))
    return dict(selected, comparison=options, policy="lowest_current_stock_among_all_YW_primary_drops")


def normalize_orirock(tip, *, now=None):
    """User-confirmed exception: fresh completed scan omitting cube means 0.

    Only material 30012 receives this rule. Stale/failed scans and explicit
    malformed values remain unknown; the raw MAA cache is never overwritten.
    """
    now = now or datetime.now(timezone.utc)
    depot = (tip or {}).get('depot') or {}
    try:
        synced = datetime.fromisoformat(depot['sync_time'])
        current = synced.tzinfo is not None and 0 <= (now-synced).total_seconds() <= 3600
    except (KeyError, TypeError, ValueError):
        current = False
    counts = depot.get('counts') or {}
    if depot.get('fresh') is not True or not current or '30012' in counts:
        return tip
    result = deepcopy(tip)
    result['depot']['counts']['30012'] = 0
    result['depot'].setdefault('count_basis', {})['30012'] = {
        'value': 0, 'raw_entry_absent': True,
        'authority': 'user_confirmed_depleted_orirock_cube_20261010',
        'sync_time': depot['sync_time'],
    }
    return result


def current_choice(event, tip, *, now=None):
    from yw_event_intake_v1 import canonical_name, event_config
    if canonical_name(event.get("name")) != "昨日海" or event.get("stage_prefix") != "YW":
        return None
    now = now or datetime.now(timezone.utc)
    raw = CATALOG.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != CATALOG_SHA:
        return None
    catalog = json.loads(raw)
    event_config(catalog, now)
    depot = (tip or {}).get("depot") or {}
    try:
        synced = datetime.fromisoformat(depot["sync_time"])
        if synced.tzinfo is None or not 0 <= (now - synced).total_seconds() <= 3600:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    normalized = normalize_orirock(tip, now=now)
    selected = choose(catalog, normalized)
    if selected:
        selected.update(inventory_sync_time=synced.isoformat(),
                        requires_live_three_star_and_cost=True,
                        inventory_basis=(normalized.get('depot') or {}).get('count_basis', {}))
    return selected


@contextmanager
def boundary(runtime):
    import event_availability_v12 as availability
    original = availability.choose_activity_material
    original_tip = runtime.build_maa_daily_stage_tip

    def current_tip(*args, **kwargs):
        return normalize_orirock(original_tip(*args, **kwargs), now=kwargs.get('now'))

    def choose_for_event(event, tip):
        if event.get("stage_prefix") == "YW":
            return current_choice(event, tip)
        return original(event, tip)

    with patch.object(availability, "choose_activity_material", choose_for_event), \
         patch.object(runtime, "build_maa_daily_stage_tip", current_tip):
        yield
