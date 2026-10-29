"""Offline activity-room policy candidate. No ADB, MAA or config writes."""
from datetime import datetime


def fresh(row, at):
    try:
        seen, now = datetime.fromisoformat(row['observed_at']), datetime.fromisoformat(at)
        return seen.tzinfo is not None and now.tzinfo is not None and 0 <= (now-seen).total_seconds() <= 3600
    except (KeyError, TypeError, ValueError):
        return False


def integer(value):
    return type(value) is int and value >= 0


def upgrade_plan(rooms, inventory, *, at):
    """Select only one currently displayed upgrade, then require a fresh read.

    Costs come from the actual room preview, not a stale server/wiki table.
    Reserve drones when that is the only missing input to avoid daily spend
    preventing construction forever. Missing building materials defer only this
    feature; daily production remains independent.
    """
    result = {'status': 'unverified', 'action': None, 'production_enabled': False,
              'drone_policy': 'existing_manufacture_policy'}
    if not fresh(inventory, at):
        return dict(result, reason='inventory_not_fresh')
    candidates, pending, seen = [], [], set()
    for room in rooms:
        rid = room.get('room_id')
        if not rid or rid in seen:
            return dict(result, reason='duplicate_or_missing_room_id')
        seen.add(rid)
        if not fresh(room, at) or room.get('facility') != '活动室':
            pending.append({'room': rid, 'reason': 'room_identity_or_freshness_unknown'})
            continue
        level, cap = room.get('level'), room.get('max_level')
        if not integer(level) or not integer(cap) or not 0 < level <= cap:
            pending.append({'room': rid, 'reason': 'level_unknown_or_unbuilt'})
            continue
        if level == cap:
            continue
        preview = room.get('upgrade_preview') or {}
        costs = preview.get('costs')
        if (preview.get('target_level') != level+1 or preview.get('conditions_met') is not True
                or not isinstance(costs, dict) or not costs or 'drones' not in costs
                or not all(integer(v) for v in costs.values())):
            pending.append({'room': rid, 'reason': 'current_upgrade_preview_unverified'})
            continue
        stocks = inventory.get('counts', {})
        if any(not integer(stocks.get(k)) for k in costs):
            pending.append({'room': rid, 'reason': 'required_material_stock_unknown'})
            continue
        deficits = {k: v-stocks[k] for k, v in costs.items() if stocks[k] < v}
        item = {'room_id': rid, 'from_level': level, 'to_level': level+1,
                'costs': dict(costs), 'deficits': deficits}
        candidates.append(item)
    candidates.sort(key=lambda x: (-x['from_level'], x['room_id']))
    affordable = [x for x in candidates if not x['deficits']]
    if affordable:
        return dict(result, status='upgrade_proposal', action=affordable[0],
                    drone_policy='upgrade_first_then_reobserve_remaining', pending=pending)
    waiting = [x for x in candidates if set(x['deficits']) == {'drones'}]
    if waiting:
        return dict(result, status='waiting_for_drones', pending=pending,
                    next_upgrade=waiting[0], drone_policy='reserve_for_next_upgrade')
    return dict(result, status='pending_inputs' if pending or candidates else
                'observed_rooms_at_max' if rooms else 'no_rooms_observed',
                pending=pending, deferred=candidates)


def rotation_plan(rooms, roster, *, at, roster_complete):
    """Keep unfinished incumbents; replace full trust by stable low-trust order.

    Activity use is independent from the production station. It must never
    summon/remove operators from a working station. All rooms are supplied so
    duplicate operators or shared-trust alternatives are not invited twice.
    """
    out = {'status': 'unverified', 'assignments': [], 'pending': [],
           'production_enabled': False, 'remove_from_production': False}
    if roster_complete is not True:
        return dict(out, reason='operator_list_incomplete')
    people = {}
    for person in roster:
        oid, trust = person.get('operator_id'), person.get('trust_percent')
        if not oid or oid in people or not fresh(person, at) or not integer(trust) or trust > 200:
            return dict(out, reason='operator_identity_trust_or_freshness_unverified')
        people[oid] = person
    if len({r.get('room_id') for r in rooms}) != len(rooms):
        return dict(out, reason='duplicate_room')
    used, vacant = set(), []
    group = lambda p: p.get('trust_group') or p['operator_id']
    for room in sorted(rooms, key=lambda r: r.get('room_id', '')):
        rid = room.get('room_id')
        if not rid or not fresh(room, at) or room.get('facility') != '活动室':
            # An unread/stale room may already hold the next candidate. Do not
            # assign elsewhere using an incomplete occupancy picture.
            return dict(out, status='unverified', assignments=[],
                        reason='room_occupancy_unverified')
        if not integer(room.get('level')) or room['level'] < 1:
            continue
        current = room.get('operator_id')
        if current and current not in people:
            return dict(out, status='unverified', assignments=[], reason='incumbent_missing_in_roster')
        # A visible claim must be collected/verified before any replacement.
        if room.get('claimable_trust') is not False:
            out['pending'].append({'room': rid, 'reason': 'claim_first_or_state_unknown'})
            if current in people:
                used.add(group(people[current]))
            continue
        if current and people[current]['trust_percent'] < 200 and group(people[current]) not in used:
            used.add(group(people[current]))
            out['assignments'].append({'room_id': rid, 'operator_id': current, 'action': 'keep'})
        else:
            vacant.append(rid)
    candidates = sorted((p for p in people.values() if p['trust_percent'] < 200),
                        key=lambda p: (p['trust_percent'], p['operator_id']))
    for rid in vacant:
        selected = next((p for p in candidates if group(p) not in used), None)
        if selected:
            used.add(group(selected))
            out['assignments'].append({'room_id': rid, 'operator_id': selected['operator_id'],
                                       'action': 'invite_without_recall'})
        else:
            out['pending'].append({'room': rid, 'reason': 'no_underfull_trust_operator'})
    out['status'] = 'rotation_proposal'
    return out


def verify_upgrade(before, after):
    return (before.get('room_id') == after.get('room_id') and before.get('room_id') is not None
            and before.get('facility') == after.get('facility') == '活动室'
            and integer(before.get('level')) and integer(after.get('level'))
            and after['level'] == before['level']+1)
