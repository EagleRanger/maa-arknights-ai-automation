"""Shadow-only stock/flow forecast. No guessed hourly rates or config writes.

Rate samples describe settled quantities and room-hours under the SAME roster
and product profile. Inventory deltas alone cannot prove production rates.
"""
from math import isfinite
from statistics import median
from .orchestration import timestamp


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def fit_rates(samples, at, *, profile, max_age_hours=168):
    groups, rejected = {}, []
    seen, measurements_seen = set(), set()
    for row in samples:
        try:
            identity = row['sample_id']
            start, end = timestamp(row['start']), timestamp(row['end'])
            hours, quantity = row['room_hours'], row['quantity']
            proof = row.get('evidence')
            key = (row.get('profile'), row.get('flow'), str(start), str(end), str(proof))
            if (identity in seen or key in measurements_seen or row.get('profile') != profile or row.get('verified') is not True
                or not row.get('evidence') or not row.get('settled') or start >= end
                or not 0 <= (at-end).total_seconds() <= max_age_hours*3600
                or not number(hours) or hours <= 0 or not number(quantity) or quantity < 0):
                raise ValueError('invalid/stale/duplicate sample')
            seen.add(identity)
            measurements_seen.add(key)
            groups.setdefault(row['flow'], []).append((quantity/hours, row['evidence']))
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({'sample_id': row.get('sample_id'), 'reason': str(exc)})
    rates = {}
    for flow, values in groups.items():
        measurements = [v for v, _ in values]
        rates[flow] = {'median': median(measurements), 'low': min(measurements),
                       'high': max(measurements), 'samples': len(values),
                       'sufficient': len(values) >= 2, 'evidence': [p for _, p in values]}
    return {'profile': profile, 'rates': rates, 'rejected': rejected}


def compare(stock, candidates, samples, *, at, profile, baseline, horizon_hours=24):
    """Compare only policy-admitted layouts, favour sustainable jade output.

Each candidate defines explicit per-room item flows. Negative coefficients are
consumption. Their conversion ratios must come from the admitted game recipe,
not invented here. Drones are excluded entirely while upgrades are pending.
"""
    at = timestamp(at)
    result = {'mode': 'shadow', 'applied': False, 'baseline': baseline,
              'recommended': baseline, 'rate_balance_verified': False,
              'candidates': [], 'reason': 'insufficient_verified_rates',
              'drone_policy': 'reserve_for_activity_room_upgrades'}
    try:
        age = (at-timestamp(stock['observed_at'])).total_seconds()
        valid = stock.get('verified') is True and stock.get('evidence') and 0 <= age <= 3600
    except (ValueError, TypeError, KeyError): valid = False
    if not valid:
        result['reason'] = 'fresh_inventory_required'
        return result
    if not number(horizon_hours) or not 0 < horizon_hours <= 48:
        raise ValueError('bounded forecast horizon required')
    fit = fit_rates(samples, at, profile=profile)
    result['fit'] = fit
    for plan in candidates:
        if plan.get('policy_admitted') is not True:
            continue
        if plan.get('jade_trade_rooms') != plan.get('shard_manufacture_rooms'):
            continue  # Preserve accepted paired-count policy; do not loosen it.
        if sum(plan.get('manufacture_rooms', {}).values()) != 3 or sum(plan.get('trade_rooms', {}).values()) != 3:
            continue
        projected = dict(stock.get('items') or {})
        net, problems = {}, []
        for flow in plan.get('flows', []):
            rate = fit['rates'].get(flow['rate']) or {}
            rooms = flow.get('rooms')
            if not rate.get('sufficient') or type(rooms) is not int or not 0 <= rooms <= 3:
                problems.append('rate:' + flow['rate']); continue
            for item, coefficient in flow['items'].items():
                if not number(coefficient) or not number(projected.get(item)):
                    problems.append('inventory_or_ratio:' + item); continue
                conservative = rate['low'] if coefficient >= 0 else rate['high']
                net[item] = net.get(item, 0) + coefficient * conservative * rooms
        if not plan.get('flows'): problems.append('missing_flows')
        for item, rate in net.items(): projected[item] += rate*horizon_hours
        feasible = not problems and all(number(v) and v >= 0 for v in projected.values())
        row = {'id': plan['id'], 'feasible': feasible, 'projected': projected,
               'net_per_hour': net, 'problems': problems}
        result['candidates'].append(row)
    eligible = [r for r in result['candidates'] if r['feasible']]
    if eligible:
        # Jade first, then reduce surplus gold. Stable baseline wins ties.
        selected = max(eligible, key=lambda r: (r['net_per_hour'].get('orundum', 0),
                       -r['projected'].get('gold', 0), r['id'] == baseline))
        result.update(recommended=selected['id'], reason='measured_shadow_comparison',
                      rate_balance_verified=True)
    return result
