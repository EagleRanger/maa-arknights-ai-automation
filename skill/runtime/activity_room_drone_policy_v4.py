"""Use admitted permanent room proof even when a tail skips base rotation."""
from contextlib import contextmanager
from copy import deepcopy
import activity_room_drone_policy_v3 as previous
import activity_room_inventory_v1 as rooms


@contextmanager
def boundary(app, *, observer=rooms.observe, accepted=None):
    # V3 lazily loaded even admitted proof only inside apply_single_plan_config.
    # A drone-only tail deliberately never calls that mutating rotation entry.
    with previous.boundary(app, observer=observer, accepted=accepted) as state:
        if rooms.complete(accepted or {}):
            state['proof'] = deepcopy(accepted)
            app._RUN_SUMMARY['activity_room_upgrade_observation'] = deepcopy(accepted)
            app._RUN_SUMMARY['activity_room_drone_policy'] = {
                'version': 'v4_admitted_proof_independent_of_rotation',
                'production_allowed': True, 'reason': 'all_eight_rooms_max'}
        yield state
