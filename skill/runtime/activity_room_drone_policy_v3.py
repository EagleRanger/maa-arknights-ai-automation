"""Conditional drones with an order-independent, canonical usage verifier.

Import before entering the legacy daily contexts. Both the module symbol and
the effective call site are replaced; a captured reservation function is never
mistaken for the normal production verifier. No game actions at installation.
"""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
import activity_room_drone_reservation_v1 as old
import activity_room_inventory_v1 as rooms
from daily_base_333_drones_v1 import verify_usage as NORMAL_VERIFY

RESERVATION_VERIFY = old.reservation_evidence
RESERVED_PAYLOAD = old.reserved_payload
if NORMAL_VERIFY.__module__ != 'daily_base_333_drones_v1':
    raise RuntimeError('import_drone_policy_before_legacy_contexts')


@contextmanager
def boundary(app, *, observer=rooms.observe, accepted=None):
    import daily_base_333_verified_execution_v1 as base
    import daily_base_333_drones_v1 as drones
    original_apply = base.apply_single_plan_config
    state = {'proof': None}

    def apply(runtime, decision):
        if runtime._maa_task_queue_running() is not False:
            raise RuntimeError('base_queue_not_idle')
        if state['proof'] is None:
            state['proof'] = deepcopy(accepted) if rooms.complete(accepted or {}) else observer(runtime)
            runtime._RUN_SUMMARY['activity_room_upgrade_observation'] = state['proof']
            allowed = rooms.complete(state['proof'])
            runtime._RUN_SUMMARY['activity_room_drone_policy'] = {
                'version': 'v3_effective_verifier', 'production_allowed': allowed,
                'reason': 'all_eight_rooms_max' if allowed else 'room_upgrade_evidence_incomplete'}
        if state['proof'].get('home_verified') is not True:
            runtime._RUN_SUMMARY.setdefault('base_333', {}).update(
                status='failed', reason='room_observation_return_unverified')
            return False
        return original_apply(runtime, decision)

    def payload(value):
        if not rooms.complete(state['proof'] or {}):
            return RESERVED_PAYLOAD(value)
        result = deepcopy(value)
        result['activity_room_drone_policy'] = 'existing_manufacture_policy'
        return result  # Preserve independently disabled allocations.

    def usage(before, after, log):
        verify = NORMAL_VERIFY if rooms.complete(state['proof'] or {}) else RESERVATION_VERIFY
        return verify(before, after, log)

    with patch.object(base, 'apply_single_plan_config', apply), \
         patch.object(old, 'reserved_payload', payload), \
         patch.object(old, 'reservation_evidence', usage), \
         patch.object(drones, 'verify_usage', usage):
        yield state
