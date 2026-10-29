"""Candidate V113: V112 daily plus proactive sign-in activity discovery."""
from contextlib import nullcontext
from unittest.mock import patch
import argparse
import sys
import run_daily_v112 as previous
import run_daily_v111 as identity_check
from run_daily_v103 import ROOT, read, sha
from event_signin_discovery_v6 import boundary

ENTRYPOINT = 'run_daily_v113.py --mode full'


def check_entry(at=None, packet=None):
    with patch.object(identity_check, 'ENTRYPOINT', ENTRYPOINT), \
         patch.object(identity_check, '__file__', __file__):
        return identity_check.check_entry(at, packet)


def full(packet=None):
    import daily_workflow_identity_v1 as identity
    old = identity.boundary
    h = read(ROOT/'.project-reasoning/AUTOMATION_HANDOFF.json')
    binding = dict(workflow='ARK-DAILY-STABLE-V113', entrypoint=ENTRYPOINT,
                   handoff_id=h['handoff_id'], sha256=sha(__file__))
    context = patch.object(identity, 'boundary', lambda runtime, root, ignored:
        old(runtime, root, binding)) if packet is None else nullcontext()
    with context, boundary(), patch.object(previous, 'check_entry',
            lambda at=None, packet=None: check_entry(at, packet)):
        return previous.full(packet)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--check-only', action='store_true')
    p.add_argument('--mode', choices=['full'], default='full')
    args = p.parse_args(argv)
    check_entry()
    if args.check_only:
        print('PASS V113; game actions0')
        return 0
    sys.argv = [str(ROOT/'run_daily.py'), '--mode', 'full']
    return full()


if __name__ == '__main__':
    raise SystemExit(main())
