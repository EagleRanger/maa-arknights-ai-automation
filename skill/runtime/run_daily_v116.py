"""Normal-daily candidate: preserve recent repairs plus weekly-failure diagnosis.

Not a new scheduler. --check-only is offline. A real invocation is restricted
to the existing handoff's natural daily validation, not an immediate test.
"""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from unittest.mock import patch
import argparse
import sys
import run_daily_v115 as previous
from run_daily_v112 import check_entry as PRODUCTION_CHECK
from run_daily_v103 import ROOT, read, sha
from annihilation_rotation_v1 import boundary

ENTRYPOINT = 'run_daily_v116.py --mode full'
COMPONENT = 'ARK-ANNIHILATION-ROTATION-V1-CANDIDATE'
LOCAL = timezone(timedelta(hours=8))


@contextmanager
def retain_recent_event_fix():
    """Keep the already-tested museum zero-cost classification at final install.

    Do not call yesterday's stamina-only continuation or replay its effects.
    """
    import event_signin_discovery_v6 as signin
    import zero_sanity_event_policy_v3 as zero
    original = signin.install
    saved = []
    def install(app):
        result = original(app)
        names = ('_non_stamina_activity_from_name', 'detect_terminal_limited_event',
                 '_zero_sanity_event_policy_v3_installed')
        saved.append((app, {name: getattr(app, name, None) for name in names}))
        zero.install(app)
        return result
    try:
        with patch.object(signin, 'install', install):
            yield
    finally:
        for app, values in reversed(saved):
            for name, value in values.items():
                if value is None:
                    if hasattr(app, name): delattr(app, name)
                else:
                    setattr(app, name, value)


def check_entry(at=None, packet=None):
    # Validate the unchanged current production graph as well as this overlay;
    # never relabel candidate bytes as an already-verified production recipe.
    result = PRODUCTION_CHECK(at)
    registry = read(ROOT / '.project-reasoning/COMPONENTS.json')
    component = next(row for row in registry['components'] if row['id'] == COMPONENT)
    if component['status'] != 'validation_only':
        raise ValueError('rotation candidate identity changed')
    by_id = {row['id']: row for row in registry['components']}
    pending, checked = [COMPONENT], set()
    while pending:
        cid = pending.pop()
        if cid in checked:
            continue
        row = by_id[cid]
        if row['status'] not in {'verified', 'validation_only'}:
            raise ValueError('rotation dependency unavailable: ' + cid)
        for artifact in row.get('artifacts', []):
            if artifact['kind'] == 'file' and sha(ROOT / artifact['path']) != artifact['sha256'].upper():
                raise ValueError('rotation candidate artifact changed: ' + artifact['path'])
        checked.add(cid)
        pending.extend(row.get('dependencies', []))
    return dict(result, rotation_candidate=COMPONENT)


def require_normal_daily(handoff, at=None):
    scope = handoff.get('current_weekly_annihilation_intake') or {}
    if scope.get('validation_entrypoint') != ENTRYPOINT or scope.get('validation_status') != 'pending_normal_daily':
        raise ValueError('rotation validation not selected')
    now = at or datetime.now(LOCAL)
    start = datetime.fromisoformat(scope['normal_daily_not_before'])
    end = datetime.fromisoformat(scope['normal_daily_before'])
    if now.tzinfo is None or not start <= now < end:
        raise ValueError('rotation validation awaits normal daily window')
    return scope


def full():
    check_entry()
    h = read(ROOT / '.project-reasoning/AUTOMATION_HANDOFF.json')
    require_normal_daily(h)
    import arknights_daily_runtime_v12 as app
    import daily_workflow_identity_v1 as identity
    original_identity = identity.boundary
    # Retain V115's exact-instance and sign-in fixes. The production V112
    # graph is still checked, but is not mislabelled as this candidate.
    binding = dict(workflow=COMPONENT, entrypoint=ENTRYPOINT,
                   handoff_id=h['handoff_id'], sha256=sha(__file__))
    with boundary(app), retain_recent_event_fix(), patch.object(identity, 'boundary',
            lambda runtime, root, ignored: original_identity(runtime, root, binding)), \
         patch.object(previous, 'check_entry', check_entry):
        return previous.full()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['full'], default='full')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    if args.check_only:
        check_entry()
        print('PASS V116 offline; no game actions; live rotation acceptance pending')
        return 0
    sys.argv = [str(ROOT / 'run_daily.py'), '--mode', 'full']
    return full()


if __name__ == '__main__':
    raise SystemExit(main())
