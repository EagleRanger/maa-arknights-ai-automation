"""Offline activity-room upgrade/material planning. Never controls the game."""
from copy import deepcopy
from math import ceil

from activity_room_plan_v1 import fresh, integer, upgrade_plan as old_upgrade_plan


class MaterialGap(ValueError):
    pass


def synthesis_plan(required, inventory, recipes, *, at):
    """Plan only a net shortage using fresh observed recipes and shared stock.

    Each recipe row contains product_id, yield_count, inputs, observed_at,
    evidence, and available=True. Currency is an ordinary consumed input;
    drones can never be a synthesis input. Steps are dependency ordered, but
    callers must execute just the first step and reobserve before replanning.
    """
    result = dict(status='unverified', steps=[], game_inputs=0,
                  execution_enabled=False)
    if not fresh(inventory, at) or not isinstance(required, dict):
        return dict(result, reason='fresh_inventory_and_required_counts_needed')
    if any(not isinstance(k, str) or not integer(v) for k, v in required.items()):
        return dict(result, reason='invalid_required_counts')
    stock = deepcopy(inventory.get('counts', {}))
    book = {}
    for row in recipes:
        key = row.get('product_id')
        if not key or key in book:
            return dict(result, reason='duplicate_or_missing_recipe_product')
        book[key] = row
    steps = []

    def consume(key, quantity, stack):
        count = stock.get(key)
        if not integer(count):
            raise MaterialGap('unknown_stock:'+key)
        if quantity > count:
            if key in stack:
                raise MaterialGap('recipe_cycle:'+key)
            row = book.get(key)
            if not row:
                raise MaterialGap('raw_material_shortage:'+key)
            ingredients, produced = row.get('inputs'), row.get('yield_count')
            if (not fresh(row, at) or row.get('available') is not True
                    or not row.get('evidence') or not integer(produced) or produced == 0
                    or not isinstance(ingredients, dict) or not ingredients
                    or any(not isinstance(k, str) or not integer(v) or v == 0
                           for k, v in ingredients.items())):
                raise MaterialGap('recipe_unverified:'+key)
            if key == 'drones' or 'drones' in ingredients:
                raise MaterialGap('drone_synthesis_not_allowed')
            batches = ceil((quantity-count)/produced)
            inputs = {k: v*batches for k, v in ingredients.items()}
            for ingredient, amount in inputs.items():
                consume(ingredient, amount, stack+(key,))
            stock[key] += produced*batches
            steps.append(dict(product_id=key, batches=batches,
                              produced=produced*batches, inputs=inputs,
                              evidence=row['evidence']))
        stock[key] -= quantity

    try:
        for key, quantity in required.items():
            if quantity:
                consume(key, quantity, ())
    except MaterialGap as exc:
        # No prefix of a failed plan is approved for live execution.
        return dict(result, status='material_gap', reason=str(exc))
    return dict(result, status='synthesis_proposal' if steps else 'materials_ready',
                steps=steps, next_action=steps[0] if steps else None,
                projected_remaining=stock)


def all_rooms_max(rooms, *, at, rooms_complete):
    if rooms_complete is not True or not rooms:
        return False
    seen = set()
    for room in rooms:
        rid = room.get('room_id')
        if (not rid or rid in seen or room.get('facility') != '活动室'
                or not fresh(room, at) or not room.get('evidence')
                or not integer(room.get('level')) or room['level'] == 0
                or not integer(room.get('max_level'))
                or room['level'] != room['max_level']):
            return False
        seen.add(rid)
    return True


def upgrade_plan(rooms, inventory, recipes=(), *, at, rooms_complete=False):
    """Keep all drones reserved until the complete room set is verified max."""
    result = old_upgrade_plan(rooms, inventory, at=at)
    result.update(drone_policy='reserve_all_for_activity_upgrades',
                  production_acceleration_allowed=False, game_inputs=0)
    if all_rooms_max(rooms, at=at, rooms_complete=rooms_complete):
        result.update(status='all_activity_rooms_max_verified',
                      drone_policy='existing_manufacture_policy',
                      production_acceleration_allowed=True)
        return result
    if result['status'] == 'upgrade_proposal':
        return result
    if result['status'] == 'observed_rooms_at_max':
        return dict(result, status='room_inventory_incomplete',
                    reason='complete_fresh_room_set_required')
    # V1 returns early for a drone-only shortage. That must not hide the
    # independently synthesizable materials of another previewed room.
    # Reuse V1's per-room validation rather than guessing future-level costs.
    candidates = []
    seen = set()
    for room in rooms:
        rid = room.get('room_id')
        if not rid or rid in seen:
            return dict(result, status='unverified', reason='duplicate_or_missing_room_id')
        seen.add(rid)
        single = old_upgrade_plan([room], inventory, at=at)
        candidates.extend(single.get('deferred', []))
    candidates.sort(key=lambda item: (-item['from_level'], item['room_id']))
    # Only preview-verified V1 candidates are considered; no guessed costs.
    for candidate in candidates:
        required = {k: v for k, v in candidate['costs'].items() if k != 'drones'}
        proposal = synthesis_plan(required, inventory, recipes, at=at)
        if proposal['status'] == 'synthesis_proposal':
            return dict(result, status='synthesize_before_upgrade',
                        next_upgrade=candidate, synthesis=proposal)
        candidate['synthesis'] = proposal
    if candidates:
        result['deferred'] = candidates
    return result
