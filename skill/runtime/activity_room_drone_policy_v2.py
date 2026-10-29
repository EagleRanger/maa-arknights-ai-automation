"""Conditional replacement for the unconditional V1 drone reservation."""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
import activity_room_drone_reservation_v1 as old
import activity_room_inventory_v1 as rooms


@contextmanager
def boundary(app, *, observer=rooms.observe, accepted=None):
    import daily_base_333_verified_execution_v1 as base
    import daily_base_333_drones_v1 as drones
    original_apply, reserve, verify = base.apply_single_plan_config, old.reserved_payload, drones.verify_usage
    state = {'proof': None}

    def apply(runtime, decision):
        if runtime._maa_task_queue_running() is not False:
            raise RuntimeError('base_queue_not_idle')
        if state['proof'] is None:
            # accepted is a project-admitted source-bound permanent upgrade proof,
            # not a user statement or a candidate's successful unit test.
            state['proof'] = deepcopy(accepted) if rooms.complete(accepted or {}) else observer(runtime)
            runtime._RUN_SUMMARY['activity_room_upgrade_observation'] = state['proof']
            runtime._RUN_SUMMARY['activity_room_drone_policy'] = {
                'version': 'v2_conditional', 'production_allowed': rooms.complete(state['proof']),
                'reason': 'all_eight_rooms_max' if rooms.complete(state['proof']) else 'room_upgrade_evidence_incomplete'}
        if state['proof'].get('home_verified') is not True:
            runtime._RUN_SUMMARY.setdefault('base_333', {}).update(status='failed', reason='room_observation_return_unverified')
            return False
        return original_apply(runtime, decision)

    def payload(value):
        if not rooms.complete(state['proof'] or {}):
            return reserve(value)
        result = deepcopy(value)
        result['activity_room_drone_policy'] = 'existing_manufacture_policy'
        # Do not force enable: preserve an independent disabled allocation.
        return result

    def usage(before, after, log):
        if rooms.complete(state['proof'] or {}):
            return verify(before, after, log)
        return old_verify(before, after, log)

    old_verify = old.reservation_evidence
    with patch.object(base, 'apply_single_plan_config', apply), \
         patch.object(old, 'reserved_payload', payload), patch.object(old, 'reservation_evidence', usage):
        yield state
